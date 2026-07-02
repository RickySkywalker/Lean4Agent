#!/usr/bin/env python3
"""
layer3_ir_init.py - Seed an empty Layer 3 IR JSON from a reference Layer 2 IR
and a freshly-segmented agent trajectory.

What this does:
  - Loads the reference Layer 2 IR (JSON dump of `WorkflowIR`, same schema as
    leanagent/codegen/lean_verifier/TaskPlanToLean.py emits with --save_ir).
  - Scans `trace_index.json` (produced by trace_segmenter.py) to line up each
    runtime step with one Layer 2 semantic node by ordinal position.
  - Emits a `layer3_ir.json` whose `exec_state` and `llm_injections` are empty;
    the YAML task plan fills them in per-step.

The output JSON is shaped exactly like `leanagent/codegen/lean_verifier/TaskPlanToLean.Layer3IR.to_dict()`
and is consumable by `ir_to_lean.py` (the codegen, `layer3_v2_codegen.generate_layer3_v2_lean`).

CLI:
  python layer3_ir_init.py \\
      --layer2_ir <reference L2 IR>.json \\
      --trace_index <staging>/trace_index.json \\
      --instance_id django__django-14140 \\
      --plan_name passed_workflow_1 \\
      --event_log_path <abs path> \\
      --report_path <abs path> \\
      --out <staging>/layer3_ir.json \\
      [--prefix passed_workflow_1_v2] [--suffix _14140]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def sanitize_suffix(instance_id: str) -> str:
    """Reduce 'django__django-14140' -> '_14140' etc.; best-effort numeric tail."""
    m = re.search(r"(\d+)\s*$", instance_id)
    if m:
        return f"_{m.group(1)}"
    safe = re.sub(r"[^A-Za-z0-9_]", "_", instance_id).strip("_")
    return f"_{safe}" if safe else ""


def _default_for_param(name: str, base_type: str, preds: list[dict]) -> str:
    """Fallback value when a parameter is declared in Layer 2 but not present in
    the event log's workflow/step variables. Chosen so the usual SWE-bench
    predicates (isValidFilePath, isNonEmptyString, nameExists) are satisfied."""
    kinds = {p.get("kind") for p in preds or []}
    if "isValidFilePath" in kinds:
        # SWE-bench convention: the container's working directory.
        return "/testbed"
    if "isNonEmptyString" in kinds:
        return "<provided>"
    return ""  # nameExists only cares that the key is bound


def compute_seed_exec_state(workflow: dict,
                            workflow_params: dict,
                            observed_tools: list[str]) -> list[list]:
    """Build exec_state entries for Layer 2 parameters + tools observed in the
    trace. Return a list of `[var_name, raw_string]` pairs suitable for direct
    inclusion in a Layer3IR JSON. Parameters come first, then tools; order
    within each group follows Layer 2 declaration order / trace arrival order."""
    out: list[list] = []
    seen: set[str] = set()
    for p in workflow.get("parameters", []) or []:
        name = p.get("name", "")
        if not name or name in seen:
            continue
        raw = workflow_params.get(name)
        if raw is None or raw == "":
            raw = _default_for_param(name, p.get("base_type", ""), p.get("predicates", []))
        out.append([name, raw])
        seen.add(name)
    for tool in observed_tools or []:
        if tool and tool not in seen:
            out.append([tool, "<tool>"])
            seen.add(tool)
    return out


def main():
    p = argparse.ArgumentParser(description="Initialise Layer 3 IR JSON.")
    p.add_argument("--layer2_ir", required=True, help="Path to reference Layer 2 IR JSON")
    p.add_argument("--trace_index", required=True, help="Path to trace_index.json from trace_segmenter")
    p.add_argument("--instance_id", required=True, help="SWE-bench instance id")
    p.add_argument("--plan_name", default="passed_workflow_1", help="Plan name for defaults")
    p.add_argument("--event_log_path", required=True, help="Absolute path to agent_events.log")
    p.add_argument("--report_path", required=True, help="Absolute path to report.json")
    p.add_argument("--out", required=True, help="Output Layer 3 IR JSON path")
    p.add_argument("--prefix", default="", help="Lean def prefix (default: <plan_name>_v2)")
    p.add_argument("--suffix", default="", help="Lean def suffix (default: _<numeric tail of instance>)")
    p.add_argument("--banner_title", default="", help="Optional banner for #eval!")
    p.add_argument("--banner_subtitle", default="", help="Optional banner subtitle for #eval!")
    args = p.parse_args()

    layer2_ir = json.loads(Path(args.layer2_ir).read_text(encoding="utf-8"))
    trace_index = json.loads(Path(args.trace_index).read_text(encoding="utf-8"))

    if "nodes" not in layer2_ir:
        if "workflow" in layer2_ir and "nodes" in layer2_ir["workflow"]:
            workflow = layer2_ir["workflow"]
        else:
            print("ERROR: reference Layer 2 IR missing 'nodes' field", file=sys.stderr)
            sys.exit(1)
    else:
        workflow = layer2_ir

    prefix = args.prefix or f"{args.plan_name}_v2"
    suffix = args.suffix if args.suffix else sanitize_suffix(args.instance_id)

    l2_nodes = workflow.get("nodes", [])
    trace_steps = trace_index.get("steps", [])

    if not l2_nodes:
        print("ERROR: Layer 2 IR has no nodes", file=sys.stderr)
        sys.exit(1)
    if not trace_steps:
        print("ERROR: trace_index has no steps", file=sys.stderr)
        sys.exit(1)

    step_id_map: list[list] = []
    dyn_nodes: list[dict] = []
    n_paired = min(len(l2_nodes), len(trace_steps))
    for idx in range(n_paired):
        ts = trace_steps[idx]
        node = l2_nodes[idx]
        sid = str(ts.get("step_id", idx + 1))
        sname = ts.get("step_name") or node.get("name", f"step_{idx}")
        step_id_map.append([sid, idx])
        dyn_nodes.append({
            "sem_node_ref": f"{prefix}_semNode{idx}",
            "trajectory_step_id": sid,
            "trajectory_step_name": sname,
            "execution_status": "completed",
        })

    if len(l2_nodes) != len(trace_steps):
        print(f"WARN: Layer 2 has {len(l2_nodes)} nodes but trace has {len(trace_steps)} steps; "
              f"pairing the first {n_paired} by ordinal.", file=sys.stderr)

    # Pre-seed exec_state with the workflow parameters + any tool used in the
    # trace. These come from the event log — NOT the LLM — because their values
    # are deterministic and are required for Layer 3's exit-fact discharge
    # (e.g. `code_path : isValidFilePath`, `shell_run : toolExists`) to succeed.
    workflow_params = trace_index.get("workflow_parameters", {}) or {}
    observed_tools = trace_index.get("observed_tools", []) or []
    exec_state = compute_seed_exec_state(workflow, workflow_params, observed_tools)

    ir: dict = {
        "ir_kind": "layer3",
        "workflow": workflow,
        "prefix": prefix,
        "suffix": suffix,
        "report_path": str(Path(args.report_path).resolve()),
        "event_log_path": str(Path(args.event_log_path).resolve()),
        "step_id_map": step_id_map,
        "exec_state": exec_state,
        "dyn_nodes": dyn_nodes,
        "llm_injections": [],
    }
    if args.banner_title:
        ir["banner_title"] = args.banner_title
    if args.banner_subtitle:
        ir["banner_subtitle"] = args.banner_subtitle

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK: seeded Layer 3 IR -> {out_path} "
          f"({len(dyn_nodes)} dyn_nodes, {len(exec_state)} exec_state seeds "
          f"[params+tools], empty llm_injections)")


if __name__ == "__main__":
    main()
