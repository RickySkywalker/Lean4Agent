#!/usr/bin/env python3
"""
elaip_layer3_ir_init.py — Seed an empty Layer-3 IR JSON for an ELAIP-Bench
(plan, question_id) pair from the plan's Layer-2 IR + the agent's trajectory.

Differences from `leanagent/codegen/agent_evolve/layer3_ir_init.py` (the SWE version):
  * No `--report_path`/`--test_output_path`; ELAIP has no harness eval.
  * Reads ELAIP-specific Layer-2 IR (schema from `build_layer2_ir.py`).
  * Walks the agent_events.log directly (the log uses
    `<<<EVENT>>>{json}<<</EVENT>>>` markers, not plain JSONL).
  * Pairs Layer-2 nodes against trajectory step_starts by step name; nodes
    that never appear in the trace (set_variable, increment, branches the
    agent did not take) get `execution_status: "skipped"`.
  * Final-state exec_state comes from the LAST step_start's `variables`
    field (which reflects every variable written up to that step).

CLI:
  python elaip_layer3_ir_init.py \\
      --layer2_ir <plan>_layer2_v2.ir.json \\
      --event_log <abs path>/agent_events.log \\
      --question_id 0 \\
      --plan_name passed_workflow_1 \\
      --out <staging>/layer3_ir.json \\
      [--banner_title <str>] [--banner_subtitle <str>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EVENT_RE = re.compile(r"<<<EVENT>>>(.*?)<<</EVENT>>>", re.DOTALL)


def parse_event_log(event_log_path: Path) -> list[dict]:
    raw = event_log_path.read_text(encoding="utf-8", errors="replace")
    events: list[dict] = []
    for m in EVENT_RE.finditer(raw):
        try:
            events.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return events


def collect_step_starts(events: list[dict]) -> list[dict]:
    """Return step_start events in the order they occurred."""
    return [e for e in events if e.get("type") == "step_start"]


def collect_final_variables(events: list[dict]) -> dict:
    """Walk events end-to-start; return the variables dict from the latest
    event that carries one (`step_start` is the most reliable carrier)."""
    for e in reversed(events):
        data = e.get("data", {}) or {}
        v = data.get("variables")
        if isinstance(v, dict):
            return v
    return {}


def build_step_id_map_and_dyn_nodes(layer2_nodes: list[dict],
                                    step_starts: list[dict]
                                    ) -> tuple[list[list], list[dict]]:
    """Pair Layer-2 nodes with trajectory step_starts by step name.
    For each L2 node:
      * If its `name` matches at least one step_start, pair with the FIRST
        unmatched occurrence. Status = "completed".
      * Else status = "skipped" (branch the agent didn't take, or
        non-executable node like `set_variable`).
    Returns parallel lists `step_id_map` and `dyn_nodes`."""
    used: set[int] = set()
    step_id_map: list[list] = []
    dyn_nodes: list[dict] = []

    for idx, node in enumerate(layer2_nodes):
        name = node.get("name") or f"node_{idx}"
        executable = node.get("executable", True)
        match_ix = -1
        if executable:
            for ti, ts in enumerate(step_starts):
                if ti in used:
                    continue
                ts_name = ts.get("data", {}).get("name") or ""
                if ts_name == name:
                    match_ix = ti
                    used.add(ti)
                    break
        if match_ix >= 0:
            ts = step_starts[match_ix]
            sid = str(ts.get("data", {}).get("step_id") or (match_ix + 1))
            sname = name
            status = "completed"
        else:
            sid = ""
            sname = name
            status = "skipped"
        step_id_map.append([sid, idx])
        dyn_nodes.append({
            "node_id": idx,
            "node_name": name,
            "trajectory_step_id": sid,
            "trajectory_step_name": sname,
            "execution_status": status,
            "branch_path": node.get("branch_path", []),
            "save_as": node.get("save_as"),
        })
    return step_id_map, dyn_nodes


def compute_seed_exec_state(layer2_ir: dict, final_vars: dict) -> list[list]:
    """Build [(name, raw_string)] entries from the final-state variables of the
    trajectory. Layer-2 parameters are seeded first (in declaration order);
    everything else (per-step `save_as` writes) follows in alphabetical order."""
    out: list[list] = []
    seen: set[str] = set()
    # Parameters first.
    for p in layer2_ir.get("parameters", []) or []:
        name = p.get("name")
        if not name:
            continue
        if name in final_vars:
            raw = _stringify(final_vars[name])
        else:
            raw = p.get("default", "") or ""
        out.append([name, raw])
        seen.add(name)
    # Then any other variable written by the trajectory.
    for name in sorted(final_vars.keys()):
        if name in seen:
            continue
        out.append([name, _stringify(final_vars[name])])
        seen.add(name)
    return out


def _stringify(v: Any) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(v)


def seed_layer3_ir(layer2_ir: dict,
                   event_log_path: Path,
                   plan_name: str,
                   question_id: str,
                   banner_title: str = "",
                   banner_subtitle: str = "") -> dict:
    events = parse_event_log(event_log_path)
    if not events:
        raise RuntimeError(
            f"Event log {event_log_path} contains zero parseable events"
        )
    step_starts = collect_step_starts(events)
    final_vars = collect_final_variables(events)
    layer2_nodes = layer2_ir.get("nodes", []) or []
    step_id_map, dyn_nodes = build_step_id_map_and_dyn_nodes(layer2_nodes,
                                                              step_starts)
    exec_state = compute_seed_exec_state(layer2_ir, final_vars)

    ir = {
        "ir_kind": "elaip_layer3",
        "plan_name": plan_name,
        "question_id": str(question_id),
        "layer2_ref": {
            "plan_kind": layer2_ir.get("plan_kind"),
            "layer2_module": layer2_ir.get("layer2_module"),
            "open_namespace": layer2_ir.get("open_namespace"),
            "prefix": layer2_ir.get("prefix"),
            "semantic_graph_def": layer2_ir.get("semantic_graph_def"),
            "goal_spec_def": layer2_ir.get("goal_spec_def"),
        },
        "event_log_path": str(event_log_path.resolve()),
        "step_id_map": step_id_map,
        "exec_state": exec_state,
        "dyn_nodes": dyn_nodes,
        # Postcond predicates per node, copied so the Layer-3 codegen does not
        # have to re-read the Layer-2 IR.
        "postconds_per_node": [
            {"node_id": n["id"],
             "node_name": n["name"],
             "save_as": n.get("save_as"),
             "executable": n.get("executable", True),
             "postconds": n.get("postconds", [])}
            for n in layer2_nodes
        ],
        "llm_injections": [],
        "stats": {
            "n_layer2_nodes": len(layer2_nodes),
            "n_executed_steps": len(step_starts),
            "n_paired": sum(1 for d in dyn_nodes if d["execution_status"] == "completed"),
            "n_skipped": sum(1 for d in dyn_nodes if d["execution_status"] == "skipped"),
            "final_state_var_count": len(exec_state),
        },
    }
    if banner_title:
        ir["banner_title"] = banner_title
    if banner_subtitle:
        ir["banner_subtitle"] = banner_subtitle
    return ir


def main():
    p = argparse.ArgumentParser(description="Seed Layer-3 IR JSON for an ELAIP pair.",
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--layer2_ir", required=True,
                   help="Path to the plan's Layer-2 IR JSON (from build_layer2_ir.py)")
    p.add_argument("--event_log", required=True,
                   help="Path to agent_events.log for one (plan, qid) trajectory")
    p.add_argument("--question_id", required=True, help="Question id (e.g. 0)")
    p.add_argument("--plan_name", required=True, help="e.g. passed_workflow_1")
    p.add_argument("--out", required=True, help="Output Layer-3 IR JSON path")
    p.add_argument("--banner_title", default="", help="Optional banner for #eval!")
    p.add_argument("--banner_subtitle", default="", help="Optional banner subtitle")
    args = p.parse_args()

    layer2_ir = json.loads(Path(args.layer2_ir).read_text(encoding="utf-8"))
    event_log = Path(args.event_log).resolve()
    if not event_log.exists():
        print(f"ERROR: event log not found: {event_log}", file=sys.stderr)
        sys.exit(2)

    ir = seed_layer3_ir(
        layer2_ir, event_log, args.plan_name, args.question_id,
        banner_title=args.banner_title, banner_subtitle=args.banner_subtitle,
    )

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    s = ir["stats"]
    print(f"OK: seeded Layer-3 IR -> {out_path}\n"
          f"     L2 nodes: {s['n_layer2_nodes']}, executed: {s['n_executed_steps']}, "
          f"paired: {s['n_paired']}, skipped: {s['n_skipped']}, "
          f"exec_state vars: {s['final_state_var_count']}")


if __name__ == "__main__":
    main()
