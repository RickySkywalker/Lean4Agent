"""Content-growth-based idle watchdog for long-running agent subprocesses.

Fires a callback when an event-log file hasn't GROWN for `idle_seconds`.
Uses byte offset (st_size) rather than mtime because:
  * a wedged agent can touch-heartbeat the log while making no real progress
  * Docker bind-mount semantics sometimes fail to propagate mtime updates

Typical usage in a spawn site:

    from harness.utils.idle_watchdog import IdleWatchdog

    def on_stall():
        logger.warning("idle-watchdog firing; killing subprocess")
        proc.terminate()
        # emit a synthetic workflow_end into the event log so downstream
        # cost aggregation and resume logic have something to parse.

    wd = IdleWatchdog(event_log_path=log_path,
                      idle_seconds=7200,     # 2 h
                      poll_interval=30,
                      on_stall=on_stall)
    wd.start()
    try:
        proc.wait()
    finally:
        wd.stop()

The watchdog only fires ONCE. On subsequent stall checks after firing it
stays quiet — the caller's `on_stall` is responsible for terminating the
subprocess. If you restart the subprocess with a fresh log file, create a
new `IdleWatchdog` for it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class IdleWatchdog:
    event_log_path: Path
    idle_seconds: float
    on_stall: Callable[[], None]
    poll_interval: float = 30.0
    # If the log doesn't exist yet (subprocess still warming up), treat
    # non-existence as "growing" for this many seconds before starting the
    # idle count — otherwise we'd fire immediately on startup.
    warmup_seconds: float = 120.0

    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _fired: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _last_size: int = field(default=-1, init=False, repr=False)
    _last_growth_time: float = field(default=0.0, init=False, repr=False)
    _start_time: float = field(default=0.0, init=False, repr=False)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._start_time = time.time()
        self._last_growth_time = self._start_time
        t = threading.Thread(target=self._loop,
                             name=f"IdleWatchdog[{self.event_log_path.name}]",
                             daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    @property
    def fired(self) -> bool:
        return self._fired.is_set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            if self._fired.is_set():
                # Already stalled; stop polling but keep the thread alive
                # until stop() is called (cheap).
                continue
            now = time.time()
            try:
                size = self.event_log_path.stat().st_size
            except FileNotFoundError:
                # No log yet. If still within warmup window, keep waiting.
                if now - self._start_time < self.warmup_seconds:
                    continue
                # Past warmup with no log — treat as stall if beyond idle.
                size = 0
            except OSError:
                # Transient I/O error; don't fire on it.
                continue

            if size > self._last_size:
                self._last_size = size
                self._last_growth_time = now
                continue

            # No growth since _last_growth_time.
            if now - self._last_growth_time >= self.idle_seconds:
                self._fired.set()
                try:
                    self.on_stall()
                except Exception:
                    # Never let a callback exception kill the watchdog
                    # thread; stopping the subprocess is the caller's job
                    # and we've at least set `fired`.
                    pass
