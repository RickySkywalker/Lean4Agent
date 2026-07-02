#!/usr/bin/env python3
"""
elaip_layer3_codegen.py — Emit a per-(plan, qid) Layer-3 `.lean` file from
an ELAIP Layer-3 IR JSON (produced by `elaip_layer3_ir_init.py`).

This is now a THIN ADAPTER over the unified codegen
`leanagent/codegen/lean_verifier/layer3_v2_codegen.py`: the ELAIP IR is normalised into the
shared `ir_kind: "layer3_v2"` schema (benchmark = "elaip") and handed to
`generate_layer3_v2_lean`. The SAME emitter drives the SWE-bench json→Layer-3
path, so the two benchmarks stay in lock-step — they differ only in the *Tool
channel* (SWE reads a `report.json`; ELAIP derives tool verdicts from the
post-execution state via `ElaipBench.rulesFromState`).

Output path (default):
  FormalAgentLib/AgentVerifier/DynamicVerification/ElaipBench/ElaipExamples/
      <plan>_q<qid>_per_step_v2.lean

The emitted file:
  - Imports the framework (the umbrella `DynamicVerification`) and the
    plan's hand-written Layer-2 module
    (`«TestVerifications».«ELAIP-Bench_selscted».{best,worst}.<plan>_layer2_v2`).
  - Declares `namespace AgenticKernel.<plan>_q<qid>_v2` and `open
    AgenticKernel.Dyn`. The ELAIP Layer-2 graph lives directly in `AgenticKernel`
    (a flat namespace), so it is visible from the nested analysis namespace WITHOUT
    an explicit `open` — hence `open_namespace` is left empty (contrast the SWE
    `*_layer2_new.lean`, which uses a nested L2 namespace and DOES need the open).
  - Hard-codes `eventLogPath`, `execState` (final-state snapshot), and the
    `(step_name, trajectory_step_id)` entries used by the by-name builders
    (`ElaipBench.buildStepIdMapByName` / `buildDynamicGraphByName`) to wire the
    dynamic graph against the L2 SemanticGraph by name.
  - Bakes in `llmInjections` (Stage A's annotator YAML pre-populates these by
    editing the IR JSON before this codegen runs).
  - Ends with an `#eval!` that runs `analyzeAllSteps` + `renderFullReport`
    (three-channel unified report) + `layer3ToJson` (machine-readable JSON).

CLI:
  python elaip_layer3_codegen.py \\
      --ir <staging>/layer3_ir.json \\
      --out <abs path>/<plan>_q<qid>_per_step_v2.lean
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
DEFAULT_OUT_DIR = (REPO_ROOT
                   / "FormalAgentLib/AgentVerifier/DynamicVerification/ElaipBench/ElaipExamples")

# The unified Layer-3 codegen lives in the SWE pipeline dir; import it so both
# benchmarks share one emitter + one IR schema.
_LEAN_VERIFIER_DIR = REPO_ROOT / "leanagent" / "codegen" / "lean_verifier"
sys.path.insert(0, str(_LEAN_VERIFIER_DIR))
try:
    import layer3_v2_codegen as L3V2  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"ERROR: cannot import layer3_v2_codegen from {_LEAN_VERIFIER_DIR}: {e}",
          file=sys.stderr)
    sys.exit(1)


def lean_safe_ident(s: str) -> str:
    """Convert a question id like '0' or 'q42' to an identifier-safe suffix."""
    s = str(s)
    if s.startswith("q"):
        s = s[1:]
    cleaned = re.sub(r"[^A-Za-z0-9]", "_", s)
    return cleaned or "0"


def elaip_ir_to_unified(ir: dict, var_truncate: int = 16384) -> dict:
    """Normalise an ELAIP Layer-3 IR (`ir_kind: "elaip_layer3"`) into the unified
    `layer3_v2` schema consumed by `layer3_v2_codegen.generate_layer3_v2_lean`.

    Already-unified IRs (`ir_kind: "layer3_v2"`) pass through untouched."""
    if ir.get("ir_kind") == "layer3_v2":
        ir.setdefault("var_truncate", var_truncate)
        return ir

    plan = ir.get("plan_name") or "passed_workflow_1"
    qid_raw = ir.get("question_id") or "0"
    suffix = lean_safe_ident(qid_raw)
    layer2 = ir.get("layer2_ref", {}) or {}
    # Fallbacks mirror build_layer2_ir.py's derivation, used only when an older
    # seed IR doesn't carry the resolved Layer-2 reference fields. The
    # hand-written ELAIP L2 specs live at StaticSemanticWorkflowExamples/ELAIP-Bench/
    # ({passed,failed}_workflow_N.lean) with their graph + goalSpec declared
    # inside `namespace AgenticKernel.<plan>_layer2_new`.
    # The plan name is already the Layer-2 `.lean` file stem
    # (passed_workflow_N / failed_workflow_N).
    wf_file = plan
    layer2_module = layer2.get("layer2_module") or \
        f"StaticSemanticWorkflowExamples.«ELAIP-Bench».{wf_file}"
    open_namespace = layer2.get("open_namespace") or f"AgenticKernel.{plan}_layer2_new"
    semantic_graph_def = layer2.get("semantic_graph_def") or f"{plan}_layer2SemanticGraph"
    goal_spec_def = layer2.get("goal_spec_def") or f"{plan}_goalSpec"

    return {
        "ir_kind": "layer3_v2",
        "benchmark": "elaip",
        "plan_name": plan,
        "question_id": str(qid_raw),
        "namespace_suffix": f"q{suffix}",
        "label": ir.get("banner_title") or f"ELAIP {plan} × q{qid_raw}",
        "header_comment": ir.get("banner_subtitle"),
        "layer2_ref": {
            "mode": "import",
            "layer2_module": layer2_module,
            # The ELAIP L2 graph + goalSpec are declared inside
            # `namespace AgenticKernel.<plan>_layer2_new`, so the generated
            # Layer-3 file must open it to resolve <plan>_layer2SemanticGraph.
            "open_namespace": open_namespace,
            "semantic_graph_def": semantic_graph_def,
            "goal_spec_def": goal_spec_def,
        },
        # No report_path: ELAIP has no harness eval; the Tool channel uses
        # `ElaipBench.rulesFromState execState` (selected by benchmark="elaip").
        "event_log_path": ir.get("event_log_path") or "",
        "dyn_nodes": ir.get("dyn_nodes", []) or [],
        "exec_state": ir.get("exec_state", []) or [],
        "llm_injections": ir.get("llm_injections", []) or [],
        "var_truncate": var_truncate,
    }


def generate_lean(ir: dict, var_truncate: int = 16384) -> str:
    """Back-compat shim: normalise the ELAIP IR and emit via the shared core."""
    unified = elaip_ir_to_unified(ir, var_truncate=var_truncate)
    return L3V2.generate_layer3_v2_lean(unified)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ir", required=True, help="Path to Layer-3 IR JSON")
    p.add_argument("--out", default="",
                   help=f"Output .lean path (default: under {DEFAULT_OUT_DIR})")
    p.add_argument("--var-truncate", type=int, default=16384,
                   help="Per-variable raw-string truncation (default: 16384 chars)")
    args = p.parse_args()

    ir_path = Path(args.ir).resolve()
    if not ir_path.exists():
        print(f"ERROR: IR JSON not found: {ir_path}", file=sys.stderr)
        sys.exit(2)
    ir = json.loads(ir_path.read_text(encoding="utf-8"))

    plan = ir.get("plan_name") or "plan"
    qid_safe = lean_safe_ident(ir.get("question_id") or "0")
    if args.out:
        out_path = Path(args.out).resolve()
    else:
        out_path = DEFAULT_OUT_DIR / f"{plan}_q{qid_safe}_per_step_v2.lean"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    code = generate_lean(ir, var_truncate=args.var_truncate)
    out_path.write_text(code, encoding="utf-8")
    n_lines = code.count("\n") + 1
    print(f"OK: wrote {out_path} ({n_lines} lines, benchmark=elaip)")


if __name__ == "__main__":
    main()
