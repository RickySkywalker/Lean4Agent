import asyncio
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp.client import Client, StreamableHttpTransport

from utils import json_default


def _append_jsonl(path: str, event: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, default=json_default)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    events: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            events.append(json.loads(raw))
    return events


class MCPClient:
    """
    Thin wrapper around fastmcp Client for this codebase.

    Durable execution note:
    - Sandbox tools require `ctx.session_id` which is ultimately derived from MCP's
      stateful Streamable HTTP session id (`mcp-session-id` header).
    - To support resume after process kill, we must be able to reattach to the same
      MCP session by re-sending the same `mcp-session-id`.
    """

    def __init__(
        self,
        url: str = None,
        tool_config_fp: str = None,
        *,
        session_id: Optional[str] = None,
        trace_path: Optional[str] = None,
        replay_trace_path: Optional[str] = None,
        connect: bool = True,
    ):
        hostname = os.getenv("MCP_HOSTNAME") or "localhost"
        port = os.getenv("MCP_PORT") or 7002
        basepath = os.getenv("MCP_BASEPATH") or "/mcp"
        self.server_url = url or f"http://{hostname}:{port}{basepath}"
        self._client: Client | None = None
        self._session_id: Optional[str] = session_id

        # Durable execution: tool-level trace/replay
        self._trace_path: Optional[str] = trace_path
        self._trace_lock = threading.Lock()
        self._trace_seq = 0
        self._replay_events: Optional[List[Dict[str, Any]]] = None
        self._replay_idx = 0
        self._replay_lock = threading.Lock()
        if replay_trace_path:
            self.enable_replay(replay_trace_path)

        # Thread lock for thread-safe access to the event loop
        # This is necessary because event loops are not thread-safe
        self._loop_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        if connect:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._init_client())

    def _update_session_id_from_transport(self) -> None:
        """
        Best-effort: capture current MCP session id from transport.
        """
        try:
            if not self._client:
                return
            transport = getattr(self._client, "transport", None)
            get_sid = getattr(transport, "get_session_id", None)
            if callable(get_sid):
                sid = get_sid()
                if sid:
                    self._session_id = str(sid)
        except Exception as e:
            print(f"Warning: Failed to extract session ID: {e}")
            # Never fail the main call due to session-id introspection.
            return

    async def _init_client(self):
        # If we have a session id (from checkpoint), attach to that server session.
        if self._session_id:
            transport = StreamableHttpTransport(
                url=self.server_url,
                headers={"mcp-session-id": self._session_id},
            )
            self._client = Client(transport)
        else:
            self._client = Client(self.server_url)
        await self._client.__aenter__()  # manually enter async context
        self._update_session_id_from_transport()

    async def _close_client(self):
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

    def close(self):
        """Public method to clean up the client"""
        if self._loop is None:
            return
        self._loop.run_until_complete(self._close_client())
        self._loop.close()
        self._loop = None

    def get_session_id(self) -> Optional[str]:
        """
        Return the current MCP Streamable HTTP session id, if known.

        This is the value that must be persisted in checkpoints to allow resuming
        with the same sandbox session (filesystem/browser/shell state).
        """
        self._update_session_id_from_transport()
        return self._session_id

    def enable_tracing(self, trace_path: str) -> None:
        """
        Enable append-only JSONL trace recording for every tool invocation via invoke().
        """
        self._trace_path = str(trace_path)

    def enable_replay(self, replay_trace_path: str) -> None:
        """
        Enable tool-output replay: invoke() will not call the server; it will return
        recorded tool outputs from the provided trace jsonl in order.
        """
        self._replay_events = _read_jsonl(str(replay_trace_path))
        self._replay_idx = 0

    def _replay_next(self) -> Dict[str, Any]:
        if not self._replay_events:
            raise RuntimeError("replay not enabled")
        while True:
            with self._replay_lock:
                if self._replay_idx >= len(self._replay_events):
                    raise IndexError("replay trace exhausted")
                ev = self._replay_events[self._replay_idx]
                self._replay_idx += 1
            # Trace may include mixed event types (e.g., llm_response, tool).
            if ev.get("type") == "tool":
                return ev

    def _maybe_apply_side_effects_in_replay(
        self, name: str, arguments: Dict[str, Any]
    ) -> None:
        # Best-effort: reproduce key artifacts without calling MCP.
        if name == "fs_write":
            try:
                path = arguments.get("path")
                content = arguments.get("content", "")
                append = bool(arguments.get("append", False))
                mode = arguments.get("mode", "text")
                if not isinstance(path, str) or mode != "text":
                    return

                # Security: restrict writes to workspace or current directory in replay
                p = Path(path)
                # If absolute, it must be within the current working directory or /workspace
                cwd = Path.cwd()
                try:
                    if p.is_absolute():
                        # Check if it's under CWD or /workspace
                        is_safe = False
                        if p.resolve().is_relative_to(cwd.resolve()):
                            is_safe = True
                        elif Path("/workspace").exists() and p.resolve().is_relative_to(
                            Path("/workspace").resolve()
                        ):
                            is_safe = True
                        elif p.resolve().is_relative_to(Path("/tmp").resolve()):
                            is_safe = True
                        # Also allow system temp directory (varies by OS, e.g. /var/folders on macOS)
                        elif p.resolve().is_relative_to(
                            Path(tempfile.gettempdir()).resolve()
                        ):
                            is_safe = True

                        if not is_safe:
                            # Skip unsafe absolute paths in replay side effects
                            return
                except (ValueError, RuntimeError):
                    # resolve() or is_relative_to() might fail on some platforms/path types
                    return

                p.parent.mkdir(parents=True, exist_ok=True)
                if append:
                    with p.open("a", encoding="utf-8") as f:
                        f.write(str(content))
                else:
                    p.write_text(str(content), encoding="utf-8")
            except Exception:
                return

    def invoke(
        self, name: str, arguments: Dict[str, Any], is_catch_exception=True
    ) -> Dict[str, Any]:
        # Replay mode: return recorded tool outputs deterministically
        if self._replay_events is not None:
            try:
                ev = self._replay_next()
                if ev.get("name") != name:
                    raise ValueError(
                        f"trace mismatch: expected tool {name}, got {ev.get('name')}"
                    )
                recorded_args = ev.get("arguments")
                if isinstance(recorded_args, dict) and recorded_args != (
                    arguments or {}
                ):
                    raise ValueError("trace mismatch: arguments differ")
                self._maybe_apply_side_effects_in_replay(name, arguments or {})
                result = ev.get("result")
                if isinstance(result, dict):
                    return result
                # Back-compat: allow non-dict results
                return {"result": result}
            except Exception as e:
                if is_catch_exception:
                    return {"error": f"Tool replay failed: {e}"}
                raise

        async def _invoke():
            if not self._client:
                raise RuntimeError("MCP client not connected")
            result = await self._client.call_tool(name, arguments)
            return result.data if hasattr(result, "data") else {"content": result}

        try:
            # Use lock to ensure thread-safe access to the event loop
            with self._loop_lock:
                if self._loop is None:
                    raise RuntimeError("MCP client not connected")
                out = self._loop.run_until_complete(_invoke())
            self._update_session_id_from_transport()
            # Trace tool call + output (append-only)
            if self._trace_path:
                with self._trace_lock:
                    self._trace_seq += 1
                    _append_jsonl(
                        self._trace_path,
                        {
                            "type": "tool",
                            "seq": self._trace_seq,
                            "ts": time.time(),
                            "session_id": self.get_session_id(),
                            "name": name,
                            "arguments": arguments or {},
                            "result": out,
                        },
                    )
            return out
        except Exception as e:
            if is_catch_exception:
                return {"error": f"Tool invocation failed: {e}"}
            else:
                raise

    def list_tools(self) -> List[Dict[str, Any]]:
        async def fetch():
            if not self._client:
                raise RuntimeError("MCP client not connected")
            tools = await self._client.list_tools()
            # Convert MCP tool objects to OpenAI function format (dicts)
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": (
                            tool.inputSchema if hasattr(tool, "inputSchema") else {}
                        ),
                    },
                }
                for tool in tools
            ]

        try:
            # Use lock to ensure thread-safe access to the event loop
            with self._loop_lock:
                if self._loop is None:
                    raise RuntimeError("MCP client not connected")
                tools = self._loop.run_until_complete(fetch())
            self._update_session_id_from_transport()
            if not isinstance(tools, list):
                raise RuntimeError("MCP did not return a list of tools.")
            return tools
        except Exception as e:
            raise RuntimeError(f"Failed to fetch tools from MCP: {e}")

    def make_mcp_tool_function(
        self, tool_name: str, param_names: list[str]
    ) -> callable:
        def wrapper(*args, is_catch_exception=True, **kwargs) -> dict:
            if len(args) > len(param_names):
                raise ValueError(
                    f"Too many arguments: expected {len(param_names)}, got {len(args)}"
                )
            arguments = dict(zip(param_names, args))
            arguments.update(kwargs)
            return self.invoke(tool_name, arguments, is_catch_exception)

        return wrapper

    def process_tool_calls(self, msg: Any) -> List[dict]:
        tool_calls = msg.tool_calls or []
        tool_calls_msg = []
        tool_results_msg = []

        if not tool_calls:
            return [], []

        tool_calls_msg.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = (
                    json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments
                ) or {}
            except Exception:
                args = {}
            try:
                result_dict = self.invoke(name, args, is_catch_exception=False)
            except Exception as e:
                tool_results_msg.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": f"error: Tool invocation failed with error {e}",
                    }
                )
                print(f"Tool {name} failed with error: {e}")
                continue

            tool_results_msg.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result_dict, default=str),
                }
            )
        return tool_calls_msg, tool_results_msg
