#!/usr/bin/env python3
"""Event-log cost aggregator + experiment-wide BudgetMonitor.

Event log format: each line is `<<<EVENT>>>{JSON}<<</EVENT>>>` (possibly
with surrounding whitespace). Two event types carry cost:

    workflow_end  (exactly once per completed run)
      data.cost    — authoritative cumulative USD for that run
      data.synthetic_timeout (optional bool) — True when the run was killed
                      by a watchdog and cost was not accumulated; in that
                      case fall back to the per-message sum.

    messages_end  (one per LLM turn)
      data.usage.cost — per-turn USD

Cost accounting rule: **prefer workflow_end.cost as the authoritative total
for an instance**. It is the cumulative sum reported by the AgentSPEX
framework. Summing messages_end on top of workflow_end double-counts.
Only fall back to `sum(messages_end.cost)` when the workflow_end is
synthetic (watchdog-killed) and its .cost is 0.

Empirical audit on django__django-15022_agent_events.log:
    workflow_end.cost           = 2.98
    sum(messages_end.cost)      = 5.96  (2× of above — DO NOT sum both)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional


EVENT_RE = re.compile(r"<<<EVENT>>>(.*?)<<</EVENT>>>", re.DOTALL)


@dataclass
class InstanceCost:
    log_path: Path
    final_cost_usd: float = 0.0          # from workflow_end (authoritative)
    live_cost_usd: float = 0.0           # running sum of messages_end (for live instances)
    has_workflow_end: bool = False
    synthetic_timeout: bool = False
    messages_end_count: int = 0

    @property
    def effective_cost(self) -> float:
        """The best-available total for this instance.

        If workflow_end exists AND was NOT a synthetic timeout, use it.
        Otherwise fall back to the running messages_end sum."""
        if self.has_workflow_end and not self.synthetic_timeout:
            return self.final_cost_usd
        return self.live_cost_usd


def parse_event_log(path: Path) -> InstanceCost:
    """Parse one event log into an InstanceCost. Robust to partial writes."""
    out = InstanceCost(log_path=path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError):
        return out
    for m in EVENT_RE.finditer(text):
        blob = m.group(1).strip()
        try:
            evt = json.loads(blob)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")
        data = evt.get("data") or {}
        if etype == "workflow_end":
            out.has_workflow_end = True
            # `cost` lives directly in data; synthetic marker from lean_evolve
            # runner lives at data.synthetic_timeout.
            out.final_cost_usd = float(data.get("cost") or 0.0)
            out.synthetic_timeout = bool(data.get("synthetic_timeout") or False)
        elif etype == "messages_end":
            usage = data.get("usage") or {}
            out.live_cost_usd += float(usage.get("cost") or 0.0)
            out.messages_end_count += 1
    return out


def _iter_event_logs(roots: Iterable[Path]) -> Iterable[Path]:
    """Yield every agent event log under `roots`, skipping pristine
    INPUT copies (those come from the baseline trajectory and would
    double-count against the experiment's own spend).

    Two filename conventions in use:
      * per-instance: `<instance_id>_agent_events.log` (used by
        swe_bench_verified/run.py and friends)
      * run-local:    `agent_events.log` (used by scripts/run_agent.sh
        when the AgentSPEX is spawned with --output_dir set)
    """
    for root in roots:
        if not root.exists():
            continue
        for pat in ("*_agent_events.log", "agent_events.log"):
            for p in root.rglob(pat):
                # Skip copies staged as inputs to downstream stages —
                # they're from the baseline run, not this experiment.
                parts = p.parts
                if "inputs" in parts:
                    continue
                yield p


def sum_costs(roots: Iterable[Path]) -> tuple[float, float, dict[Path, InstanceCost]]:
    """Walk every *_agent_events.log under each root and sum costs.

    Returns (final_total, live_total, by_path).
      final_total: sum of `effective_cost` across all instances — the canonical
                   experiment-wide total.
      live_total:  sum of `live_cost_usd` — useful for per-instance soft caps
                   on in-flight runs.
    """
    final_total = 0.0
    live_total = 0.0
    by_path: dict[Path, InstanceCost] = {}
    for p in _iter_event_logs(roots):
        ic = parse_event_log(p)
        by_path[p] = ic
        final_total += ic.effective_cost
        live_total += ic.live_cost_usd
    return final_total, live_total, by_path


class BudgetExceeded(Exception):
    pass


@dataclass
class BudgetMonitor:
    """Experiment-wide budget enforcer.

    Spawns a background thread that rescans `roots` every `poll_interval_sec`
    seconds and maintains a running `(total, by_path)` snapshot. The caller
    should gate every new subprocess spawn via `pre_spawn_gate(expected_usd)`
    (synchronous; raises BudgetExceeded if over), and poll
    `over_soft_cap_instances()` to decide which live instances to kill.

    Design note: the 30s poll cadence means brief bursts can momentarily
    exceed the cap by at most one instance's per-turn cost. The per-instance
    soft cap + `pre_spawn_gate` together ensure the cumulative overshoot is
    bounded.
    """
    cap_usd: float
    soft_cap_per_instance_usd: float
    roots: list[Path]
    poll_interval_sec: float = 30.0
    ledger_path: Optional[Path] = None        # append-only JSONL of snapshots
    pre_spawn_margin_usd: float = 5.0         # pre-gate at cap - margin

    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _snapshot: dict = field(default_factory=dict, init=False, repr=False)
    _last_ok: bool = field(default=True, init=False, repr=False)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._refresh_now()
        t = threading.Thread(target=self._loop, name="BudgetMonitor",
                             daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval_sec):
            self._refresh_now()

    def _refresh_now(self) -> None:
        final_total, live_total, by_path = sum_costs(self.roots)
        over_soft = {
            p: ic.live_cost_usd for p, ic in by_path.items()
            if (not ic.has_workflow_end
                and ic.live_cost_usd > self.soft_cap_per_instance_usd)
        }
        with self._lock:
            self._snapshot = {
                "timestamp": time.time(),
                "final_total_usd": round(final_total, 4),
                "live_total_usd": round(live_total, 4),
                "n_instances": len(by_path),
                "over_soft_cap": {str(p): round(v, 4)
                                  for p, v in over_soft.items()},
            }
        if self.ledger_path is not None:
            try:
                with open(self.ledger_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(self._snapshot) + "\n")
            except OSError:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def total_usd(self) -> float:
        with self._lock:
            return float(self._snapshot.get("final_total_usd", 0.0))

    def pre_spawn_gate(self, expected_usd: float = 5.0) -> None:
        """Synchronous gate. Call BEFORE spawning a new instance. If the
        projected total (current_total + expected_usd + margin) would exceed
        cap_usd, raise BudgetExceeded. `expected_usd` should be a
        conservative estimate of what the new instance will cost."""
        self._refresh_now()
        total = self.total_usd()
        projected = total + expected_usd + self.pre_spawn_margin_usd
        if projected > self.cap_usd:
            raise BudgetExceeded(
                f"pre_spawn_gate: projected ${projected:.2f} "
                f"(current ${total:.2f} + expected ${expected_usd:.2f} "
                f"+ margin ${self.pre_spawn_margin_usd:.2f}) > cap ${self.cap_usd:.2f}")

    def over_soft_cap_instances(self) -> dict[str, float]:
        """Return {log_path_str: live_cost} for in-flight instances whose
        live cost has exceeded `soft_cap_per_instance_usd`."""
        snap = self.snapshot()
        return dict(snap.get("over_soft_cap", {}))


# -----------------------------------------------------------------------------
# CLI — ad-hoc one-shot aggregation
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Aggregate cost across event logs under one or more roots.")
    ap.add_argument("--root", action="append", required=True, type=Path,
                    help="directory to recursively scan for *_agent_events.log "
                         "(repeat for multiple roots)")
    ap.add_argument("--json", action="store_true",
                    help="emit structured JSON instead of human-readable")
    args = ap.parse_args()

    final_total, live_total, by_path = sum_costs(args.root)

    if args.json:
        payload = {
            "final_total_usd": round(final_total, 4),
            "live_total_usd": round(live_total, 4),
            "n_instances": len(by_path),
            "per_instance": {
                str(p): {
                    "effective_cost": round(ic.effective_cost, 4),
                    "final_cost": round(ic.final_cost_usd, 4),
                    "live_cost": round(ic.live_cost_usd, 4),
                    "has_workflow_end": ic.has_workflow_end,
                    "synthetic_timeout": ic.synthetic_timeout,
                    "messages_end_count": ic.messages_end_count,
                }
                for p, ic in sorted(by_path.items())
            },
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"final_total_usd : ${final_total:.4f}   (authoritative; from workflow_end)")
    print(f"live_total_usd  : ${live_total:.4f}   (running messages_end sum)")
    print(f"n_instances     : {len(by_path)}")
    print(f"{'log':<60}  {'effective':>10}  {'final':>10}  {'live':>10}  WE  ST")
    for p, ic in sorted(by_path.items()):
        shortp = str(p).replace(
            "", "")
        print(f"{shortp[-58:]:<60}  "
              f"${ic.effective_cost:>9.4f}  ${ic.final_cost_usd:>9.4f}  "
              f"${ic.live_cost_usd:>9.4f}  "
              f"{'Y' if ic.has_workflow_end else 'N'}   "
              f"{'Y' if ic.synthetic_timeout else 'N'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
