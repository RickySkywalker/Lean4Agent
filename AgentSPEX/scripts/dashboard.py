"""
Agent Log Dashboard: A real-time log viewer with collapsible sections for monitoring YAML agent execution.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

from flask import (Flask, abort, jsonify, render_template_string, request,
                   send_file)
from flask_socketio import SocketIO, emit, join_room, leave_room

logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("socketio").setLevel(logging.ERROR)
logging.getLogger("engineio").setLevel(logging.ERROR)

# Ports blocked by browsers (Chrome, Firefox, etc.) for security reasons
UNSAFE_PORTS = {
    5060,
    5061,  # SIP
    6000,  # X11
    6566,  # SANE
    6665,
    6666,
    6667,
    6668,
    6669,  # IRC
}


def find_available_port(start_port: int, host: str = "127.0.0.1") -> int:
    """Find an available port starting from start_port.

    Skips ports that browsers block for security reasons.
    """
    port = start_port
    while port < start_port + 100:
        if port in UNSAFE_PORTS:
            port += 1
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                port += 1
    raise RuntimeError(
        f"No available port found in range {start_port}-{start_port + 99}"
    )


# =============================================================================
# Event Parsing
# =============================================================================

EVENT_START = "<<<EVENT>>>"
EVENT_END = "<<</EVENT>>>"


@dataclass
class ParsedEvent:
    """Parsed log event."""

    type: str
    timestamp: str
    data: Dict[str, Any]
    raw_line: str = ""


@dataclass
class AgentIteration:
    """Represents an agent iteration."""

    number: int
    max: int
    tokens: int = 0
    limit: int = 0
    utilization: float = 0.0
    reasoning_tokens: int = 0
    content: List[str] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    context_tokens: int = 0
    context_limit: int = 0


@dataclass
class Step:
    """Represents a workflow step."""

    step_id: str
    number: str
    name: str
    step_type: str
    instruction: str = ""
    depth: int = 0
    parent_step_id: Optional[str] = None
    parent_iteration: Optional[int] = None
    tokens: int = 0
    status: str = "running"
    variables: Dict[str, str] = field(default_factory=dict)
    iterations: List[AgentIteration] = field(default_factory=list)
    events: List[ParsedEvent] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""


@dataclass
class Workflow:
    """Represents the entire workflow."""

    task_name: str = ""
    goal: str = ""
    model: str = ""
    steps: List[Step] = field(default_factory=list)
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float = 0.0
    status: str = "running"
    start_time: str = ""
    end_time: str = ""
    raw_lines: List[str] = field(default_factory=list)


class LogParser:
    """Parses structured log events."""

    def __init__(self):
        self.workflow = Workflow()
        self._current_step: Optional[Step] = None
        self._current_iteration: Optional[AgentIteration] = None
        self._current_tool: Optional[Dict[str, Any]] = None
        self._call_index: Dict[tuple, Dict[str, Any]] = {}
        self._step_index: Dict[str, Step] = {}
        self._iteration_index: Dict[tuple, AgentIteration] = {}

    def _get_step(self, step_id: str) -> Step:
        step = self._step_index.get(step_id)
        if step:
            return step
        step = Step(
            step_id=step_id,
            number=step_id,
            name=f"Step {step_id}",
            step_type="step",
        )
        self._step_index[step_id] = step
        self.workflow.steps.append(step)
        return step

    def _get_iteration(self, step_id: str, iteration_number: int) -> AgentIteration:
        key = (step_id, iteration_number)
        iteration = self._iteration_index.get(key)
        if iteration:
            return iteration
        step = self._get_step(step_id)
        iteration = AgentIteration(number=iteration_number, max=0)
        step.iterations.append(iteration)
        self._iteration_index[key] = iteration
        return iteration

    def parse_line(self, line: str) -> Optional[ParsedEvent]:
        """Parse a single log line."""
        self.workflow.raw_lines.append(line)

        # Check for structured event
        if EVENT_START in line and EVENT_END in line:
            try:
                start = line.index(EVENT_START) + len(EVENT_START)
                end = line.index(EVENT_END)
                event_json = line[start:end]
                event_data = json.loads(event_json)
                event = ParsedEvent(
                    type=event_data.get("type", "unknown"),
                    timestamp=event_data.get("timestamp", ""),
                    data=event_data.get("data", {}),
                    raw_line=line,
                )
                self._process_event(event)
                return event
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    def _process_event(self, event: ParsedEvent):
        """Process a parsed event and update workflow state."""
        data = event.data
        etype = event.type

        if etype == "workflow_start":
            self.workflow.task_name = data.get("task_name", "")
            self.workflow.goal = data.get("goal", "")
            self.workflow.model = data.get("model", "")
            self.workflow.start_time = event.timestamp
            self.workflow.status = "running"
            self.workflow.total_tokens = 0
            self.workflow.prompt_tokens = 0
            self.workflow.completion_tokens = 0
            self.workflow.reasoning_tokens = 0
            self.workflow.cost = 0.0

        elif etype == "workflow_end":
            self.workflow.total_tokens = data.get("total_tokens", 0)
            self.workflow.prompt_tokens = data.get("prompt_tokens", 0)
            self.workflow.completion_tokens = data.get("completion_tokens", 0)
            self.workflow.reasoning_tokens = data.get("reasoning_tokens", 0)
            self.workflow.cost = float(data.get("cost", 0) or 0)
            self.workflow.end_time = event.timestamp
            self.workflow.status = "completed"

        elif etype == "step_start":
            step_id = str(data.get("step_id") or data.get("step_number") or "?")
            step = self._get_step(step_id)
            step.number = str(data.get("step_number", step_id))
            step.name = data.get("name", step.name)
            step.step_type = data.get("step_type", step.step_type)
            step.instruction = data.get("instruction", step.instruction)
            step.depth = int(data.get("depth", step.depth or 0))
            step.parent_step_id = data.get("parent_step_id") or step.parent_step_id
            if data.get("parent_iteration") is not None:
                try:
                    step.parent_iteration = int(data.get("parent_iteration"))
                except Exception:
                    step.parent_iteration = step.parent_iteration
            step.variables = data.get("variables", {})
            step.start_time = event.timestamp
            step.status = "running"
            self._current_step = step

        elif etype == "step_end":
            step_id = str(data.get("step_id") or data.get("step_number") or "?")
            step = self._step_index.get(step_id)
            if step:
                step.tokens = data.get("tokens", 0)
                step.end_time = event.timestamp
                step.status = data.get("status", "completed")
            if self._current_step and self._current_step.step_id == step_id:
                self._current_step = None

        elif etype == "agent_iteration":
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("number", 0))
            iteration = self._get_iteration(step_id, iteration_number)
            iteration.max = data.get("max", iteration.max)
            iteration.tokens = data.get("tokens", iteration.tokens)
            iteration.limit = data.get("limit", iteration.limit)
            iteration.utilization = data.get("utilization", iteration.utilization)
            self._current_iteration = iteration

        elif etype == "messages_start":
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("iteration", 1))
            iteration = self._get_iteration(step_id, iteration_number)
            iteration.messages = data.get("messages", [])
            iteration.context_tokens = data.get("context_tokens", 0)
            iteration.context_limit = data.get("context_limit", 0)
            iteration.utilization = data.get("utilization", iteration.utilization)
            self._current_iteration = iteration

        elif etype == "messages_end":
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("iteration", 1))
            iteration = self._get_iteration(step_id, iteration_number)
            iteration.usage = data.get("usage", {})
            usage = iteration.usage or {}
            self.workflow.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self.workflow.completion_tokens += int(
                usage.get("completion_tokens", 0) or 0
            )
            self.workflow.total_tokens += int(usage.get("total_tokens", 0) or 0)
            reasoning_tokens = int(usage.get("reasoning_tokens", 0) or 0)
            iteration.reasoning_tokens = reasoning_tokens
            self.workflow.reasoning_tokens += reasoning_tokens
            self.workflow.cost += float(usage.get("cost", 0) or 0)

        elif etype == "llm_response":
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("iteration", 1))
            iteration = self._get_iteration(step_id, iteration_number)
            iteration.content.append(data.get("content", ""))

        elif etype in ("tool_call_start", "parallel_call_start", "module_start"):
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("iteration", 1))
            iteration = self._get_iteration(step_id, iteration_number)
            call_id = int(data.get("call", len(iteration.timeline) + 1))
            entry = {
                "call": call_id,
                "name": data.get("name", "unknown"),
                "args": data.get("args") or data.get("params") or "",
                "result": None,
                "kind": etype,
            }
            iteration.timeline.append(entry)
            self._call_index[(step_id, iteration_number, call_id)] = entry

        elif etype in ("tool_call_end", "parallel_call_end", "module_end"):
            step_id = str(data.get("step_id") or "?")
            iteration_number = int(data.get("iteration", 1))
            call_id = int(data.get("call", 0)) or None
            if call_id:
                entry = self._call_index.get((step_id, iteration_number, call_id))
                if entry:
                    entry["result"] = str(data.get("result", ""))
            else:
                iteration = self._get_iteration(step_id, iteration_number)
                if iteration.timeline:
                    iteration.timeline[-1]["result"] = str(data.get("result", ""))

        elif etype in ("info", "warning", "error", "debug"):
            step_id = str(data.get("step_id") or "")
            iteration_number = data.get("iteration")
            msg_text = data.get("message", "")
            if step_id and iteration_number is not None:
                iteration = self._get_iteration(step_id, int(iteration_number))
                iteration.content.append(f"[{etype.upper()}] {msg_text}")
            elif step_id:
                step = self._get_step(step_id)
                step.events.append(event)
            elif self._current_iteration:
                self._current_iteration.content.append(f"[{etype.upper()}] {msg_text}")
            elif self._current_step:
                self._current_step.events.append(event)

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary for JSON serialization."""
        return {
            "task_name": self.workflow.task_name,
            "goal": self.workflow.goal,
            "model": self.workflow.model,
            "status": self.workflow.status,
            "total_tokens": self.workflow.total_tokens,
            "prompt_tokens": self.workflow.prompt_tokens,
            "completion_tokens": self.workflow.completion_tokens,
            "reasoning_tokens": self.workflow.reasoning_tokens,
            "cost": self.workflow.cost,
            "start_time": self.workflow.start_time,
            "end_time": self.workflow.end_time,
            "steps": [
                {
                    "step_id": step.step_id,
                    "number": step.number,
                    "name": step.name,
                    "type": step.step_type,
                    "instruction": step.instruction,
                    "depth": step.depth,
                    "parent_step_id": step.parent_step_id,
                    "parent_iteration": step.parent_iteration,
                    "tokens": step.tokens,
                    "variables": step.variables,
                    "status": step.status,
                    "start_time": step.start_time,
                    "end_time": step.end_time,
                    "iterations": [
                        {
                            "number": it.number,
                            "max": it.max,
                            "tokens": it.tokens,
                            "limit": it.limit,
                            "utilization": it.utilization,
                            "timeline": getattr(it, "timeline", []),
                            "messages": it.messages,
                            "usage": it.usage,
                            "reasoning_tokens": it.reasoning_tokens,
                            "context_tokens": it.context_tokens,
                            "context_limit": it.context_limit,
                            "content": it.content,  # full content for transparency
                        }
                        for it in step.iterations
                    ],
                    "events": [
                        {"type": ev.type, "message": ev.data.get("message", "")}
                        for ev in step.events
                    ],
                }
                for step in self.workflow.steps
            ],
            "raw_line_count": len(self.workflow.raw_lines),
        }


# =============================================================================
# Log Sessions
# =============================================================================


def _room_for_path(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
    return f"log:{digest}"


class LogSession:
    def __init__(self, path: Path, socketio: SocketIO, shutdown_event: threading.Event):
        self.path = path
        self.socketio = socketio
        self.shutdown_event = shutdown_event
        self.room = _room_for_path(path)
        self.parser = LogParser()
        self.lock = threading.Lock()
        self.subscribers: Set[str] = set()
        self.missing = False
        self._watching = False
        self._thread: Optional[threading.Thread] = None
        self._last_position = 0
        self._last_size = 0
        self._last_inode: Optional[int] = None
        self._loaded = False

    def _reset_parser(self) -> None:
        with self.lock:
            self.parser = LogParser()
        self._last_position = 0
        self._last_size = 0

    def _read_full(self) -> None:
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                self.parser.parse_line(line.rstrip("\n"))
            self._last_position = f.tell()
        try:
            stat = self.path.stat()
            self._last_size = stat.st_size
            self._last_inode = stat.st_ino
        except Exception:
            pass

    def load_initial(self) -> None:
        if not self.path.exists():
            self.missing = True
            return
        self.missing = False
        self._reset_parser()
        with self.lock:
            self._read_full()
        self._loaded = True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._watching = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._watching = False

    def state(self) -> Dict[str, Any]:
        with self.lock:
            state = self.parser.to_dict()
        state["log_path"] = str(self.path)
        state["log_missing"] = self.missing
        return state

    def emit_full_state(self, sid: str) -> None:
        self.socketio.emit("full_state", self.state(), to=sid)

    def emit_update(self) -> None:
        self.socketio.emit("update", self.state(), to=self.room)

    def _watch_loop(self) -> None:
        while self._watching and not self.shutdown_event.is_set():
            if not self.path.exists():
                if not self.missing:
                    self.missing = True
                    self.emit_update()
                time.sleep(1)
                continue

            self.missing = False
            try:
                stat = self.path.stat()
            except Exception:
                time.sleep(1)
                continue

            size = stat.st_size
            inode = stat.st_ino

            rotated = self._last_inode is not None and inode != self._last_inode
            truncated = size < self._last_size

            if self._last_inode is None or rotated or truncated:
                self._reset_parser()
                with self.lock:
                    self._read_full()
                self.emit_update()
                time.sleep(0.2)
                continue

            if size > self._last_size:
                try:
                    with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._last_position)
                        new_content = f.read()
                        self._last_position = f.tell()
                        self._last_size = size
                    with self.lock:
                        for line in new_content.splitlines():
                            self.parser.parse_line(line.rstrip("\n"))
                    self.emit_update()
                except Exception:
                    time.sleep(1)
                    continue

            time.sleep(0.5)


class LogManager:
    def __init__(
        self,
        root: Optional[Path],
        socketio: SocketIO,
        shutdown_event: threading.Event,
        initial_path: Optional[Path] = None,
    ):
        self.root = root
        self.socketio = socketio
        self.shutdown_event = shutdown_event
        self.initial_path = initial_path
        self.sessions: Dict[str, LogSession] = {}
        self.sid_to_path: Dict[str, str] = {}
        self.lock = threading.Lock()

    def list_logs(self) -> list[dict]:
        return _collect_logs(self.root)

    def _default_path(self) -> Optional[str]:
        if self.initial_path:
            return str(self.initial_path)
        logs = self.list_logs()
        if not logs:
            return None
        return logs[0].get("path")

    def _get_or_create(self, path: Path) -> LogSession:
        key = str(path)
        session = self.sessions.get(key)
        if session:
            return session
        session = LogSession(path, self.socketio, self.shutdown_event)
        session.load_initial()
        self.sessions[key] = session
        return session

    def subscribe(self, sid: str, path: Optional[str]) -> Optional[LogSession]:
        with self.lock:
            if not path:
                path = self._default_path()
            if not path:
                return None
            resolved = _safe_resolve(path)
            if not resolved:
                return None
            resolved_str = str(resolved)

            current = self.sid_to_path.get(sid)
            if current and current != resolved_str:
                self._leave_room(sid, current)

            session = self._get_or_create(resolved)
            self.sid_to_path[sid] = resolved_str
            session.subscribers.add(sid)
            join_room(session.room, sid=sid)
            session.start()
            return session

    def unsubscribe(self, sid: str) -> None:
        with self.lock:
            current = self.sid_to_path.pop(sid, None)
            if not current:
                return
            self._leave_room(sid, current)

    def _leave_room(self, sid: str, path_str: str) -> None:
        session = self.sessions.get(path_str)
        if not session:
            return
        if sid in session.subscribers:
            session.subscribers.discard(sid)
        leave_room(session.room, sid=sid)
        if not session.subscribers:
            session.stop()

    def current_path(self, sid: str) -> Optional[str]:
        return self.sid_to_path.get(sid)


# =============================================================================
# Flask Application
# =============================================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = "agent-dashboard-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global state
log_root_path: Optional[Path] = None
log_manager: Optional[LogManager] = None
connected_clients: Set[str] = set()
shutdown_event = threading.Event()


def trigger_shutdown(reason: str = ""):
    """Stop the server and exit when there are no more clients."""
    if reason:
        print(reason)
    if shutdown_event.is_set():
        return
    shutdown_event.set()

    def _stop():
        # Give the watcher loop a moment to exit
        time.sleep(0.2)
        try:
            socketio.stop()
        except Exception:
            pass
        # Ensure process exits
        sys.exit(0)

    threading.Thread(target=_stop, daemon=True).start()


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Logs</title>
    <!-- Realtime is optional; UI works via polling. -->
    <style>
        :root {
            --bg: #0f1115;
            --bg-alt: #161920;
            --bg-hover: #1d212a;
            --border: #262c36;
            --text: #f5f7fb;
            --text-dim: #c7cedd;
            --text-dimmer: #8d95a6;
            --accent: #8bb5ff;
            --green: #8fd19e;
            --yellow: #e3c07b;
            --red: #f28b82;
            --orange: #ffb072;
            --purple: #c9a0ff;
            --cyan: #7bd9ff;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
            font-size: 13px;
            line-height: 1.5;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
        }

        /* Header bar */
        .header {
            background: var(--bg-alt);
            border-bottom: 1px solid var(--border);
            padding: 8px 16px;
            position: sticky;
            top: 0;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .log-controls {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .log-search-wrap {
            position: relative;
            min-width: 280px;
            max-width: 520px;
        }

        .log-search {
            background: var(--bg);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 4px 6px;
            font-size: 12px;
            font-family: inherit;
            width: 100%;
            box-sizing: border-box;
            outline: none;
        }

        .log-search:focus {
            border-color: var(--accent);
        }

        .log-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 4px;
            margin-top: 2px;
            max-height: 260px;
            overflow-y: auto;
            z-index: 1000;
        }

        .log-dropdown.open {
            display: block;
        }

        .log-option {
            padding: 4px 8px;
            font-size: 12px;
            cursor: pointer;
            color: var(--text);
        }

        .log-option:hover {
            background: var(--bg-hover);
        }

        .log-option.active {
            color: var(--accent);
        }

        .log-group-label {
            padding: 4px 8px;
            font-size: 11px;
            color: var(--yellow);
            font-weight: 600;
            pointer-events: none;
        }

        .header-title {
            color: var(--text);
            font-weight: 600;
            font-size: 13px;
        }

        .header-task {
            color: var(--text-dim);
            font-size: 12px;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 12px;
            color: var(--text-dim);
        }

        .status {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }

        .status-dot.running { background: var(--yellow); }
        .status-dot.completed { background: var(--green); }
        .status-dot.error { background: var(--red); }

        /* Stats bar */
        .stats {
            background: var(--bg);
            border-bottom: 1px solid var(--border);
            padding: 6px 16px;
            display: flex;
            gap: 24px;
            font-size: 12px;
            color: var(--text-dim);
        }

        .stat { display: flex; gap: 6px; }
        .stat-value { color: var(--text); }

        /* Minimap */
        .minimap {
            position: sticky;
            top: 42px;
            z-index: 90;
            background: var(--bg-alt);
            border-bottom: 1px solid var(--border);
            padding: 6px 16px 8px;
            display: none;
        }
        .minimap.visible { display: block; }
        .minimap-legend {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 4px;
            font-size: 11px;
            color: var(--text-dim);
        }
        .minimap-legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .minimap-legend-dot {
            width: 8px;
            height: 8px;
            border-radius: 2px;
            display: inline-block;
        }
        .minimap-bar {
            display: flex;
            gap: 1px;
            height: 16px;
            border-radius: 3px;
            overflow: hidden;
            cursor: pointer;
        }
        .minimap-seg {
            min-width: 3px;
            flex: 1;
            border-radius: 1px;
            transition: opacity 0.15s;
        }
        .minimap-seg:hover {
            opacity: 0.7;
        }
        .minimap-seg[data-role="system"] { background: var(--purple); }
        .minimap-seg[data-role="user"] { background: var(--green); }
        .minimap-seg[data-role="assistant"] { background: var(--accent); }
        .minimap-seg[data-role="tool"] { background: var(--orange); }
        .minimap-seg[data-role="error"] { background: var(--red); }
        .minimap-seg[data-role="unknown"] { background: var(--text-dimmer); }
        .minimap-step-sep {
            width: 3px;
            background: var(--bg);
            flex-shrink: 0;
        }

        /* Main content */
        .main {
            padding: 0 0 60px 0;
        }

        /* Step */
        .step {
            border-bottom: 1px solid var(--border);
        }

        .step-header {
            padding: 10px 16px;
            cursor: pointer;
            display: flex;
            align-items: flex-start;
            gap: 8px;
            user-select: none;
        }

        .step-header:hover {
            background: var(--bg-hover);
        }

        .step-toggle {
            color: var(--text-dimmer);
            width: 16px;
            flex-shrink: 0;
            text-align: center;
        }

        .step.expanded .step-toggle { color: var(--text-dim); }

        .step.step-selected {
            border-left: 3px solid var(--accent);
            background: var(--bg-hover);
        }

        .step-icon {
            color: var(--accent);
            width: 16px;
            flex-shrink: 0;
        }

        .step-info { flex: 1; min-width: 0; }

        .step-title {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .step-name {
            color: var(--text);
            font-weight: 500;
        }

        .step-type {
            color: var(--text-dimmer);
            font-size: 11px;
        }

        .step-meta {
            color: var(--text-dim);
            font-size: 11px;
            margin-top: 2px;
        }

        .step-status {
            font-size: 11px;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .step-status.running { color: var(--yellow); }
        .step-status.completed { color: var(--green); }

        .vars-btn {
            font-size: 10px;
            padding: 1px 6px;
            border: 1px solid var(--border);
            border-radius: 3px;
            background: var(--bg-surface);
            color: var(--text-dim);
            cursor: pointer;
            margin-right: 8px;
            white-space: nowrap;
        }
        .vars-btn:hover { color: var(--text); border-color: var(--text-dim); }

        .vars-popup {
            display: none;
            position: absolute;
            right: 0;
            top: 100%;
            z-index: 100;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 10px 14px;
            min-width: 360px;
            max-width: 600px;
            max-height: 400px;
            overflow: auto;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            font-size: 12px;
            line-height: 1.4;
        }
        .vars-popup.show { display: block; }
        .vars-row {
            display: flex;
            gap: 8px;
            padding: 4px 0;
            border-bottom: 1px solid var(--border);
        }
        .vars-row:last-child { border-bottom: none; }
        .vars-key {
            color: var(--cyan);
            font-weight: 500;
            white-space: nowrap;
            flex-shrink: 0;
            min-width: 100px;
        }
        .vars-val {
            color: var(--text-dim);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            flex: 1;
        }
        .vars-val.clickable { cursor: pointer; }
        .vars-val.clickable:hover { color: var(--text); }
        .vars-empty {
            color: var(--text-dimmer);
            font-style: italic;
        }

        .vars-modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            z-index: 200;
            background: rgba(0,0,0,0.85);
            align-items: center;
            justify-content: center;
        }
        .vars-modal-overlay.show { display: flex; }
        .vars-modal {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            min-width: 400px;
            max-width: 80vw;
            max-height: 70vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        }
        .vars-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }
        .vars-modal-title {
            color: var(--cyan);
            font-weight: 600;
            font-size: 13px;
        }
        .vars-modal-close {
            background: none;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            font-size: 16px;
            padding: 2px 6px;
        }
        .vars-modal-close:hover { color: var(--text); }
        .vars-modal-body {
            overflow: auto;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            color: var(--text);
        }

        .step-content {
            display: none;
            padding: 0 16px 12px 40px;
        }

        .step.expanded .step-content { display: block; }

        /* Instruction */
        .instruction {
            background: var(--bg-alt);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 8px 12px;
            margin-bottom: 8px;
            color: var(--text-dim);
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 280px;
            overflow: auto;
            display: block;
        }

        /* Iteration */
        .iteration {
            margin-top: 6px;
        }

        .iteration-header {
            padding: 6px 0;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
        }

        .iteration-header:hover { color: var(--text); }

        .iteration-toggle {
            color: var(--text-dimmer);
            width: 12px;
        }

        .iteration[open] .iteration-toggle { color: var(--text-dim); }

        .iteration-label {
            color: var(--purple);
        }

        .iteration-meta {
            color: var(--text-dimmer);
            margin-left: auto;
        }

        .iteration-content {
            display: none;
            padding-left: 20px;
        }

        .iteration[open] .iteration-content { display: block; }

        /* Message prefix collapse */
        .msg-prefix-summary {
            font-size: 13px;
        }
        .msg-prefix-label {
            color: var(--text-dim);
            font-style: italic;
        }
        .msg-prefix-hint-expand,
        .msg-prefix-hint-collapse {
            color: var(--text-dimmer);
            font-size: 12px;
            margin-left: 4px;
        }
        .msg-prefix-collapse .msg-prefix-hint-collapse { display: none; }
        .msg-prefix-collapse .msg-prefix-hint-expand { display: inline; }
        .msg-prefix-collapse[open] .msg-prefix-hint-collapse { display: inline; }
        .msg-prefix-collapse[open] .msg-prefix-hint-expand { display: none; }

        /* Tool call */
        .tool {
            padding: 0;
            font-size: 12px;
            border-left: 2px solid var(--border);
            padding-left: 10px;
            margin: 0;
        }
        .tool.message {
            margin-top: 6px;
        }
        .tool summary {
            margin: 0;
            padding: 0;
        }
        .tool[open] > summary {
            margin-bottom: 0;
        }

        .tool-header {
            display: flex;
            align-items: flex-start;
            gap: 6px;
        }

        .tool-name {
            color: var(--cyan);
        }

        .tool-name.module {
            color: var(--orange);
        }
        .tool-name.parallel {
            color: var(--yellow);
        }
        .role-label {
            font-weight: 600;
        }
        .role-system { color: var(--purple); }
        .role-user { color: var(--green); }
        .role-assistant { color: var(--accent); }
        .role-tool { color: var(--orange); }

        .tool-args {
            color: var(--text-dimmer);
            font-size: 11px;
            margin-top: 0;
            word-break: break-all;
        }

        .tool-result {
            color: var(--text-dim);
            font-size: 11px;
            margin-top: 0;
            padding: 0;
            background: transparent;
            border-radius: 0;
            display: contents;
        }

        .tool-args, .tool-result {
            display: flex;
            flex-direction: column;
            gap: 0;
            margin: 0;
            padding: 0;
        }
        .tool-args > summary, .tool-result > summary {
            margin: 0;
            padding: 0;
        }
        .tool-args > .tool-box, .tool-result > .tool-box {
            margin: 0;
        }
        .tool-result::after, .tool-result::before {
            display: none;
        }

        .tool-label {
            color: var(--text);
            font-weight: 600;
            margin-bottom: 0;
        }

        .tool-box {
            background: var(--bg-alt);
            border: 1px solid var(--border);
            border-radius: 3px;
            padding: 4px 8px;
            white-space: pre-wrap;
            word-break: break-word;
            color: var(--text-dim);
            font-size: 11px;
            margin: 0;
            max-height: 280px;
            overflow-y: auto;
        }
        /* Screenshot thumbnail inside tool output */
        .tool-screenshot {
            display: flex;
            flex-direction: column;
            gap: 0;
            margin: 0;
            padding: 0;
            font-size: 11px;
            color: var(--text-dim);
        }
        .tool-screenshot > summary {
            margin: 0;
            padding: 0;
            cursor: pointer;
            color: var(--text);
            font-weight: 600;
        }
        .screenshot-thumb-wrap {
            margin: 4px 0 0 0;
            position: relative;
            display: inline-block;
        }
        .screenshot-thumb {
            display: block;
            max-width: 100%;
            width: 320px;
            border: 1px solid var(--border);
            border-radius: 3px;
            cursor: zoom-in;
            transition: opacity 0.15s;
        }
        .screenshot-thumb:hover {
            opacity: 0.85;
        }
        .screenshot-zoom-hint {
            position: absolute;
            bottom: 6px;
            right: 6px;
            background: rgba(0,0,0,0.6);
            color: #fff;
            font-size: 10px;
            padding: 2px 5px;
            border-radius: 3px;
            pointer-events: none;
        }

        /* Lightbox modal */
        .lightbox-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.85);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            cursor: zoom-out;
        }
        .lightbox-overlay.show {
            display: flex;
        }
        .lightbox-inner {
            position: relative;
            max-width: 95vw;
            max-height: 95vh;
        }
        .lightbox-img {
            display: block;
            max-width: 95vw;
            max-height: 95vh;
            border-radius: 4px;
            box-shadow: 0 8px 40px rgba(0,0,0,0.7);
        }
        .lightbox-close {
            position: absolute;
            top: -14px;
            right: -14px;
            width: 28px;
            height: 28px;
            background: var(--bg-alt);
            border: 1px solid var(--border);
            border-radius: 50%;
            color: var(--text);
            font-size: 16px;
            line-height: 26px;
            text-align: center;
            cursor: pointer;
        }

        .payload-box {
            line-height: 1.3;
            max-height: 280px;
            overflow-y: auto;
        }

        /* Context bar */
        .context-bar {
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .context-track {
            width: 60px;
            height: 4px;
            background: var(--border);
            border-radius: 2px;
            overflow: hidden;
        }

        .context-fill {
            height: 100%;
            border-radius: 2px;
        }

        .context-fill.low { background: var(--green); }
        .context-fill.medium { background: var(--yellow); }
        .context-fill.high { background: var(--red); }

        /* Footer */
        .footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: var(--bg-alt);
            border-top: 1px solid var(--border);
            padding: 8px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }

        .footer-left {
            color: var(--text-dim);
            display: flex;
            gap: 16px;
        }

        .footer-right {
            display: flex;
            gap: 8px;
        }

        .btn {
            background: var(--bg);
            border: 1px solid var(--border);
            color: var(--text-dim);
            padding: 4px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-family: inherit;
            font-size: 11px;
        }

        .btn:hover {
            background: var(--bg-hover);
            color: var(--text);
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        .btn-refresh-content {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: opacity 0.35s ease;
        }

        @keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }

        .btn-refresh-spinner {
            display: none;
            width: 12px;
            height: 12px;
            border: 1.5px solid var(--text-dimmer);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite, fade-in 0.35s ease;
        }

        .btn.spinning {
            pointer-events: none;
            position: relative;
        }

        .btn.spinning .btn-refresh-content {
            opacity: 0;
        }

        .btn.spinning .btn-refresh-spinner {
            display: block;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            margin: auto;
        }

        /* Empty state */
        .empty {
            padding: 40px 16px;
            text-align: center;
            color: var(--text-dim);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: var(--bg); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-dimmer); }

        /* New content indicator */
        .new-content {
            position: fixed;
            bottom: 50px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--bg-alt);
            border: 1px solid var(--border);
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 11px;
            color: var(--text-dim);
            cursor: pointer;
            display: none;
        }

        .new-content.visible { display: block; }
    </style>
</head>
<body>
    <header class="header">
        <div class="header-left">
            <span class="header-title">Agent Logs</span>
            <div class="log-controls">
                <div class="log-search-wrap">
                    <input type="text" id="log-search" class="log-search" placeholder="Search logs..." autocomplete="off" />
                    <div class="log-dropdown" id="log-dropdown"></div>
                </div>
                <button class="btn" id="btn-refresh-logs" title="Refresh logs" style="position:relative"><span class="btn-refresh-content">↻ refresh</span><span class="btn-refresh-spinner"></span></button>
            </div>
            <span class="header-task" id="task-name">-</span>
        </div>
        <div class="header-right">
            <div class="status">
                <span class="status-dot" id="status-dot"></span>
                <span id="status-text">-</span>
            </div>
            <span id="connection">connected</span>
        </div>
    </header>

    <div class="stats">
        <div class="stat">steps: <span class="stat-value" id="stat-steps">0</span></div>
        <div class="stat">iterations: <span class="stat-value" id="stat-iterations">0</span></div>
        <div class="stat">tool calls: <span class="stat-value" id="stat-tools">0</span></div>
        <div class="stat">tokens: <span class="stat-value" id="stat-tokens">0</span></div>
        <div class="stat">prompt: <span class="stat-value" id="stat-prompt">0</span></div>
        <div class="stat">completion: <span class="stat-value" id="stat-completion">0</span></div>
        <div class="stat">reasoning: <span class="stat-value" id="stat-reasoning">0</span></div>
        <div class="stat">cost: <span class="stat-value" id="stat-cost">$0.00</span></div>
    </div>

    <div class="minimap" id="minimap">
        <div class="minimap-legend">
            <span style="color: var(--text); font-weight: 500;" id="minimap-title">Minimap</span>
            <span class="minimap-legend-item"><span class="minimap-legend-dot" style="background:var(--purple)"></span> System</span>
            <span class="minimap-legend-item"><span class="minimap-legend-dot" style="background:var(--green)"></span> User</span>
            <span class="minimap-legend-item"><span class="minimap-legend-dot" style="background:var(--accent)"></span> Assistant</span>
            <span class="minimap-legend-item"><span class="minimap-legend-dot" style="background:var(--orange)"></span> Tool</span>
            <span class="minimap-legend-item"><span class="minimap-legend-dot" style="background:var(--red)"></span> Error</span>
        </div>
        <div class="minimap-bar" id="minimap-bar"></div>
    </div>

    <div class="main" id="main">
        <div class="empty">Waiting for agent output...</div>
    </div>

    <div class="footer">
        <div class="footer-left">
            <span>Press <kbd>j</kbd>/<kbd>k</kbd> to navigate, <kbd>Enter</kbd> to expand</span>
        </div>
        <div class="footer-right">
            <button class="btn" id="btn-scroll" onclick="toggleAutoScroll()">auto-scroll: on</button>
            <button class="btn" onclick="expandAll()">expand all</button>
            <button class="btn" onclick="collapseAll()">collapse all</button>
        </div>
    </div>

    <div class="new-content" id="new-content" onclick="scrollToBottom(true)">↓ new output</div>

    <script>
        // When served behind a reverse-proxy path prefix (e.g. /api/dashboard/<id>/),
        // keep all requests relative to the current location.
        const basePath = window.location.pathname.replace(/\\/$/, '');
        let autoScroll = true;
        let data = null;
        let selectedStep = -1;
        let preservedState = { steps: new Set(), iterations: new Set(), details: new Set() };
        let seenState = { steps: new Set(), iterations: new Set(), details: new Set() };
        let hasRenderedOnce = false;
        let logsLoaded = false;
        let logRefreshTimer = null;
        let currentLogPath = '';
        let statePollTimer = null;
        let statePollInFlight = false;
        let lastStateSig = '';

        function stateUrl() {
            const base = `${basePath}/api/state`;
            if (!currentLogPath) return base;
            return `${base}?path=${encodeURIComponent(currentLogPath)}`;
        }

        function stateSignature(state) {
            const logPath = state && state.log_path ? state.log_path : '';
            const raw = state && typeof state.raw_line_count === 'number' ? state.raw_line_count : 0;
            const status = state && state.status ? state.status : '';
            const tokens = state && typeof state.total_tokens === 'number' ? state.total_tokens : 0;
            const steps = state && Array.isArray(state.steps) ? state.steps.length : 0;
            return `${logPath}|${raw}|${status}|${tokens}|${steps}`;
        }

        function isAtBottom() {
            // Consider "near bottom" as bottom to avoid jitter.
            const threshold = 80;
            const scrollPos = window.innerHeight + window.scrollY;
            const max = document.body.offsetHeight;
            return scrollPos >= max - threshold;
        }

        function collectScrollState() {
            const boxes = {};
            document.querySelectorAll('[data-scroll-key]').forEach((el) => {
                try {
                    const key = el.getAttribute('data-scroll-key');
                    if (!key) return;
                    // Only store if it's actually scrollable.
                    if (el.scrollHeight > el.clientHeight + 1) {
                        boxes[key] = el.scrollTop;
                    }
                } catch (e) {
                    // ignore
                }
            });
            return { boxes };
        }

        function restoreScrollState(state) {
            const boxes = (state && state.boxes) ? state.boxes : {};
            Object.keys(boxes).forEach((key) => {
                const el = document.querySelector(`[data-scroll-key="${cssEscape(key)}"]`);
                if (!el) return;
                try {
                    // Clamp to new bounds.
                    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
                    el.scrollTop = Math.min(Math.max(0, boxes[key] || 0), maxTop);
                } catch (e) {
                    // ignore
                }
            });
        }

        async function refreshState() {
            if (statePollInFlight) return;
            statePollInFlight = true;
            try {
                const wasAtBottom = isAtBottom();
                const preservedScroll = collectScrollState();
                const res = await fetch(stateUrl());
                if (!res.ok) return;
                const state = await res.json();
                if (!state) return;
                const sig = stateSignature(state);
                if (sig && sig === lastStateSig) {
                    return;
                }
                lastStateSig = sig;
                data = state;
                render(state);
                restoreScrollState(preservedScroll);
                // Auto-scroll is only controlled by the button
                if (autoScroll) {
                    scrollToBottom(true);
                } else {
                    document.getElementById('new-content').classList.add('visible');
                }
            } catch (err) {
                console.error('[dashboard] refreshState error:', err);
            } finally {
                statePollInFlight = false;
            }
        }

        document.getElementById('connection').textContent = 'polling';

        async function fetchLogs() {
            try {
                const res = await fetch(`${basePath}/api/logs`);
                if (!res.ok) return;
                const payload = await res.json();
                renderLogOptions(payload);
                logsLoaded = true;
                maybeStartLogRefresh(payload);
                if (!currentLogPath) {
                    const defaultPath = payload.default || (payload.logs && payload.logs[0] ? payload.logs[0].path : '');
                    if (defaultPath) {
                        currentLogPath = defaultPath;
                        updateSearchInputDisplay();
                    }
                }
            } catch (err) {
                console.warn('Failed to fetch logs', err);
            }
        }

        // Initial load.
        (async function bootstrap() {
            try {
                await fetchLogs();
                await refreshState();
                if (!statePollTimer) {
                    statePollTimer = setInterval(refreshState, 1000);
                }
            } catch (err) {
                // ignore
            }
        })();

        function renderLogOptions(payload) {
            const dropdown = document.getElementById('log-dropdown');
            const searchInput = document.getElementById('log-search');
            if (!dropdown || !searchInput) return;
            const logs = payload.logs || [];
            dropdown.innerHTML = '';
            if (!logs.length) {
                searchInput.placeholder = 'No logs found (auto-refreshing)';
                searchInput.disabled = true;
                return;
            }
            searchInput.disabled = false;
            searchInput.placeholder = 'Search logs...';
            const grouped = {};
            logs.forEach((entry) => {
                const group = entry.group || 'logs';
                if (!grouped[group]) grouped[group] = [];
                grouped[group].push(entry);
            });
            Object.keys(grouped).sort().forEach((group) => {
                const label = document.createElement('div');
                label.className = 'log-group-label';
                label.textContent = group;
                dropdown.appendChild(label);
                grouped[group].forEach((entry) => {
                    const opt = document.createElement('div');
                    opt.className = 'log-option';
                    opt.dataset.path = entry.path;
                    opt.dataset.label = entry.label;
                    opt.textContent = entry.label;
                    if (entry.path === currentLogPath) opt.classList.add('active');
                    dropdown.appendChild(opt);
                });
            });
            // Update input display value to current log label
            updateSearchInputDisplay();
        }

        function updateSearchInputDisplay() {
            const searchInput = document.getElementById('log-search');
            if (!searchInput || searchInput === document.activeElement) return;
            const active = document.querySelector('#log-dropdown .log-option.active');
            searchInput.value = active ? active.dataset.label : '';
        }

        async function switchLog(path) {
            if (!path) return;
            currentLogPath = path;
            await refreshState();
        }

        function maybeStartLogRefresh(payload) {
            const logs = payload.logs || [];
            if (logs.length) {
                if (logRefreshTimer) {
                    clearInterval(logRefreshTimer);
                    logRefreshTimer = null;
                }
                return;
            }
            if (!logRefreshTimer) {
                logRefreshTimer = setInterval(fetchLogs, 3000);
            }
        }

        // Searchable log dropdown logic
        (function() {
            const searchInput = document.getElementById('log-search');
            const dropdown = document.getElementById('log-dropdown');

            searchInput.addEventListener('focus', () => {
                searchInput.select();
                dropdown.classList.add('open');
                filterDropdown(searchInput.value);
            });

            searchInput.addEventListener('input', () => {
                dropdown.classList.add('open');
                filterDropdown(searchInput.value);
            });

            function fuzzyMatch(query, text) {
                let qi = 0;
                for (let ti = 0; ti < text.length && qi < query.length; ti++) {
                    if (text[ti] === query[qi]) qi++;
                }
                return qi === query.length;
            }

            function filterDropdown(query) {
                const q = query.toLowerCase();
                dropdown.querySelectorAll('.log-option').forEach(opt => {
                    opt.style.display = fuzzyMatch(q, opt.dataset.label.toLowerCase()) ? '' : 'none';
                });
                dropdown.querySelectorAll('.log-group-label').forEach(label => {
                    let next = label.nextElementSibling;
                    let anyVisible = false;
                    while (next && !next.classList.contains('log-group-label')) {
                        if (next.style.display !== 'none') anyVisible = true;
                        next = next.nextElementSibling;
                    }
                    label.style.display = anyVisible ? '' : 'none';
                });
            }

            dropdown.addEventListener('click', (e) => {
                const opt = e.target.closest('.log-option');
                if (!opt) return;
                dropdown.querySelectorAll('.log-option.active').forEach(el => el.classList.remove('active'));
                opt.classList.add('active');
                searchInput.value = opt.dataset.label;
                dropdown.classList.remove('open');
                switchLog(opt.dataset.path);
            });

            document.addEventListener('click', (e) => {
                if (!e.target.closest('.log-search-wrap')) {
                    dropdown.classList.remove('open');
                    updateSearchInputDisplay();
                }
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && dropdown.classList.contains('open')) {
                    dropdown.classList.remove('open');
                    searchInput.blur();
                    updateSearchInputDisplay();
                }
            });
        })();

        document.getElementById('btn-refresh-logs').addEventListener('click', async (e) => {
            e.preventDefault();
            const btn = e.currentTarget;
            if (btn.classList.contains('spinning')) return;
            btn.classList.add('spinning');
            const minDelay = new Promise(r => setTimeout(r, 600));
            try {
                await Promise.all([fetchLogs(), minDelay]);
            } finally {
                btn.classList.remove('spinning');
            }
        });

        function render(state) {
            preservedState = collectOpenState();
            const shouldAutoExpand = !hasRenderedOnce;
            // Header
            document.getElementById('task-name').textContent = state.task_name || '-';
            document.getElementById('status-dot').className = 'status-dot ' + state.status;
            document.getElementById('status-text').textContent = state.status;

            // Stats
            const totalIterations = state.steps.reduce((s, step) => s + step.iterations.length, 0);
            const totalTools = state.steps.reduce((s, step) =>
                s + step.iterations.reduce((i, iter) => i + (iter.timeline || []).length, 0), 0);

            document.getElementById('stat-steps').textContent = state.steps.length;
            document.getElementById('stat-iterations').textContent = totalIterations;
            document.getElementById('stat-tools').textContent = totalTools;
            document.getElementById('stat-tokens').textContent = state.total_tokens.toLocaleString();
            document.getElementById('stat-prompt').textContent = (state.prompt_tokens || 0).toLocaleString();
            document.getElementById('stat-completion').textContent = (state.completion_tokens || 0).toLocaleString();
            document.getElementById('stat-reasoning').textContent = (state.reasoning_tokens || 0).toLocaleString();
            const cost = state.cost || 0;
            document.getElementById('stat-cost').textContent = cost > 0 ? '$' + cost.toFixed(4) : '$0.00';

            // Minimap
            renderMinimap(state);

            // Main content
            const main = document.getElementById('main');
            if (state.steps.length === 0) {
                main.innerHTML = '<div class="empty">Waiting for agent output...</div>';
                return;
            }

            const indexed = indexSteps(state.steps || []);
            main.innerHTML = indexed.roots.map((step, i) =>
                renderStep(step, indexed, {
                    root: true,
                    autoExpand: shouldAutoExpand,
                    forceExpanded: shouldAutoExpand && (step.status === 'running' || i === indexed.roots.length - 1),
                })
            ).join('');
            restoreOpenState(preservedState);
            autoOpenNewElements(preservedState);
            hasRenderedOnce = true;
        }

        function renderMinimap(state) {
            const minimap = document.getElementById('minimap');
            const bar = document.getElementById('minimap-bar');
            const title = document.getElementById('minimap-title');
            if (!state.steps || !state.steps.length) {
                minimap.classList.remove('visible');
                return;
            }

            // Collect messages from the last iteration of each step (most complete view)
            const segments = [];
            let totalMsgs = 0;
            state.steps.forEach((step) => {
                if (!step.iterations || !step.iterations.length) return;
                const lastIter = step.iterations[step.iterations.length - 1];
                if (!lastIter.messages || !lastIter.messages.length) return;
                const stepKey = step.step_id || step.number;
                const iterNum = lastIter.number;
                lastIter.messages.forEach((msg, msgIdx) => {
                    const role = (msg.role || 'unknown').toLowerCase();
                    segments.push({ role, stepKey, iterNum, msgIdx });
                    totalMsgs++;
                });
                // Add separator between steps
                segments.push({ sep: true });
            });
            // Remove trailing separator
            if (segments.length && segments[segments.length - 1].sep) {
                segments.pop();
            }

            if (totalMsgs === 0) {
                minimap.classList.remove('visible');
                return;
            }

            title.textContent = `Minimap (${totalMsgs} messages)`;
            bar.innerHTML = segments.map((seg, i) => {
                if (seg.sep) {
                    return '<div class="minimap-step-sep"></div>';
                }
                return `<div class="minimap-seg" data-role="${seg.role}" data-step-key="${esc(String(seg.stepKey))}" data-iter-num="${seg.iterNum}" data-msg-idx="${seg.msgIdx}" title="${seg.role}"></div>`;
            }).join('');

            minimap.classList.add('visible');
        }

        // Minimap click handler — open step/iteration/messages and scroll to the exact message
        document.getElementById('minimap-bar').addEventListener('click', (e) => {
            const seg = e.target.closest('.minimap-seg');
            if (!seg) return;
            const stepKey = seg.dataset.stepKey;
            const iterNum = seg.dataset.iterNum;
            const msgIdx = seg.dataset.msgIdx;
            if (!stepKey) return;

            // 1. Expand the step
            const stepEl = document.querySelector(`.step[data-step-key="${CSS.escape(stepKey)}"]`);
            if (!stepEl) return;
            if (!stepEl.classList.contains('expanded')) {
                setStepExpanded(stepEl, true);
            }

            // 2. Open the iteration
            const iterKey = `${stepKey}:${iterNum}`;
            const iterEl = document.querySelector(`details.iteration[data-iter-key="${CSS.escape(iterKey)}"]`);
            if (iterEl && !iterEl.open) {
                iterEl.open = true;
                const toggle = iterEl.querySelector(':scope > summary > .iteration-toggle');
                if (toggle) toggle.textContent = '▼';
            }

            // 3. Open the messages group
            const msgGroupKey = `msg-group:${stepKey}:${iterNum}`;
            const msgGroup = document.querySelector(`details[data-detail-key="${CSS.escape(msgGroupKey)}"]`);
            if (msgGroup && !msgGroup.open) {
                msgGroup.open = true;
            }

            // 4. If the message is inside a collapsed prefix, open it
            const prefixKey = `msg-prefix:${stepKey}:${iterNum}`;
            const prefixEl = document.querySelector(`details[data-detail-key="${CSS.escape(prefixKey)}"]`);
            if (prefixEl) {
                // Check if the target message is inside the prefix
                const targetDetailKey = `msg:${stepKey}:${iterNum}:${msgIdx}`;
                const msgInPrefix = prefixEl.querySelector(`details[data-detail-key="${CSS.escape(targetDetailKey)}"]`);
                if (msgInPrefix && !prefixEl.open) {
                    prefixEl.open = true;
                }
            }

            // 5. Scroll to the specific message, offset by sticky header + minimap height
            requestAnimationFrame(() => {
                const targetDetailKey = `msg:${stepKey}:${iterNum}:${msgIdx}`;
                const msgEl = document.querySelector(`details[data-detail-key="${CSS.escape(targetDetailKey)}"]`);
                const el = msgEl || stepEl;
                const minimapEl = document.getElementById('minimap');
                const headerEl = document.querySelector('.header');
                const offset = (headerEl ? headerEl.offsetHeight : 0) + (minimapEl ? minimapEl.offsetHeight : 0);
                const top = el.getBoundingClientRect().top + window.scrollY - offset - 4;
                window.scrollTo({ top, behavior: 'smooth' });
            });
        });

        function indexSteps(steps) {
            const byId = new Map();
            const roots = [];
            steps.forEach((step) => {
                if (!step) return;
                const key = step.step_id || step.number;
                if (!key) return;
                step.children = [];
                byId.set(key, step);
            });
            steps.forEach((step) => {
                if (!step) return;
                const key = step.step_id || step.number;
                if (!key) return;
                let parentId = step.parent_step_id;
                if (!parentId) {
                    // Try to infer a reasonable parent from the dotted step id,
                    // walking up the hierarchy until we find an existing ancestor.
                    let candidate = inferParentStepId(key);
                    while (candidate && !byId.has(candidate)) {
                        const next = inferParentStepId(candidate);
                        if (!next || next === candidate) {
                            candidate = null;
                            break;
                        }
                        candidate = next;
                    }
                    parentId = candidate;
                }
                if (parentId && byId.has(parentId)) {
                    const parent = byId.get(parentId);
                    if (step.parent_iteration == null && parent.iterations && parent.iterations.length) {
                        step.parent_iteration = parent.iterations[parent.iterations.length - 1].number;
                    }
                    parent.children.push(step);
                } else {
                    roots.push(step);
                }
            });
            return { byId, roots };
        }

        function inferParentStepId(stepId) {
            if (!stepId) return null;
            const parts = stepId.toString().split('.');
            if (parts.length <= 1) return null;
            const compressed = [];
            for (let i = 0; i < parts.length; i++) {
                if (parts[i] === 'tool' && i + 1 < parts.length) {
                    compressed.push(`tool.${parts[i + 1]}`);
                    i += 1;
                } else {
                    compressed.push(parts[i]);
                }
            }
            if (compressed.length <= 1) return null;
            return compressed.slice(0, -1).join('.');
        }

        const _varRawValues = new Map();
        let _varIdx = 0;

        function renderVarsBtn(step) {
            const vars = step.variables || {};
            const keys = Object.keys(vars);
            if (keys.length === 0) return '';
            const rows = keys.map(k => {
                const v = vars[k];
                if (v === null || v === undefined || v === '') {
                    return `<div class="vars-row"><span class="vars-key">${esc(k)}</span><span class="vars-val"><span class="vars-empty">None</span></span></div>`;
                }
                const escaped = esc(v);
                const idx = _varIdx++;
                _varRawValues.set(idx, { key: k, val: v });
                return `<div class="vars-row"><span class="vars-key">${esc(k)}</span><span class="vars-val clickable" data-var-idx="${idx}">${escaped}</span></div>`;
            }).join('');
            return `
                <div style="position:relative; display:inline-flex; align-items:center;">
                    <button class="vars-btn" onclick="event.stopPropagation(); this.nextElementSibling.classList.toggle('show')">vars (${keys.length})</button>
                    <div class="vars-popup">${rows}</div>
                </div>
            `;
        }

        function renderStep(step, indexed, opts = {}) {
            const expanded = step.status === 'running' || opts.forceExpanded;
            const depth = Math.max(0, Number.isFinite(step.depth) ? step.depth : (step.number || '').toString().split('.').length - 1);
            const indent = depth * 16;
            const stepKey = step.step_id || step.number || '';
            const childSteps = Array.isArray(step.children) ? step.children : [];
            const inlineChildren = childSteps.filter(c => c.parent_iteration == null);

            return `
                <div class="step ${expanded ? 'expanded' : ''}" data-step-key="${esc(stepKey)}" style="margin-left:${indent}px">
                    <div class="step-header">
                        <span class="step-toggle">${expanded ? '▼' : '▶'}</span>
                        <span class="step-icon">●</span>
                        <div class="step-info">
                            <div class="step-title">
                                <span class="step-name">${esc(step.name)}</span>
                                <span class="step-type">${step.type}</span>
                            </div>
                            <div class="step-meta">
                                #${step.number}${step.name ? ' ' + esc(step.name) : ''}${step.type ? ' (' + esc(step.type) + ')' : ''} · ${step.iterations.length} iteration${step.iterations.length !== 1 ? 's' : ''} ·
                                ${step.tokens.toLocaleString()} tokens
                            </div>
                        </div>
                        ${renderVarsBtn(step)}
                        <div class="step-status ${step.status}">
                            ${step.status === 'running' ? '● running' : step.status === 'completed' ? '✓ done' : step.status}
                        </div>
                    </div>
                    <div class="step-content">
                        ${step.instruction ? `<div class="instruction payload-box" data-scroll-key="instr:${esc(stepKey)}">${esc(step.instruction)}</div>` : ''}
                        ${renderStepEvents(step)}
                        ${step.iterations.map((iter, i) => renderIteration(iter, i, step.iterations.length, stepKey, step, indexed, opts.autoExpand)).join('')}
                        ${inlineChildren.map(child => renderStep(child, indexed, { root: false, forceExpanded: false, autoExpand: opts.autoExpand })).join('')}
                    </div>
                </div>
            `;
        }

        function renderIteration(iter, idx, total, stepKey, step, indexed, autoExpand) {
            const isLast = idx === total - 1;
            const utilization = iter.utilization || 0;
            const ctxClass = utilization < 50 ? 'low' : utilization < 80 ? 'medium' : 'high';
            const toolCount = countTools(iter);
            const iterKey = `${stepKey}:${iter.number}`;
            const childSteps = Array.isArray(step.children)
                ? step.children.filter(c => Number(c.parent_iteration) === Number(iter.number))
                : [];
            const messagesKey = `msg-group:${stepKey}:${iter.number}`;
            const expanded = autoExpand && isLast;

            return `
                <details class="iteration" data-iter-key="${esc(iterKey)}" data-detail-key="iter:${esc(iterKey)}" ${expanded ? 'open' : ''}>
                    <summary class="iteration-header">
                        <span class="iteration-toggle">${expanded ? '▼' : '▶'}</span>
                        <span class="iteration-label">iteration ${iter.number}</span>
                        <span style="color: var(--text-dimmer)">${toolCount} tool${toolCount !== 1 ? 's' : ''}</span>
                        <span class="iteration-meta">
                            <span class="context-bar">
                                <span class="context-track">
                                    <span class="context-fill ${ctxClass}" style="width: ${Math.min(utilization, 100)}%"></span>
                                </span>
                                ${utilization.toFixed(0)}%
                            </span>
                        </span>
                    </summary>
                    <div class="iteration-content">
                        <details class="tool message-group" data-detail-key="${esc(messagesKey)}">
                            <summary class="tool-header" style="cursor:pointer; list-style:none;">
                                <span class="tool-name">messages</span>
                                <span style="color: var(--text-dimmer); margin-left:auto;">expand</span>
                            </summary>
                            ${renderMessages(iter, stepKey, idx > 0 ? step.iterations[idx - 1] : null)}
                        </details>
                        ${renderUsage(iter)}
                        ${renderContent(iter, stepKey)}
                        ${renderTimeline(iter, stepKey)}
                        ${childSteps.map(child => renderStep(child, indexed, { root: false, forceExpanded: true, autoExpand })).join('')}
                    </div>
                </details>
            `;
        }

        function countTools(iter) {
            if (iter.timeline && iter.timeline.length) {
                return iter.timeline.length;
            }
            const ids = new Set();
            if (iter.messages && iter.messages.length) {
                iter.messages.forEach(msg => {
                    if (Array.isArray(msg.tool_calls)) {
                        msg.tool_calls.forEach(tc => {
                            if (tc && tc.id) ids.add(tc.id);
                        });
                    }
                    if ((msg.role || '').toLowerCase() === 'tool' && msg.tool_call_id) {
                        ids.add(msg.tool_call_id);
                    }
                });
            }
            if (iter.tool_calls && iter.tool_calls.length) {
                iter.tool_calls.forEach(tc => {
                    if (tc && tc.id) ids.add(tc.id);
                });
            }
            return ids.size;
        }

        function extractScreenshotVpath(resultStr) {
            // Try to parse tool result JSON and return the best screenshot vpath.
            // Prefers som_filename (annotated) over screenshot_filename (raw).
            if (!resultStr) return null;
            try {
                const r = JSON.parse(resultStr);
                return r.som_filename || r.screenshot_filename || null;
            } catch (e) {
                return null;
            }
        }

        function renderScreenshotSection(vpath) {
            if (!vpath) return '';
            const url = '/screenshot?vpath=' + encodeURIComponent(vpath);
            const filename = vpath.split('/').pop();
            const isSom = vpath.includes('-som.');
            const label = isSom ? 'SoM screenshot' : 'Screenshot';
            return `
                <details class="tool-screenshot">
                    <summary class="tool-label" style="cursor:pointer;">${label}</summary>
                    <div class="screenshot-thumb-wrap">
                        <img class="screenshot-thumb" src="${url}" alt="${esc(filename)}"
                             onclick="openLightbox('${url}')"
                             onerror="this.parentElement.style.display='none'">
                        <span class="screenshot-zoom-hint">click to expand</span>
                    </div>
                </details>
            `;
        }

        function renderTimeline(iter, stepKey) {
            if (iter.timeline && iter.timeline.length) {
                return iter.timeline
                    .sort((a, b) => (a.call || 0) - (b.call || 0))
                    .map(entry => {
                        const title = entry.call ? `call ${entry.call}` : '';
                        const nameClass = entry.kind && entry.kind.includes('module') ? 'module' : (entry.kind && entry.kind.includes('parallel') ? 'parallel' : '');
                        const detailKey = `tool:${stepKey}:${iter.number}:${entry.call || 0}:${entry.name || ''}`;
                        const screenshotVpath = extractScreenshotVpath(entry.result);
                        return `
                            <details class="tool" data-detail-key="${esc(detailKey)}">
                                <summary class="tool-header" style="cursor:pointer; list-style:none;">
                                    <span class="tool-name ${nameClass}">${esc(entry.name || '')}</span>
                                    ${title ? `<span style="color: var(--text-dimmer); margin-left:6px">${title}</span>` : ''}
                                    ${screenshotVpath ? `<span style="color: var(--cyan); margin-left:6px; font-size:11px;">[img]</span>` : ''}
                                    <span style="color: var(--text-dimmer); margin-left:auto;">expand</span>
                                </summary>
                                <div class="tool-box payload-box" data-scroll-key="${esc(detailKey)}:output:box" style="${entry.result ? '' : 'color: var(--text-dimmer);'}">${entry.result ? esc(entry.result) : 'No result yet'}</div>
                                ${renderScreenshotSection(screenshotVpath)}
                            </details>
                        `;
                    }).join('');
            }
            return (iter.tool_calls || []).map(tc => renderTool(tc)).join('');
        }

        function messagesEqual(a, b) {
            if (!a || !b) return false;
            if ((a.role || '') !== (b.role || '')) return false;
            if ((a.content || '') !== (b.content || '')) return false;
            const aTC = a.tool_calls ? JSON.stringify(a.tool_calls) : '';
            const bTC = b.tool_calls ? JSON.stringify(b.tool_calls) : '';
            if (aTC !== bTC) return false;
            if ((a.tool_call_id || '') !== (b.tool_call_id || '')) return false;
            return true;
        }

        function newMessageCount(prevMsgs, curMsgs) {
            // Find how many messages at the end of curMsgs are new (not in prevMsgs).
            // First try exact prefix match — if it covers all of prevMsgs, the rest are new.
            // If prefix breaks (due to truncation/editing), fall back to matching from the
            // end of prevMsgs backwards: count how many trailing curMsgs don't appear in prev.
            if (!prevMsgs || !prevMsgs.length) return curMsgs ? curMsgs.length : 0;
            if (!curMsgs || !curMsgs.length) return 0;

            // Exact prefix match
            let prefixLen = 0;
            const minLen = Math.min(prevMsgs.length, curMsgs.length);
            for (let i = 0; i < minLen; i++) {
                if (!messagesEqual(prevMsgs[i], curMsgs[i])) break;
                prefixLen++;
            }
            if (prefixLen >= prevMsgs.length) {
                // All prev messages matched as a prefix — new messages are the tail
                return curMsgs.length - prefixLen;
            }

            // Prefix broke (messages were edited/truncated mid-conversation).
            // Match backwards from the end of prevMsgs to find how many trailing
            // messages in curMsgs are truly new (not present at the end of prev).
            let suffixMatch = 0;
            const pLen = prevMsgs.length;
            const cLen = curMsgs.length;
            while (suffixMatch < pLen && suffixMatch < cLen) {
                if (!messagesEqual(prevMsgs[pLen - 1 - suffixMatch], curMsgs[cLen - 1 - suffixMatch])) break;
                suffixMatch++;
            }
            // The suffix that matches prev's tail is old context; everything else beyond prev is new.
            // new count = total cur messages - (prev messages count), but at least the unmatched tail.
            const newCount = cLen - pLen;
            return Math.max(newCount, 0);
        }

        function renderMessages(iter, stepKey, prevIter) {
            if (!iter.messages || !iter.messages.length) return '';
            const prevMsgs = prevIter && prevIter.messages ? prevIter.messages : null;
            const newCount = newMessageCount(prevMsgs, iter.messages);
            const prefixLen = iter.messages.length - newCount;
            const newMessages = iter.messages.slice(prefixLen);

            let prefixHtml = '';
            if (prefixLen > 0) {
                const prefixKey = `msg-prefix:${stepKey}:${iter.number}`;
                prefixHtml = `
                    <details class="tool message msg-prefix-collapse" data-detail-key="${esc(prefixKey)}">
                        <summary class="tool-header msg-prefix-summary" style="cursor:pointer; list-style:none;">
                            <span class="msg-prefix-label">${prefixLen} message${prefixLen !== 1 ? 's' : ''} from previous iteration</span>
                            <span class="msg-prefix-hint-expand">· click to expand</span>
                            <span class="msg-prefix-hint-collapse">· click to collapse</span>
                        </summary>
                        ${iter.messages.slice(0, prefixLen).map((msg, i) => {
                            const role = (msg.role || 'unknown').toLowerCase();
                            const roleClass = 'role-' + role;
                            const contentText = msg.content || '';
                            const toolCallsText = msg.tool_calls ? JSON.stringify(msg.tool_calls, null, 2) : '';
                            const content = esc(contentText || toolCallsText || '');
                            const toolCalls = contentText && toolCallsText
                                ? '<div class="tool-box payload-box">' + esc(toolCallsText) + '</div>'
                                : '';
                            const detailKey = 'msg:' + stepKey + ':' + iter.number + ':' + i;
                            return '<details class="tool message" data-detail-key="' + esc(detailKey) + '">' +
                                '<summary class="tool-header" style="cursor:pointer; list-style:none;">' +
                                    '<span class="role-label ' + roleClass + '">Role: ' + esc(role) + '</span>' +
                                    '<span style="color: var(--text-dimmer); margin-left:6px">message ' + (i + 1) + '</span>' +
                                    '<span style="color: var(--text-dimmer); margin-left:auto;">expand</span>' +
                                '</summary>' +
                                '<div class="tool-box payload-box" data-scroll-key="' + esc(detailKey) + ':box">' + content + '</div>' +
                                toolCalls +
                            '</details>';
                        }).join('')}
                    </details>
                `;
            }

            const newHtml = newMessages.map((msg, j) => {
                const i = prefixLen + j;
                const role = (msg.role || 'unknown').toLowerCase();
                const roleClass = `role-${role}`;
                const contentText = msg.content || '';
                const toolCallsText = msg.tool_calls ? JSON.stringify(msg.tool_calls, null, 2) : '';
                const content = esc(
                    contentText || toolCallsText || ''
                );
                const toolCalls = contentText && toolCallsText
                    ? `<div class="tool-box payload-box">${esc(toolCallsText)}</div>`
                    : '';
                const detailKey = `msg:${stepKey}:${iter.number}:${i}`;
                return `
                    <details class="tool message" data-detail-key="${esc(detailKey)}">
                        <summary class="tool-header" style="cursor:pointer; list-style:none;">
                            <span class="role-label ${roleClass}">Role: ${esc(role)}</span>
                            <span style="color: var(--text-dimmer); margin-left:6px">message ${i + 1}</span>
                            <span style="color: var(--text-dimmer); margin-left:auto;">expand</span>
                        </summary>
                        <div class="tool-box payload-box" data-scroll-key="${esc(detailKey)}:box">${content}</div>
                        ${toolCalls}
                    </details>
                `;
            }).join('');

            return prefixHtml + newHtml;
        }

        function renderUsage(iter) {
            if (!iter.usage || !iter.usage.total_tokens) return '';
            const prompt = iter.usage.prompt_tokens || 0;
            const completion = iter.usage.completion_tokens || 0;
            const total = iter.usage.total_tokens || 0;
            const reasoning = iter.usage.reasoning_tokens || 0;
            return `
                <div class="tool">
                    <div class="tool-header">
                        <span class="tool-name">usage</span>
                        <span style="color: var(--text-dimmer); margin-left:6px">${prompt} prompt / ${completion} completion · ${reasoning} reasoning · ${total} total</span>
                    </div>
                </div>
            `;
        }

        function renderStepEvents(step) {
            if (!step.events || !step.events.length) return '';
            return step.events.map((ev, i) => {
                const detailKey = `step:${step.step_id || step.number}:event:${i}`;
                return `
                    <details class="tool message" data-detail-key="${esc(detailKey)}">
                        <summary class="tool-header" style="cursor:pointer; list-style:none;">
                            <span class="tool-name">${esc(ev.type || 'event')}</span>
                            <span style="color: var(--text-dimmer); margin-left:6px">step event ${i + 1}</span>
                            <span style="color: var(--text-dimmer); margin-left:auto;">expand</span>
                        </summary>
                        <div class="tool-box payload-box">${esc(ev.message || '')}</div>
                    </details>
                `;
            }).join('');
        }

        function renderContent(iter, stepKey) {
            if (!iter.content || !iter.content.length) return '';
            const timeline = (iter.timeline || []).slice().sort((a, b) => (a.call || 0) - (b.call || 0));
            return iter.content.map((entry, i) => {
                const detailKey = `content:${stepKey}:${iter.number}:${i}`;
                // Distribute timeline args: content[i] gets timeline entries whose index >= i*stride
                // Simple approach: last content entry gets all remaining tool inputs
                const isLast = i === iter.content.length - 1;
                const start = i;
                const end = isLast ? timeline.length : i + 1;
                const toolInputText = timeline.slice(start, end).filter(e => e.args).map(e =>
                    `[${e.name || 'tool'} input]\\n${e.args}`
                ).join('\\n');
                return `
                    <details class="tool message" data-detail-key="${esc(detailKey)}">
                        <summary class="tool-header" style="cursor:pointer; list-style:none;">
                            <span class="tool-name">response</span>
                            <span style="color: var(--text-dimmer); margin-left:6px">entry ${i + 1}</span>
                            <span style="color: var(--text-dimmer); margin-left:auto;">expand</span>
                        </summary>
                        <div class="tool-box payload-box">${esc(entry && toolInputText ? entry + '\\n' + toolInputText : entry || toolInputText)}</div>
                    </details>
                `;
            }).join('');
        }

        function renderTool(tc) {
            const isModule = tc.name.startsWith('MODULE:');
            return `
                <div class="tool">
                    <div class="tool-header">
                        <span class="tool-name ${isModule ? 'module' : ''}">${esc(tc.name)}</span>
                    </div>
                    ${tc.args ? `<div class="tool-box payload-box">${esc(tc.args)}</div>` : ''}
                    ${tc.result ? `<div class="tool-box payload-box">${esc(tc.result)}</div>` : ''}
                </div>
            `;
        }

        function setStepExpanded(stepEl, expanded) {
            if (!stepEl) return;
            stepEl.classList.toggle('expanded', expanded);
            const toggle = stepEl.querySelector(':scope > .step-header > .step-toggle');
            if (toggle) toggle.textContent = expanded ? '▼' : '▶';
            const content = stepEl.querySelector(':scope > .step-content');
            if (content) {
                // Inline style to guarantee visibility respects the expanded state,
                // even for deeply nested steps.
                content.style.display = expanded ? 'block' : 'none';
            }
        }

        function toggleStep(stepKey) {
            const el = document.querySelector(`.step[data-step-key="${cssEscape(stepKey)}"]`);
            if (!el) return;
            const expanded = !el.classList.contains('expanded');
            setStepExpanded(el, expanded);
        }

        function toggleAutoScroll() {
            autoScroll = !autoScroll;
            document.getElementById('btn-scroll').textContent = 'auto-scroll: ' + (autoScroll ? 'on' : 'off');
            if (autoScroll) scrollToBottom(true);
        }

        function expandAll() {
            document.querySelectorAll('.step').forEach(el => {
                el.classList.add('expanded');
                const toggle = el.querySelector(':scope > .step-header > .step-toggle');
                if (toggle) toggle.textContent = '▼';
            });
            document.querySelectorAll('details.iteration').forEach(el => {
                el.open = true;
                const toggle = el.querySelector(':scope > summary > .iteration-toggle');
                if (toggle) toggle.textContent = '▼';
            });
            document.querySelectorAll('details.tool').forEach(el => {
                el.open = true;
            });
        }

        function collapseAll() {
            document.querySelectorAll('.step').forEach(el => {
                el.classList.remove('expanded');
                const toggle = el.querySelector(':scope > .step-header > .step-toggle');
                if (toggle) toggle.textContent = '▶';
            });
            document.querySelectorAll('details.iteration').forEach(el => {
                el.open = false;
                const toggle = el.querySelector(':scope > summary > .iteration-toggle');
                if (toggle) toggle.textContent = '▶';
            });
            document.querySelectorAll('details.tool').forEach(el => {
                el.open = false;
            });
        }

        function scrollToBottom(force = false) {
            if (!force && !autoScroll) return;
            window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            document.getElementById('new-content').classList.remove('visible');
        }

        function esc(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function cssEscape(value) {
            return CSS.escape(value || '');
        }

        function collectOpenState() {
            const steps = new Set();
            const iterations = new Set();
            const details = new Set();
            document.querySelectorAll('.step.expanded').forEach(el => {
                const key = el.getAttribute('data-step-key');
                if (key) steps.add(key);
            });
            document.querySelectorAll('details.iteration[open]').forEach(el => {
                const key = el.getAttribute('data-iter-key');
                if (key) iterations.add(key);
            });
            document.querySelectorAll('details[data-detail-key]').forEach(el => {
                const key = el.getAttribute('data-detail-key');
                if (key && el.open) details.add(key);
            });
            return { steps, iterations, details };
        }

        function restoreOpenState(state) {
            document.querySelectorAll('.step').forEach(el => {
                const key = el.getAttribute('data-step-key');
                if (!key) return;
                if (state.steps.has(key)) {
                    el.classList.add('expanded');
                    const toggle = el.querySelector(':scope > .step-header > .step-toggle');
                    if (toggle) toggle.textContent = '▼';
                } else {
                    // User had this step collapsed — override any expanded
                    // state baked in by renderStep (e.g. running steps).
                    el.classList.remove('expanded');
                    const toggle = el.querySelector(':scope > .step-header > .step-toggle');
                    if (toggle) toggle.textContent = '▶';
                }
            });
            document.querySelectorAll('details.iteration').forEach(el => {
                const key = el.getAttribute('data-iter-key');
                if (!key) return;
                if (state.iterations.has(key)) {
                    el.open = true;
                    const toggle = el.querySelector(':scope > summary > .iteration-toggle');
                    if (toggle) toggle.textContent = '▼';
                } else {
                    el.open = false;
                    const toggle = el.querySelector(':scope > summary > .iteration-toggle');
                    if (toggle) toggle.textContent = '▶';
                }
            });
            document.querySelectorAll('details[data-detail-key]').forEach(el => {
                const key = el.getAttribute('data-detail-key');
                if (!key) return;
                if (state.details.has(key)) {
                    el.open = true;
                } else {
                    el.open = false;
                }
            });
        }

        function autoOpenNewElements(state) {
            document.querySelectorAll('.step').forEach(el => {
                const key = el.getAttribute('data-step-key');
                if (!key) return;
                const seen = seenState.steps.has(key);
                if (!seen && !state.steps.has(key)) {
                    el.classList.add('expanded');
                    const toggle = el.querySelector(':scope > .step-header > .step-toggle');
                    if (toggle) toggle.textContent = '▼';
                }
                seenState.steps.add(key);
            });

            document.querySelectorAll('details.iteration').forEach(el => {
                const key = el.getAttribute('data-iter-key');
                if (!key) return;
                const seen = seenState.iterations.has(key);
                if (!seen && !state.iterations.has(key)) {
                    el.open = true;
                    const toggle = el.querySelector(':scope > summary > .iteration-toggle');
                    if (toggle) toggle.textContent = '▼';
                }
                seenState.iterations.add(key);
            });

            document.querySelectorAll('details[data-detail-key]').forEach(el => {
                const key = el.getAttribute('data-detail-key');
                if (!key) return;
                const seen = seenState.details.has(key);
                if (!seen && !state.details.has(key)) {
                    const isPayload = el.classList.contains('tool-args') || el.classList.contains('tool-result');
                    const isPrefix = el.classList.contains('msg-prefix-collapse');
                    if (!isPayload && !isPrefix) {
                        el.open = true;
                    }
                }
                seenState.details.add(key);
            });
        }

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            const tag = (e.target.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.isContentEditable) return;
            const steps = document.querySelectorAll('.step');
            function highlightSelectedStep(steps) {
                steps.forEach(s => s.classList.remove('step-selected'));
                if (selectedStep >= 0 && selectedStep < steps.length) {
                    steps[selectedStep].classList.add('step-selected');
                }
            }
            if (e.key === 'j') {
                selectedStep = Math.min(selectedStep + 1, steps.length - 1);
                highlightSelectedStep(steps);
                steps[selectedStep]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } else if (e.key === 'k') {
                selectedStep = Math.max(selectedStep - 1, 0);
                highlightSelectedStep(steps);
                steps[selectedStep]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } else if (e.key === 'Enter' && selectedStep >= 0) {
                const key = steps[selectedStep]?.getAttribute('data-step-key');
                if (key) toggleStep(key);
            } else if (e.key === 'g' && e.shiftKey) {
                window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
            } else if (e.key === 'g') {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });

        document.addEventListener('click', (e) => {
            // Close any open vars popups when clicking outside
            if (!e.target.closest('.vars-btn') && !e.target.closest('.vars-popup')) {
                document.querySelectorAll('.vars-popup.show').forEach(p => p.classList.remove('show'));
            }
            const stepHeader = e.target.closest('.step-header');
            if (!stepHeader) return;
            // Don't toggle step when clicking vars button
            if (e.target.closest('.vars-btn') || e.target.closest('.vars-popup')) return;
            const step = stepHeader.parentElement;
            if (!step || !step.classList.contains('step')) return;
            const expanded = !step.classList.contains('expanded');
            setStepExpanded(step, expanded);
        });

        // Click on a variable value to open full view modal
        document.addEventListener('click', (e) => {
            const val = e.target.closest('.vars-val.clickable');
            if (!val) return;
            e.stopPropagation();
            const idx = Number(val.dataset.varIdx);
            const entry = _varRawValues.get(idx) || {};
            document.getElementById('vars-modal-title').textContent = entry.key || '';
            document.getElementById('vars-modal-body').textContent = entry.val || '';
            document.getElementById('vars-modal').classList.add('show');
        });

        // Close modal on overlay click or Escape
        document.getElementById('vars-modal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) e.currentTarget.classList.remove('show');
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') document.getElementById('vars-modal').classList.remove('show');
        });

        document.addEventListener('toggle', (e) => {
            const details = e.target;
            if (!(details instanceof HTMLDetailsElement)) return;
            if (details.classList.contains('iteration')) {
                const toggle = details.querySelector('.iteration-toggle');
                if (toggle) toggle.textContent = details.open ? '▼' : '▶';
            }
        }, true);

        // Scroll detection - only hide new-content indicator when at bottom
        window.addEventListener('scroll', () => {
            const atBottom = isAtBottom();
            if (atBottom) {
                document.getElementById('new-content').classList.remove('visible');
            }
        });
    </script>
    <div class="vars-modal-overlay" id="vars-modal">
        <div class="vars-modal">
            <div class="vars-modal-header">
                <span class="vars-modal-title" id="vars-modal-title"></span>
                <button class="vars-modal-close" onclick="document.getElementById('vars-modal').classList.remove('show')">&times;</button>
            </div>
            <div class="vars-modal-body" id="vars-modal-body"></div>
        </div>
    </div>

    <!-- Screenshot lightbox -->
    <div class="lightbox-overlay" id="lightbox" onclick="closeLightbox()">
        <div class="lightbox-inner" onclick="event.stopPropagation()">
            <span class="lightbox-close" onclick="closeLightbox()">&times;</span>
            <img class="lightbox-img" id="lightbox-img" src="" alt="Screenshot">
        </div>
    </div>
    <script>
        function openLightbox(url) {
            document.getElementById('lightbox-img').src = url;
            document.getElementById('lightbox').classList.add('show');
        }
        function closeLightbox() {
            document.getElementById('lightbox').classList.remove('show');
            document.getElementById('lightbox-img').src = '';
        }
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') closeLightbox();
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/screenshot")
def serve_screenshot():
    """Serve a screenshot from the sandbox workspace by vpath.

    Accepts a session-relative vpath like /shots/shot-X-som.png and resolves
    it by globbing across all sessions in HOST_WORKSPACE.
    """
    import re

    vpath = request.args.get("vpath", "")
    filename = os.path.basename(vpath)
    # Only allow safe filenames (no path traversal)
    if not filename or not re.match(r"^[\w\-]+\.(png|jpg|jpeg|webp)$", filename):
        abort(404)
    host_ws = os.environ.get("HOST_WORKSPACE", "")
    if not host_ws:
        abort(404)
    shots_dir = Path(host_ws) / "sessions"
    if not shots_dir.exists():
        abort(404)
    matches = list(shots_dir.glob(f"*/shots/{filename}"))
    if not matches:
        abort(404)
    return send_file(str(matches[0]), mimetype="image/png")


@app.route("/api/state")
def get_state():
    if not log_manager:
        return jsonify({})
    path = request.args.get("path", "")
    if path:
        resolved = _safe_resolve(path)
        if resolved:
            session = log_manager._get_or_create(resolved)
            if not session._loaded:
                session.load_initial()
            session.start()
            return jsonify(session.state())
    default_path = log_manager._default_path()
    if default_path:
        resolved = _safe_resolve(default_path)
        if resolved:
            session = log_manager._get_or_create(resolved)
            if not session._loaded:
                session.load_initial()
            session.start()
            return jsonify(session.state())
    return jsonify({})


def _safe_resolve(path: str) -> Optional[Path]:
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        return None
    if log_root_path:
        try:
            resolved.relative_to(log_root_path)
        except Exception:
            return None
    return resolved


def _log_kind(path: Path) -> str:
    name = path.name
    if name == "agent_events.log" or name.endswith("_agent_events.log"):
        return "events"
    if name.startswith("agent_events-prev-"):
        return "events-prev"
    if name == "agent_run.log":
        return "run"
    if name.endswith("_full.log"):
        return "full"
    return "log"


def _log_label(path: Path) -> str:
    kind = _log_kind(path)
    if log_root_path:
        try:
            rel = path.relative_to(log_root_path)
            parent = rel.parent
            label = parent.name if parent.name else rel.name
            return f"{label} [{kind}]"
        except Exception:
            pass
    return f"{path.name} [{kind}]"


def _collect_logs(root: Optional[Path]) -> list[dict]:
    if not root or not root.exists():
        return []
    patterns = ["agent_events.log", "*_agent_events.log", "agent_events-prev-*.log"]
    seen: set[Path] = set()
    entries: list[dict] = []
    for pattern in patterns:
        for path in root.rglob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                stat = resolved.stat()
                group = "outputs"
                label = _log_label(resolved)
                if log_root_path:
                    try:
                        rel = resolved.relative_to(log_root_path)
                        parent = rel.parent
                        label = rel.name
                        parent_group = parent.as_posix() if parent else ""
                        group = (
                            parent_group if parent_group not in ("", ".") else "outputs"
                        )
                    except Exception:
                        group = "outputs"
                entries.append(
                    {
                        "path": str(resolved),
                        "label": label,
                        "group": group or "logs",
                        "mtime": stat.st_mtime,
                    }
                )
            except Exception:
                continue
    entries.sort(key=lambda e: e.get("label", "").lower())
    return entries


@app.route("/api/logs")
def list_logs():
    logs = _collect_logs(log_root_path)
    default_path = log_manager._default_path() if log_manager else ""
    return jsonify({"logs": logs, "default": default_path})


@app.route("/api/switch", methods=["POST"])
def switch_log():
    path = request.args.get("path", "")
    resolved = _safe_resolve(path)
    if not resolved or not resolved.exists():
        return jsonify({"error": "Log file not found"}), 404
    logs = _collect_logs(log_root_path)
    return jsonify({"logs": logs, "current": str(resolved)})


@socketio.on("connect")
def handle_connect():
    connected_clients.add(request.sid)
    if log_manager:
        session = log_manager.subscribe(request.sid, None)
        if session:
            session.emit_full_state(request.sid)
            emit("log_selected", {"path": str(session.path)})


@socketio.on("disconnect")
def handle_disconnect():
    connected_clients.discard(request.sid)
    if log_manager:
        log_manager.unsubscribe(request.sid)
    # If no clients connected and auto-close is enabled, shutdown
    if not connected_clients and args.auto_close:
        trigger_shutdown("No clients connected, shutting down...")


@socketio.on("request_full_state")
def handle_full_state():
    if not log_manager:
        emit("full_state", {})
        return
    session = log_manager.subscribe(request.sid, None)
    if session:
        session.emit_full_state(request.sid)
        emit("log_selected", {"path": str(session.path)})
    else:
        emit("full_state", {})


@socketio.on("subscribe")
def handle_subscribe(data):
    if not log_manager:
        emit("full_state", {})
        return
    path = ""
    if isinstance(data, dict):
        path = data.get("path", "")
    session = log_manager.subscribe(request.sid, path)
    if session:
        session.emit_full_state(request.sid)
        emit("log_selected", {"path": str(session.path)})
    else:
        emit("full_state", {})


@socketio.on("switch_log")
def handle_switch_log(data):
    handle_subscribe(data)


@socketio.on("shutdown")
def handle_shutdown():
    print("Shutdown requested by client")
    trigger_shutdown("Shutdown requested by client")


def main():
    global args, log_root_path, log_manager

    parser = argparse.ArgumentParser(description="Agent Log Dashboard")
    parser.add_argument("log_file", nargs="?", help="Path to log file to watch")
    parser.add_argument(
        "--port", type=int, default=5050, help="Dashboard port (default: 5050)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Dashboard host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--log-root", type=str, default=None, help="Root directory to search for logs"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't open browser automatically"
    )
    parser.add_argument(
        "--no-auto-close",
        action="store_false",
        dest="auto_close",
        help="Keep running after all browsers disconnect (default: auto close)",
    )
    parser.set_defaults(auto_close=True)
    args = parser.parse_args()

    if args.log_root:
        log_root_path = Path(args.log_root).expanduser().resolve()
    else:
        workspace_persistent = os.environ.get("WORKSPACE_PERSISTENT")
        if workspace_persistent:
            default_root = Path(workspace_persistent) / "outputs"
        else:
            repo_root = Path(__file__).resolve().parents[1]
            default_root = repo_root / "outputs"
        log_root_path = default_root if default_root.exists() else None

    initial_path: Optional[Path] = None
    if args.log_file:
        try:
            candidate = Path(args.log_file).expanduser().resolve()
        except Exception:
            candidate = None
        if candidate and log_root_path:
            try:
                # Only allow selecting logs within log_root_path.
                candidate.relative_to(log_root_path)
                # Allow initial_path even if the file doesn't exist yet;
                # LogSession._watch_loop polls for missing files.
                initial_path = candidate
            except Exception:
                initial_path = None

    log_manager = LogManager(
        log_root_path, socketio, shutdown_event, initial_path=initial_path
    )

    # Find available port (handles TIME_WAIT sockets and race conditions)
    requested_port = args.port
    port = find_available_port(requested_port, args.host)
    if port != requested_port:
        print(f"Port {requested_port} unavailable, using port {port}")

    if not args.no_browser:
        url = f"http://{args.host}:{port}"
        print(f"Opening dashboard: {url}")

        def open_browser():
            time.sleep(1)
            cache_bust_url = f"{url}?t={int(time.time())}"
            webbrowser.open_new_tab(cache_bust_url)

        threading.Thread(target=open_browser, daemon=True).start()

    # Handle shutdown signals
    def signal_handler(sig, frame):
        print("\nShutting down...")
        trigger_shutdown("Signal received, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"Dashboard running on http://{args.host}:{port}")
    print("Press Ctrl+C to stop")

    try:
        socketio.run(
            app, host=args.host, port=port, debug=False, allow_unsafe_werkzeug=True
        )
    except Exception as e:
        print(f"Server error: {e}")


if __name__ == "__main__":
    main()
