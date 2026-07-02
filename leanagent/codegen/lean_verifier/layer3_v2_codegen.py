#!/usr/bin/env python3
"""
layer3_v2_codegen.py — Unified JSON → Layer-3 Lean codegen for BOTH the
SWE-bench and ELAIP pipelines.

This replaced the now-removed V1 generator (`TaskPlanToLean._gen_layer3_tail` /
`generate_layer3_lean`). It targets the rebuilt dynamic layer that lives under
`AgentVerifier/DynamicVerification/` (namespace `AgenticKernel.Dyn`), the
same surface the hand-written reference examples under
`FormalAgentLib/DynamicLayerExamples/` use and the one
`experiments/elaip_LeanEvolve/elaip_layer3_codegen.py`
emits.  One module produces the Lean for both benchmarks; they differ only in
the *Tool channel* (SWE reads a SWE-bench `report.json`; ELAIP derives tool
verdicts from the post-state).

────────────────────────────────────────────────────────────────────────────
THE UNIFIED LAYER-3 V2 IR  (`ir_kind: "layer3_v2"`)
────────────────────────────────────────────────────────────────────────────
A Layer-3 eval = 4 input blocks assembled into one `.lean`; only ONE block
(`llm_injections`) is written by an LLM — everything else is mechanical:

    {
      "ir_kind": "layer3_v2",
      "benchmark": "swe" | "elaip",       # selects the Tool channel + runner
      "plan_name": "passed_workflow_1",
      "instance_id": "astropy__astropy-7166",   # SWE id, or ELAIP question id
      "namespace_suffix": "astropy_7166",        # → namespace AgenticKernel.<plan>_<suffix>_v2

      # ── BLOCK 1: Layer-2 contract (already exists; never LLM) ───────────
      "layer2_ref": {
        # import mode (standalone files; ELAIP + the hand-written examples):
        "mode": "import",
        "layer2_module":      "VerificationExamples.passed_workflow_1_layer2_new",
        "open_namespace":     "AgenticKernel.passed_workflow_1_layer2_new",
        "semantic_graph_def": "passed_workflow_1_v2SemanticGraph",
        "goal_spec_def":      "passed_workflow_1_v2_goalSpec"
        # — OR — inline mode (transfer pipeline; no importable L2 module):
        #   "mode": "inline", "prefix": "passed_workflow_1_v2", "workflow": {<WorkflowIR>}
        #   (semantic_graph_def/goal_spec_def default to "<prefix>SemanticGraph"/"<prefix>_goalSpec")
      },

      # ── BLOCK 2: runtime wiring (mechanical, from agent_events.log) ─────
      "event_log_path": "/abs/.../astropy__astropy-7166_agent_events.log",
      # step_entries pair an L2 node *name* with its trajectory step id; the
      # by-name builders resolve them against the imported graph (no
      # off-by-one).  If omitted, derived from dyn_nodes (completed only).
      "step_entries": [["explore_repository", "1"], ["reproduce_issue", "2"], ...],
      "dyn_nodes":    [{"node_name": "...", "trajectory_step_name": "...",
                        "trajectory_step_id": "1", "execution_status": "completed"}, ...],
      "exec_state":   [["problem_statement", "..."], ["code_path", "/testbed"], ...],

      # ── BLOCK 3: Tool verdict (Lean reads this at runtime; never LLM) ───
      "report_path": "/abs/.../report.json",      # SWE only; absent for ELAIP

      # ── BLOCK 4: LLM judgements (THE ONLY LLM-WRITTEN BLOCK) ───────────
      "llm_injections": [
        {"step_name": "explore_repository", "var_name": "repository_understanding",
         "holds": true, "confidence": 0.86, "llm_explanation": "...",
         "node_instruction": ""},   # node_instruction optional
        ...
      ],

      # ── cosmetic (only in #eval! output) ───────────────────────────────
      "label": "astropy__astropy-7166",
      "banner_title": "...", "header_comment": "..."
    }

The emitted file (import mode) is byte-for-byte the shape of the hand-written
`passed_workflow_1_astropy_7166_per_step_v2.lean`:

    import … ; import <layer2_module> ; import …DynamicVerification.DynamicVerification
    namespace AgenticKernel.<plan>_<suffix>_v2
    open AgenticKernel.Dyn ; open <open_namespace>
    def reportPath/eventLogPath/stepEntries/execState/stepIdMap/dynamicGraph/llmInjections
    #eval! (… SWEBench.rulesFromReport · analyzeAllSteps · renderFullReport · layer3ToJson …)

Back-compat: this module also reads the legacy SWE `ir_kind: "layer3"`
(`leanagent/codegen/agent_evolve/layer3_ir_init.py`) and the ELAIP `ir_kind: "elaip_layer3"`
(`experiments/elaip_LeanEvolve/.../elaip_layer3_ir_init.py`) shapes by
normalising them into the unified IR first — so the existing IR-init scripts
keep working unchanged.

CLI:
  python layer3_v2_codegen.py --ir <layer3_ir.json> --out <per_step_v2.lean>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ───────────────────────────────────────────────────────────────────────────
# Lean literal helpers
# ───────────────────────────────────────────────────────────────────────────


def lean_str(s) -> str:
    """Escape a Python value for a Lean `"..."` string literal. Control chars
    are kept as \\uXXXX escapes; `\\n`, `\\"`, `\\\\`, `\\r`, `\\t` are emitted
    as their Lean escapes (Lean 4 accepts all of these)."""
    if s is None:
        return '""'
    if not isinstance(s, str):
        s = json.dumps(s, ensure_ascii=False)
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def lean_safe_ident(s: str) -> str:
    """Turn an arbitrary id (instance id / question id) into an identifier-safe
    namespace suffix, e.g. 'astropy__astropy-7166' → 'astropy__astropy_7166'."""
    s = str(s)
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", s).strip("_")
    if not cleaned:
        cleaned = "x"
    if not re.match(r"[A-Za-z_]", cleaned[0]):
        cleaned = "n_" + cleaned
    return cleaned


def fmt_float(x: float) -> str:
    """Lean-friendly float literal (0.85 → '0.85', 1.0 → '1.0')."""
    x = float(x)
    if x.is_integer():
        return f"{x:.1f}"
    s = f"{x:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def truncate_for_lean(s: str, limit: int = 16384) -> str:
    """Lean string literals over ~100KB compile slowly; truncate aggressively
    while recording the original length so the value stays self-describing."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = json.dumps(s, ensure_ascii=False)
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n[TRUNCATED FROM {len(s)} CHARS]"


# ───────────────────────────────────────────────────────────────────────────
# Import blocks
# ───────────────────────────────────────────────────────────────────────────

_STATIC_IMPORTS: list[str] = [
    "import Lean",
    "import Mathlib",
    "import AgentVerifier.StaticLayer",
    "import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer",
    "import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates",
]

# The single V2 umbrella import pulls in §0–§10 transitively (ExecutionTrace,
# PerStepView/SWEBench glue, ElaipBench builders, VerificationJsonOutput).
_UMBRELLA_IMPORT = "import AgentVerifier.DynamicVerification.DynamicVerification"

# Imports appended to an INLINE-mode file (the L2 is generated in-place; we only
# add the umbrella on top of whatever L2 codegen already imports).
_LAYER3_IMPORTS: list[str] = [_UMBRELLA_IMPORT]


# ───────────────────────────────────────────────────────────────────────────
# IR normalisation: legacy SWE/ELAIP shapes → unified fields
# ───────────────────────────────────────────────────────────────────────────


def _norm_layer2_ref(ir: dict) -> dict:
    """Resolve the Layer-2 reference into a uniform dict:
        {mode, layer2_module, open_namespace, semantic_graph_def,
         goal_spec_def, prefix, workflow}
    handling the unified `layer2_ref`, the legacy SWE inline `workflow`+`prefix`,
    and the ELAIP `layer2_ref` (which lacks open_namespace)."""
    ref = dict(ir.get("layer2_ref") or {})
    # Legacy SWE inline IR: workflow embedded at top level, prefix at top level.
    if "workflow" in ir and "mode" not in ref:
        ref.setdefault("mode", "inline")
        ref.setdefault("workflow", ir["workflow"])
        ref.setdefault("prefix", ir.get("prefix"))
    prefix = ref.get("prefix") or ir.get("prefix")
    mode = ref.get("mode") or ("inline" if ref.get("workflow") is not None else "import")

    semantic_graph_def = ref.get("semantic_graph_def") or (f"{prefix}SemanticGraph" if prefix else None)
    goal_spec_def = ref.get("goal_spec_def") or (f"{prefix}_goalSpec" if prefix else None)

    open_ns = ref.get("open_namespace")
    if open_ns is None and mode == "import":
        # ELAIP IR stores layer2_module but not the namespace to open; the
        # module's namespace is conventionally `AgenticKernel.<module tail>`.
        module = ref.get("layer2_module") or ""
        tail = module.split(".")[-1] if module else ""
        open_ns = f"AgenticKernel.{tail}" if tail else None

    return {
        "mode": mode,
        "layer2_module": ref.get("layer2_module"),
        "open_namespace": open_ns,
        "semantic_graph_def": semantic_graph_def,
        "goal_spec_def": goal_spec_def,
        "prefix": prefix,
        "workflow": ref.get("workflow") if mode == "inline" else None,
    }


def _norm_step_entries(ir: dict) -> list[tuple[str, str]]:
    """`step_entries` = list of (l2_node_name, trajectory_step_id). Prefer an
    explicit `step_entries`; otherwise derive from `dyn_nodes` (completed only).
    Both the SWE and ELAIP dyn_nodes carry `trajectory_step_name`/`_id`."""
    raw = ir.get("step_entries")
    if raw:
        return [(str(a), str(b)) for (a, b) in raw]
    out: list[tuple[str, str]] = []
    for d in ir.get("dyn_nodes", []) or []:
        if d.get("execution_status") != "completed":
            continue
        sid = d.get("trajectory_step_id") or ""
        name = d.get("trajectory_step_name") or d.get("node_name") or ""
        if name and sid:
            out.append((str(name), str(sid)))
    return out


def _norm_exec_state(ir: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for entry in ir.get("exec_state", []) or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 1:
            continue
        name = entry[0]
        raw = entry[1] if len(entry) > 1 else ""
        out.append((str(name), raw if raw is not None else ""))
    return out


def _norm_injections(ir: dict) -> list[dict]:
    """Normalise an `llm_injections` list. Accepts both the flat schema
    (top-level holds/confidence/llm_explanation, the ELAIP annotator form) and
    the nested `judgement.*` schema, with the flat one taking precedence."""
    out: list[dict] = []
    for inj in ir.get("llm_injections", []) or []:
        judge = inj.get("judgement") or {}
        out.append({
            "step_name": inj.get("step_name") or inj.get("stepName") or "",
            "var_name": inj.get("var_name") or inj.get("varName") or "",
            "holds": bool(inj.get("holds", judge.get("holds", True))),
            "confidence": float(inj.get("confidence", judge.get("confidence", 1.0))),
            "llm_explanation": (inj.get("llm_explanation") or inj.get("explanation")
                                or judge.get("llmExplanation") or judge.get("explanation") or ""),
            "node_instruction": (inj.get("node_instruction")
                                 or judge.get("nodeInstruction") or ""),
        })
    return out


# ───────────────────────────────────────────────────────────────────────────
# The shared V2 Layer-3 tail (identical for SWE & ELAIP, import & inline)
# ───────────────────────────────────────────────────────────────────────────


def _render_block(name_eq: str, items: list[str], indent: str = "    ") -> list[str]:
    """`def <name_eq>` followed by a bracketed list of pre-rendered items."""
    lines = [name_eq]
    if not items:
        lines.append("  []")
        return lines
    if len(items) == 1:
        lines.append(f"  [ {items[0]} ]")
        return lines
    lines.append(f"  [ {items[0]},")
    for it in items[1:-1]:
        lines.append(f"{indent}{it},")
    lines.append(f"{indent}{items[-1]} ]")
    return lines


def _render_injection(inj: dict) -> str:
    holds = "true" if inj["holds"] else "false"
    conf = fmt_float(inj["confidence"])
    body = ("{ stepName := " + lean_str(inj["step_name"]) + ", varName := " + lean_str(inj["var_name"]) + "\n"
            "      judgement := makeLLMJudgementResult\n"
            f"        (holds := {holds}) (confidence := {conf})\n"
            "        (llmExplanation := " + lean_str(inj["llm_explanation"]) + ")")
    if inj.get("node_instruction"):
        body += "\n        (nodeInstruction := " + lean_str(inj["node_instruction"]) + ")"
    body += " }"
    return body


def render_l3_v2_tail(*, semantic_graph_def: str, goal_spec_def: str | None,
                      benchmark: str, report_path: str | None, event_log_path: str,
                      step_entries: list[tuple[str, str]], exec_state: list[tuple[str, str]],
                      llm_injections: list[dict], label: str = "",
                      suffix: str = "", extra_opens=(), var_truncate: int = 16384) -> list[str]:
    """Emit the V2 Layer-3 tail: opens + paths + stepEntries + execState +
    stepIdMap + dynamicGraph + llmInjections + the #eval! driver. Shared by both
    benchmarks and both import/inline modes — it only references
    `<semantic_graph_def>` (in scope either way) and the surface."""
    is_swe = (benchmark == "swe")
    sfx = suffix or ""
    report_name = f"reportPath{sfx}"
    event_name = f"eventLogPath{sfx}"
    entries_name = f"stepEntries{sfx}"
    state_name = f"execState{sfx}"
    map_name = f"stepIdMap{sfx}"
    graph_name = f"dynamicGraph{sfx}"
    inj_name = f"llmInjections{sfx}"
    lbl = label or "layer-3"

    L: list[str] = []
    L.append("open AgenticKernel.Dyn")
    for op in extra_opens:
        if op:
            L.append(f"open {op}")
    L.append("")

    if is_swe:
        if not report_path:
            raise ValueError("benchmark 'swe' requires a report_path (Tool channel)")
        L.append(f"def {report_name} : System.FilePath :=")
        L.append(f"  {lean_str(report_path)}")
    L.append(f"def {event_name} : System.FilePath :=")
    L.append(f"  {lean_str(event_log_path)}")
    L.append("")

    # stepEntries : (l2_node_name, trajectory_step_id) — resolved by name.
    ent_items = [f"({lean_str(n)}, {lean_str(s)})" for (n, s) in step_entries]
    L.append("/- Trajectory pairings: (l2_node_name, trajectory_step_id) — resolved by name. -/")
    L.extend(_render_block(f"def {entries_name} : List (String × String) :=", ent_items))
    L.append("")

    # execState
    es_items = [f"({lean_str(v)}, {lean_str(truncate_for_lean(raw, var_truncate))})"
                for (v, raw) in exec_state]
    L.extend(_render_block(f"def {state_name} : NodeExecutionState := makeExecutionState", es_items))
    L.append("")

    # stepIdMap + dynamicGraph via the by-name builders (no off-by-one).
    L.append(f"def {map_name} : StepIdMap :=")
    L.append(f"  ElaipBench.buildStepIdMapByName {semantic_graph_def} {entries_name}")
    L.append("")
    L.append(f"def {graph_name} : DynamicVerificationGraph :=")
    L.append(f"  ElaipBench.buildDynamicGraphByName {semantic_graph_def} {state_name} {entries_name}")
    L.append("")

    # llmInjections — the only LLM-written block.
    inj_items = [_render_injection(i) for i in llm_injections]
    L.append("/- Per-step LLM judgements (the only LLM-written block). -/")
    L.extend(_render_block(f"def {inj_name} : List PerPredicateLLMInjection :=", inj_items))
    L.append("")

    # #eval! driver — three methods (Lean ∧ Tool ∧ LLM via authority routing)
    # are composed inside analyzeAllSteps/renderFullReport.
    L.append("#eval! (do")
    if is_swe:
        banner = (f's!"{lean_escape_in_interp(lbl)} — report.json resolved=' "{report.resolved}"
                  ", F2P fail={report.testsStatus.failToPass.failure.length}"
                  ', P2P fail={report.testsStatus.passToPass.failure.length}"')
        L.append(f"  let report ← SWEBench.InstanceReport.loadFromFile {report_name}")
        L.append(f"  IO.println {banner}")
        L.append(f"  let trace ← ExecutionTrace.loadEventLog {event_name}")
        L.append(f"  let rules := SWEBench.rulesFromReport report")
    else:
        L.append(f"  let trace ← ExecutionTrace.loadEventLog {event_name}")
        L.append(f"  let rules := ElaipBench.rulesFromState {state_name}")
    L.append(f"  let analyses := analyzeAllSteps {graph_name} trace {map_name} rules {inj_name}")
    L.append(f"  IO.println (renderFullReport {graph_name} trace analyses "
             f"(stepIdMap := {map_name}) (label := {lean_str(lbl)}))")
    L.append(f"  IO.println (layer3ToJson {graph_name} trace analyses "
             f"(stepIdMap := {map_name}) (label := {lean_str(lbl)})).compress")
    L.append("  : IO Unit)")
    return L


def lean_escape_in_interp(s: str) -> str:
    """Escape a literal fragment placed inside a Lean s!"..." interpolation
    (so embedded quotes/backslashes don't break the string; braces are left
    alone because callers only pass plain labels)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ───────────────────────────────────────────────────────────────────────────
# Top-level: assemble a complete .lean from a unified IR dict
# ───────────────────────────────────────────────────────────────────────────


def _resolve_meta(ir: dict, l2: dict) -> tuple[str, str]:
    """Return (namespace, label). Namespace = AgenticKernel.<plan>_<suffix>_v2
    (used only in import mode; inline mode keeps the inlined `AgenticKernel`)."""
    plan = ir.get("plan_name") or l2.get("prefix") or "plan"
    suffix = ir.get("namespace_suffix")
    if not suffix:
        inst = ir.get("instance_id") or ir.get("question_id") or ""
        suffix = lean_safe_ident(inst) if inst else "inst"
    ns = f"AgenticKernel.{lean_safe_ident(plan)}_{lean_safe_ident(suffix)}_v2"
    label = (ir.get("label") or ir.get("banner_title") or ir.get("instance_id")
             or ir.get("question_id") or plan)
    return ns, str(label)


def _benchmark_of(ir: dict) -> str:
    b = ir.get("benchmark")
    if b in ("swe", "elaip"):
        return b
    kind = ir.get("ir_kind") or ""
    if kind == "elaip_layer3" or "question_id" in ir:
        return "elaip"
    # legacy SWE layer3 IR and the unified default
    return "swe" if (ir.get("report_path") or kind == "layer3") else "elaip"


def generate_layer3_v2_lean(ir: dict) -> str:
    """Generate a complete Layer-3 Lean source from a (unified or legacy)
    IR dict. Import mode emits a standalone file; inline mode delegates the L2
    emission to TaskPlanToLean_v2 and appends the V2 tail."""
    l2 = _norm_layer2_ref(ir)
    benchmark = _benchmark_of(ir)
    if not l2["semantic_graph_def"]:
        raise ValueError("IR does not resolve a semantic_graph_def "
                         "(need layer2_ref.semantic_graph_def or a prefix)")

    event_log_path = ir.get("event_log_path") or ""
    report_path = ir.get("report_path")
    step_entries = _norm_step_entries(ir)
    exec_state = _norm_exec_state(ir)
    injections = _norm_injections(ir)
    ns, label = _resolve_meta(ir, l2)
    header_comment = ir.get("header_comment")

    if l2["mode"] == "inline":
        return _generate_inline(ir, l2, benchmark, report_path, event_log_path,
                                step_entries, exec_state, injections, label)

    # ── import mode ────────────────────────────────────────────────────────
    if not l2["layer2_module"]:
        raise ValueError("import mode requires layer2_ref.layer2_module")
    parts: list[str] = []
    if header_comment:
        parts.append("/- " + header_comment + " -/")
        parts.append("")
    parts.extend(_STATIC_IMPORTS)
    parts.append(f"import {l2['layer2_module']}")
    parts.append(_UMBRELLA_IMPORT)
    parts.append("")
    parts.append(f"namespace {ns}")
    parts.append("")

    extra_opens = [l2["open_namespace"]] if l2["open_namespace"] else []
    tail = render_l3_v2_tail(
        semantic_graph_def=l2["semantic_graph_def"],
        goal_spec_def=l2["goal_spec_def"],
        benchmark=benchmark, report_path=report_path, event_log_path=event_log_path,
        step_entries=step_entries, exec_state=exec_state, llm_injections=injections,
        label=label, suffix="", extra_opens=extra_opens,
        var_truncate=int(ir.get("var_truncate", 16384)),
    )
    parts.extend(tail)
    parts.append("")
    parts.append(f"end {ns}")
    parts.append("")
    return "\n".join(parts)


def _generate_inline(ir, l2, benchmark, report_path, event_log_path,
                     step_entries, exec_state, injections, label) -> str:
    """Inline mode: the transfer pipeline has no importable L2 module, so we emit
    the new-format Layer-2 in-place (via TaskPlanToLean_v2) plus the V2 tail.
    Imported lazily so import-mode callers (e.g. ELAIP) never load the heavy
    Layer-2 codegen."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import TaskPlanToLean as T            # noqa: E402
    import TaskPlanToLean_v2 as T2         # noqa: E402

    prefix = l2["prefix"]
    if not prefix:
        raise ValueError("inline mode requires a prefix")
    workflow_dict = l2["workflow"]
    wf = T.WorkflowIR.from_dict(workflow_dict)
    # Attach the v2 info-flow fields present in the inlined workflow dict.
    raw_nodes = {rn["id"]: rn for rn in workflow_dict.get("nodes", [])}
    for n in wf.nodes:
        rn = raw_nodes.get(n.id, {})
        n._info_requires = rn.get("info_requires") or []
        n._produces_variable_info = rn.get("produces_variable_info") or []
        n._produces_context_info = rn.get("produces_context_info") or []
    wf._param_produces_variable_info = workflow_dict.get("param_produces_variable_info") or []
    wf._expected_info_sound = bool(workflow_dict.get("expected_info_sound", True))

    tail = render_l3_v2_tail(
        semantic_graph_def=l2["semantic_graph_def"],
        goal_spec_def=l2["goal_spec_def"],
        benchmark=benchmark, report_path=report_path, event_log_path=event_log_path,
        step_entries=step_entries, exec_state=exec_state, llm_injections=injections,
        label=label, suffix=str(ir.get("suffix") or ""), extra_opens=(),
        var_truncate=int(ir.get("var_truncate", 16384)),
    )
    if ir.get("header_comment"):
        tail = ["", "/-!", ir["header_comment"], "-/", ""] + tail
    return T2.generate_layer2_lean_v2(wf, prefix,
                                      extra_imports=_LAYER3_IMPORTS,
                                      extra_tail=tail)


# ───────────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ir", required=True, help="Path to a Layer-3 IR JSON "
                   "(unified `layer3_v2`, legacy SWE `layer3`, or ELAIP `elaip_layer3`)")
    p.add_argument("--out", required=True, help="Output .lean path")
    p.add_argument("--var-truncate", type=int, default=16384,
                   help="Per-variable raw-string truncation (default 16384 chars)")
    args = p.parse_args()

    ir_path = Path(args.ir).resolve()
    if not ir_path.exists():
        print(f"ERROR: IR JSON not found: {ir_path}", file=sys.stderr)
        sys.exit(2)
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    ir.setdefault("var_truncate", args.var_truncate)

    code = generate_layer3_v2_lean(ir)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(code, encoding="utf-8")
    n_lines = code.count("\n") + 1
    print(f"OK: Layer-3 V2 Lean -> {out_path} ({n_lines} lines, "
          f"benchmark={_benchmark_of(ir)}, mode={_norm_layer2_ref(ir)['mode']})")


if __name__ == "__main__":
    main()
