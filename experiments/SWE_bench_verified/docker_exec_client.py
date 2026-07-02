"""Docker exec-based MCP client for official SWE-bench images.

Instead of connecting to an MCP server, this client executes commands
directly in a Docker container via `docker exec`. This allows using
the official pre-built SWE-bench Docker images which have the repo
and conda env pre-built.

Architecture:
    LLM -> LLMExecutor -> mcp_client.invoke("shell_run") -> docker exec -> container
"""

import subprocess
import time
from typing import Any, Dict, List, Optional

from mcp_client.client import MCPClient, _append_jsonl

_SHELL_TIMEOUT = 300  # seconds per shell command
_OUTPUT_MAX_CHARS = 10_000  # truncate output longer than this
_OUTPUT_HALF_CHARS = 5_000  # keep this many chars from each end


class DockerExecClient(MCPClient):
    """MCP-compatible client that routes tool calls through `docker exec`.

    Subclasses MCPClient with connect=False to skip HTTP connection,
    then overrides invoke, list_tools, close, and get_session_id to
    use docker exec against an official SWE-bench container.
    """

    def __init__(
        self,
        image: str,
        container_id: Optional[str] = None,
    ):
        """Initialize DockerExecClient.

        Args:
            image: SWE-bench Docker image name (e.g. swebench/sweb.eval.x86_64.django_1776_django-10880:latest)
            container_id: Optional existing container ID for resume.
        """
        # Initialize parent without connecting to MCP server
        super().__init__(connect=False)

        self.image = image

        if container_id:
            self._container_id = container_id
        else:
            # Start a new container from the image
            # -w /testbed sets the default working directory (matches mini-swe-agent)
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "-w",
                    "/testbed",
                    image,
                    "sleep",
                    "7200",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Failed to start container from {image}: {result.stderr}"
                )
            self._container_id = result.stdout.strip()

        self._session_id = self._container_id
        print(f"[DockerExecClient] Container started: {self._container_id[:12]}")

        # Run eval-compatible setup (matches the SWE-bench eval harness script)
        if not container_id:
            self._setup_container()

    def _setup_container(self):
        """Run eval-compatible setup inside the container.

        Matches the setup steps from SWE-bench eval harness scripts.
        Environment variables are written to /etc/profile.d/ so they
        persist across separate `bash -lc` invocations (each docker exec
        starts a new login shell).
        """
        setup_cmd = " && ".join(
            [
                # Locale setup — generate locale and persist env vars via profile.d
                "sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen 2>/dev/null && locale-gen 2>/dev/null || true",
                # Write env vars to profile.d so every bash -lc invocation picks them up
                "echo 'export LANG=en_US.UTF-8' >> /etc/profile.d/swebench-setup.sh",
                "echo 'export LANGUAGE=en_US:en' >> /etc/profile.d/swebench-setup.sh",
                "echo 'export LC_ALL=en_US.UTF-8' >> /etc/profile.d/swebench-setup.sh",
                # Git safe directory
                "git config --global --add safe.directory /testbed",
                # Reinstall package in editable mode so source edits take effect
                "cd /testbed && python -m pip install -e . 2>&1 | tail -5",
            ]
        )
        result = self._exec_shell_run({"text": setup_cmd, "cwd": "/testbed"})
        if result.get("returncode", -1) != 0:
            print(
                f"[DockerExecClient] Warning: container setup returned non-zero: {result.get('output', '')[:500]}"
            )
        else:
            print(f"[DockerExecClient] Container setup complete")

    def invoke(
        self, name: str, arguments: Dict[str, Any], is_catch_exception=True
    ) -> Dict[str, Any]:
        """Route tool invocations through docker exec.

        Handles shell_run, fs_read, and fs_write tools.
        """
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
                return {"result": result}
            except Exception as e:
                if is_catch_exception:
                    return {"error": f"Tool replay failed: {e}"}
                raise

        try:
            if name == "shell_run":
                out = self._exec_shell_run(arguments or {})
            elif name == "fs_read":
                out = self._exec_fs_read(arguments or {})
            elif name == "fs_write":
                out = self._exec_fs_write(arguments or {})
            else:
                out = {"error": f"Unknown tool: {name}"}

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
                            "session_id": self._container_id,
                            "name": name,
                            "arguments": arguments or {},
                            "result": out,
                        },
                    )
            return out

        except Exception as e:
            if is_catch_exception:
                return {"error": f"Tool invocation failed: {e}"}
            raise

    def _exec_shell_run(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a shell command via docker exec."""
        text = arguments.get("text", "")
        cwd = arguments.get("cwd")
        # conda_env is intentionally ignored — the official SWE-bench images
        # activate the conda env via .bashrc in the login shell.

        # Build docker exec command (matches mini-swe-agent pattern)
        cmd = ["docker", "exec"]
        if cwd:
            cmd.extend(["-w", cwd])
        cmd.extend([self._container_id, "bash", "-lc", text])

        try:
            result = subprocess.run(
                cmd,
                timeout=_SHELL_TIMEOUT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
            )
            output = result.stdout
            if len(output) > _OUTPUT_MAX_CHARS:
                output = (
                    output[:_OUTPUT_HALF_CHARS]
                    + "\n... [truncated] ...\n"
                    + output[-_OUTPUT_HALF_CHARS:]
                )

            out = {
                "output": output,
                "returncode": result.returncode,
            }
            if result.returncode != 0:
                out["error"] = f"Command exited with code {result.returncode}"
            return out
        except subprocess.TimeoutExpired:
            return {
                "output": f"Command timed out after {_SHELL_TIMEOUT} seconds",
                "error": f"Command timed out after {_SHELL_TIMEOUT} seconds",
                "returncode": -1,
            }

    def _exec_fs_read(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Read a file from the container via docker exec."""
        path = arguments.get("path", "")

        try:
            result = subprocess.run(
                ["docker", "exec", self._container_id, "cat", path],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                return {"error": result.stderr}
            return {"data": result.stdout}
        except subprocess.TimeoutExpired:
            return {"error": "Read timed out"}

    def _exec_fs_write(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Write a file to the container via docker exec."""
        path = arguments.get("path", "")
        content = arguments.get("content", "")
        append = bool(arguments.get("append", False))

        # Use >> for append, > for overwrite; mkdir -p ensures parent dirs exist
        redirect = ">>" if append else ">"
        shell_cmd = f"mkdir -p $(dirname {_shell_quote(path)}) && cat {redirect} {_shell_quote(path)}"

        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    self._container_id,
                    "/bin/bash",
                    "-c",
                    shell_cmd,
                ],
                input=content,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                return {"error": result.stderr}
            return {"path": path}
        except subprocess.TimeoutExpired:
            return {"error": "Write timed out"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return hardcoded tool schemas matching the MCP server tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "shell_run",
                    "description": "Run a shell command in the container",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Command to run"},
                            "cwd": {
                                "type": "string",
                                "description": "Working directory",
                            },
                            "conda_env": {
                                "type": "string",
                                "description": "Conda environment name",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fs_read",
                    "description": "Read file contents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to read",
                            },
                            "max_bytes": {
                                "type": "integer",
                                "description": "Max bytes to read",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fs_write",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to write",
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to write",
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
        ]

    def get_session_id(self) -> Optional[str]:
        """Return the container ID as the session ID."""
        return self._container_id

    def close(self):
        """Stop and remove the Docker container."""
        if self._container_id:
            print(f"[DockerExecClient] Stopping container: {self._container_id[:12]}")
            try:
                subprocess.run(
                    ["docker", "stop", self._container_id],
                    capture_output=True,
                    timeout=30,
                )
            except Exception as e:
                print(f"[DockerExecClient] Warning: failed to stop container: {e}")
            self._container_id = None

    @staticmethod
    def resolve_image_name(instance_id: str) -> str:
        """Convert an instance_id to the official SWE-bench Docker image name.

        Args:
            instance_id: e.g. "django__django-10880"

        Returns:
            Image name e.g. "swebench/sweb.eval.x86_64.django_1776_django-10880:latest"
        """
        sanitized = instance_id.replace("__", "_1776_")
        return f"swebench/sweb.eval.x86_64.{sanitized}:latest".lower()


def _shell_quote(s: str) -> str:
    """Quote a string for safe use in shell commands."""
    return "'" + s.replace("'", "'\"'\"'") + "'"
