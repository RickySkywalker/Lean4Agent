from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List

from ..types.serialization import json_default


def append_jsonl(path: Path, event: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, default=json_default)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            yield json.loads(raw)


@dataclass(frozen=True)
class ReplayFunction:
    name: str
    arguments: str


@dataclass(frozen=True)
class ReplayToolCall:
    id: str
    function: ReplayFunction


@dataclass(frozen=True)
class ReplayMessage:
    content: str
    tool_calls: List[ReplayToolCall]


class TraceReplayer:
    def __init__(self, events: List[Dict[str, Any]]):
        self._events = events
        self._idx = 0

    @classmethod
    def from_file(cls, path: Path) -> "TraceReplayer":
        return cls(list(iter_jsonl(path)))

    def _next(self) -> Dict[str, Any]:
        if self._idx >= len(self._events):
            raise IndexError("trace exhausted")
        ev = self._events[self._idx]
        self._idx += 1
        return ev

    def next_llm_message(self, *, step_id: str, iteration: int) -> ReplayMessage:
        ev = self._next()
        if ev.get("type") != "llm_response":
            raise ValueError(
                f"trace mismatch: expected llm_response, got {ev.get('type')}"
            )
        # Validate alignment between expected and actual event
        ev_step_id = str(ev.get("step_id", ""))
        ev_iteration = ev.get("iteration")
        if ev_step_id != str(step_id):
            raise ValueError(
                f"trace mismatch: expected step={step_id}, got step={ev_step_id}"
            )
        try:
            ev_iter_int = int(ev_iteration) if ev_iteration is not None else -1
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"trace mismatch: invalid iteration in trace: {ev_iteration!r}"
            ) from e
        if ev_iter_int != int(iteration):
            raise ValueError(
                f"trace mismatch: expected iteration={iteration}, got iteration={ev_iter_int}"
            )
        tool_calls = []
        for tc in ev.get("tool_calls") or []:
            tool_calls.append(
                ReplayToolCall(
                    id=str(tc.get("id")),
                    function=ReplayFunction(
                        name=str((tc.get("function") or {}).get("name") or ""),
                        arguments=str(
                            (tc.get("function") or {}).get("arguments") or "{}"
                        ),
                    ),
                )
            )
        return ReplayMessage(
            content=str(ev.get("content") or ""), tool_calls=tool_calls
        )

    def next_tool_result(
        self,
        *,
        step_id: str,
        iteration: int,
        call: int,
        name: str,
    ) -> Dict[str, Any]:
        ev = self._next()
        if ev.get("type") != "tool_result":
            raise ValueError(
                f"trace mismatch: expected tool_result, got {ev.get('type')}"
            )
        # Validate alignment between expected and actual event
        ev_step_id = str(ev.get("step_id", ""))
        ev_iteration = ev.get("iteration")
        ev_call = ev.get("call")
        ev_name = str(ev.get("name", ""))

        if ev_step_id != str(step_id):
            raise ValueError(
                f"trace mismatch: expected step={step_id}, got step={ev_step_id}"
            )
        try:
            ev_iter_int = int(ev_iteration) if ev_iteration is not None else -1
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"trace mismatch: invalid iteration in trace: {ev_iteration!r}"
            ) from e
        if ev_iter_int != int(iteration):
            raise ValueError(
                f"trace mismatch: expected iteration={iteration}, got iteration={ev_iter_int}"
            )
        try:
            ev_call_int = int(ev_call) if ev_call is not None else -1
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"trace mismatch: invalid call in trace: {ev_call!r}"
            ) from e
        if ev_call_int != int(call):
            raise ValueError(
                f"trace mismatch: expected call={call}, got call={ev_call_int}"
            )
        if ev_name != str(name):
            raise ValueError(
                f"trace mismatch: expected tool={name}, got tool={ev_name}"
            )
        return ev


class TraceWriter:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write(self, event: Dict[str, Any]) -> None:
        append_jsonl(self.path, event)
