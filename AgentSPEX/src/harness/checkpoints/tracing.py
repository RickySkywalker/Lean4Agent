"""Tracing and replay functionality for durable execution.

This module provides the TracingMixin that enables durable execution capabilities
by recording LLM responses for replay during recovery.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .durable_execution import iter_jsonl

if TYPE_CHECKING:
    from .durable_execution import TraceWriter


class TracingMixin:
    """Mixin providing tracing and replay capabilities for LLM calls.

    This mixin enables durable execution by recording LLM responses during
    normal execution and replaying them during recovery. This allows the
    agent to resume from checkpoints without re-executing expensive LLM calls.

    Required Attributes:
        Classes using this mixin must initialize these attributes:
        - _trace_lock: threading.Lock for thread-safe trace writing
        - _trace_writer: Optional TraceWriter for recording events
        - _llm_replay_events: Optional list of events for replay mode
        - _replay_index: Current position in replay events

    Example:
        class MyExecutor(TracingMixin):
            def __init__(self):
                self._trace_lock = threading.Lock()
                self._trace_writer = None
                self._llm_replay_events = None
                self._replay_index = 0
    """

    # Type annotations for required attributes
    _trace_lock: threading.Lock
    _trace_writer: Optional[TraceWriter]
    _llm_replay_events: Optional[List[Dict[str, Any]]]
    _replay_index: int

    def _trace(self, event: Dict[str, Any]) -> None:
        """Write a trace event for durable execution.

        Thread-safe method that records events to the trace file when
        tracing is enabled.

        Args:
            event: Dictionary containing event data to record.
                   Should include 'type' key identifying the event type.
        """
        trace_writer = getattr(self, "_trace_writer", None)
        if trace_writer is not None:
            with self._trace_lock:
                trace_writer.write(event)

    def _load_replay(self, trace_path: str) -> None:
        """Load LLM response events from a trace file for replay.

        Reads all LLM response events from a trace file and stores them
        for sequential replay during recovery.

        Args:
            trace_path: Path to the JSONL trace file to load.
        """
        events: List[Dict[str, Any]] = []
        for event in iter_jsonl(Path(trace_path)):
            if event.get("type") == "llm_response":
                events.append(event)
        self._llm_replay_events = events
        self._replay_index = 0

    def _next_replay_event(self, *, step_id: str, iteration: int) -> Dict[str, Any]:
        """Get the next LLM replay event with alignment validation.

        Retrieves the next event from the replay queue and validates that
        it matches the expected step and iteration. This ensures replay
        events are consumed in the correct order.

        Args:
            step_id: Expected step identifier for the event.
            iteration: Expected iteration number for the event.

        Returns:
            The next replay event dictionary.

        Raises:
            RuntimeError: If replay mode is not enabled.
            IndexError: If all replay events have been consumed.
            ValueError: If the event doesn't match expected step/iteration.
        """
        if not self._llm_replay_events:
            raise RuntimeError("LLM replay not enabled")
        if self._replay_index >= len(self._llm_replay_events):
            raise IndexError("LLM replay trace exhausted")

        event = self._llm_replay_events[self._replay_index]
        self._replay_index += 1

        # Validate alignment between expected and actual event
        event_step_id = str(event.get("step_id"))
        event_iteration = int(event.get("iteration", 0))
        if event_step_id != str(step_id) or event_iteration != int(iteration):
            raise ValueError(
                f"LLM trace mismatch: expected step={step_id} iter={iteration}, "
                f"got step={event_step_id} iter={event_iteration}"
            )
        return event
