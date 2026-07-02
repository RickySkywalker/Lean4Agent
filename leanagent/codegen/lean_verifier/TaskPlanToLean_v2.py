#!/usr/bin/env python3
"""
TaskPlanToLean_v2.py — Parsed Task IR (JSON) → Lean code generator, **v2 / Solution-2 idiom**.

This is the v2 of `TaskPlanToLean.py`. It emits the restructured Layer-2 format:

  * each semantic node carries THREE separate record groups —
      (1) variable-level  : precondVariables / postcondVariables
      (2) information flow : infoRequires / producesVariableInfo / producesContextInfo
      (3) graph-level      : graphContributions / graphVerifications / graphImplicitRetries
    (NO `markSubGoal*` / `markInfoContent` / `markStep*` sentinels in postconditions),
  * sub-goal names are typed `SubGoalName` constants declared once in a per-plan
    `namespace <prefix>.SG`, referenced by both the node graph-fields and the goalSpec,
  * the `GoalSpecification` is embedded in the `SemanticWorkflowGraph.goalSpec` field
    (defined before the graph), and
  * ONE `verifyWorkflowReport` #eval plus `hoareSound` / `infoSound` theorems replace
    the old per-channel STEP 6 / 6½ / 7 evals.

It REUSES the low-level IR from `TaskPlanToLean.py` (PredicateIR, VarPredicateIR,
TypedVar, EdgeIR, GraphPredicateKeyIR, WorkflowIR.from_dict, the Layer-1 structural
emitter `_gen_structural`, and the Layer-3 codegen), and only overrides the Layer-2
semantic emission.

v2 IR JSON schema = the existing Layer-2 IR schema PLUS optional per-node fields:
    "info_requires":          ["atom", ...]
    "produces_variable_info": [{"var_name": "v", "atoms": ["atom", ...]}, ...]
    "produces_context_info":  ["atom", ...]
and an optional top-level "param_produces_variable_info" (same shape) and
"expected_info_sound": bool. The existing "sub_goal_contributions" /
"sub_goal_verifications" / "implicit_retries" / "goal_spec" fields are used as-is.

CLI:
  python TaskPlanToLean_v2.py --ir <layer2_ir.json> --prefix <p> --out <file.lean>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import TaskPlanToLean as T  # low-level IR + L1 structural + L3 codegen


# ---------------------------------------------------------------------------
# sub-goal name constants
# ---------------------------------------------------------------------------

def _sg_ident(name: str) -> str:
    """A valid Lean identifier for a sub-goal name (snake_case names pass through)."""
    ident = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not ident or not re.match(r'[A-Za-z_]', ident[0]):
        ident = "sg_" + ident
    return ident


def _collect_subgoal_names(ir: T.WorkflowIR) -> list[str]:
    """Every sub-goal name used anywhere (node graph-fields ∪ goalSpec), ordered, deduped."""
    names: list[str] = []
    seen: set[str] = set()

    def add(nm: str) -> None:
        if nm not in seen:
            seen.add(nm)
            names.append(nm)

    for n in ir.nodes:
        for lst in (n.sub_goal_contributions, n.sub_goal_verifications, n.implicit_retries):
            for tag in (lst or []):
                add(tag.sub_goal_name)
    if ir.goal_spec is not None:
        for sg in ir.goal_spec.sub_goals:
            add(sg.name)
    return names


def _emit_sg_namespace(ir: T.WorkflowIR, prefix: str) -> list[str]:
    names = _collect_subgoal_names(ir)
    if not names:
        return []
    lines = [
        "/- FIX #3: typed sub-goal identities — declared once, referenced (not re-typed)",
        "   in the node graph-fields and the GoalSpecification. -/",
        f"namespace {prefix}.SG",
    ]
    for nm in names:
        lines.append(f'  def {_sg_ident(nm)} : SubGoalName := ⟨"{nm}"⟩')
    lines.append(f"end {prefix}.SG")
    lines.append(f"open {prefix}.SG")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# per-node info / graph record fields (new format)
# ---------------------------------------------------------------------------

def _info_atom_list(atoms) -> str:
    return ", ".join(f'info "{a}"' for a in (atoms or []))


def _var_info_list(entries) -> str:
    # entries: list of {"var_name": str, "atoms": [str]}
    parts = []
    for e in (entries or []):
        atoms = ", ".join(f'"{a}"' for a in e.get("atoms", []))
        parts.append(f'varInfo "{e["var_name"]}" [{atoms}]')
    return ", ".join(parts)


def _sg_ref_list(tags) -> str:
    return ", ".join(_sg_ident(t.sub_goal_name) for t in (tags or []))


def _node_record_field_lines(n: T.NodeIR) -> list[str]:
    """Emit the information-flow and graph-level record-group fields for a node,
    omitting any that are empty. New attrs are attached to the NodeIR by the loader."""
    lines: list[str] = []
    info_requires = getattr(n, "_info_requires", None)
    produces_var = getattr(n, "_produces_variable_info", None)
    produces_ctx = getattr(n, "_produces_context_info", None)
    if info_requires:
        lines.append(f"  infoRequires := [{_info_atom_list(info_requires)}]")
    if produces_var:
        lines.append(f"  producesVariableInfo := [{_var_info_list(produces_var)}]")
    if produces_ctx:
        lines.append(f"  producesContextInfo := [{_info_atom_list(produces_ctx)}]")
    if n.sub_goal_contributions:
        lines.append(f"  graphContributions := [{_sg_ref_list(n.sub_goal_contributions)}]")
    if n.sub_goal_verifications:
        lines.append(f"  graphVerifications := [{_sg_ref_list(n.sub_goal_verifications)}]")
    if n.implicit_retries:
        lines.append(f"  graphImplicitRetries := [{_sg_ref_list(n.implicit_retries)}]")
    return lines


def _collect_var_predicate_exprs(extra, vars_) -> list[str]:
    """Variable-level predicate Lean exprs only — extra (VarPredicateIR entries,
    skipping InfoContentIR) + reads/writes predicates, deduped. (The old
    markInfoContent/markStep/marker emission is dropped: info & graph data now
    live in dedicated node fields.)"""
    exprs: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in (extra or []):
        if isinstance(item, T.VarPredicateIR):
            key = (item.var_name, item.predicate.kind)
            if key not in seen:
                seen.add(key)
                exprs.append(item.to_lean())
        # InfoContentIR (old markInfoContent aspect) → intentionally skipped.
    for v in vars_:
        for vp in v.to_var_predicates():
            key = (vp.var_name, vp.predicate.kind)
            if key not in seen:
                seen.add(key)
                exprs.append(vp.to_lean())
    return exprs


def _vp_exprs(lst) -> str:
    """Join only the variable-level predicates of a heterogeneous list, dropping
    any InfoContentIR (legacy `markInfoContent` aspects no longer ride the Hoare
    chain — information lives in the node info fields now)."""
    return ", ".join(p.to_lean() for p in (lst or []) if isinstance(p, T.VarPredicateIR))


def _gen_semantic_node_v2(n: T.NodeIR, prefix: str) -> list[str]:
    """Emit a SemanticWorkflowNode / SemanticLoopNode / SemanticConditionalNode in
    the new node-field idiom."""
    lines: list[str] = []
    pre_exprs = _collect_var_predicate_exprs(n.precond_extra, n.reads)
    post_exprs = _collect_var_predicate_exprs(n.postcond_extra, n.writes)
    pre_s = ", ".join(pre_exprs)
    post_s = ", ".join(post_exprs)
    fields = _node_record_field_lines(n)

    lines.append(f'-- Semantic Node {n.id}: {n.step_type} "{n.name}"')

    if n.is_conditional:
        lines.append(f"def {prefix}_condNode{n.id} : SemanticConditionalNode := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        lines.extend(fields)
        lines.append(f"  thenTargetId := {prefix}_nodeId{n.then_target_id}")
        lines.append(f"  elseTargetId := {prefix}_nodeId{n.else_target_id}")
        lines.append(f"  thenPostcondVariables := [{_vp_exprs(n.then_postcond)}]")
        lines.append(f"  elsePostcondVariables := [{_vp_exprs(n.else_postcond)}]")
        lines.append(f"}}")
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {prefix}_condNode{n.id}.toSemanticWorkflowNode")

    elif n.is_loop:
        is_fe = n.iteration_var is not None
        st = "SemanticForEachLoopNode" if is_fe else "SemanticLoopNode"
        lines.append(f"def {prefix}_loopNode{n.id} : {st} := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        lines.extend(fields)
        lines.append(f"  loopInvariant := [{_vp_exprs(n.loop_invariant)}]")
        tk = n.termination_kind or "finiteCondition"
        if tk == "finiteCondition":
            vs = ", ".join(f'"{v}"' for v in (n.termination_vars or []))
            lines.append(f"  terminationSpec := .finiteCondition [{vs}]")
        elif tk == "llmControlledExit":
            lines.append(f'  terminationSpec := .llmControlledExit ⟨{n.termination_exit_node}⟩ "{n.termination_sentinel}"')
        elif tk == "externalTermination":
            lines.append(f'  terminationSpec := .externalTermination "{n.termination_mechanism}"')
        elif tk == "allowUnbounded":
            lines.append(f'  terminationSpec := .allowUnbounded "{n.termination_justification}"')
        xp = _vp_exprs(n.exit_postcond)
        if xp:
            lines.append(f"  exitPostconditions := [{xp}]")
        if is_fe:
            lines.append(f'  iterationVar := "{n.iteration_var}"')
        if n.loop_executes_at_least_once:
            lines.append(f"  executesAtLeastOnce := true")
        lines.append(f"}}")
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {prefix}_loopNode{n.id}.toSemanticWorkflowNode")

    else:
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        lines.extend(fields)
        lines.append(f"}}")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# goal spec (typed names), param node (with param info), semantic graph, report
# ---------------------------------------------------------------------------

def _gen_goal_spec_v2(ir: T.WorkflowIR, prefix: str) -> list[str]:
    assert ir.goal_spec is not None
    gs = ir.goal_spec
    goal_esc = gs.original_goal.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    lines = [f"def {prefix}_goalSpec : GoalSpecification := {{",
             f'  originalGoal := "{goal_esc}"',
             f"  subGoals := ["]
    sub_lines = []
    for sg in gs.sub_goals:
        desc = sg.description.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        rgp = ", ".join(k.to_lean() for k in sg.required_graph_predicates)
        sub_lines.append(
            f"    {{ name := {_sg_ident(sg.name)}\n"
            f'      variableName := "{sg.variable_name}"\n'
            f"      requiredPredicate := {sg.required_predicate.to_lean()}\n"
            f'      description := "{desc}"\n'
            f"      requiredGraphPredicates := [{rgp}] }}"
        )
    lines.append(",\n".join(sub_lines))
    lines.append("  ]")
    lines.append("}")
    lines.append("")
    return lines


def _gen_param_node_v2(ir: T.WorkflowIR, prefix: str) -> list[str]:
    lines = [f"def {prefix}_paramNode : SemanticWorkflowNode := {{",
             f'  baseNode := {{ id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }}',
             f"  precondVariables := []"]
    pp = ",\n    ".join(p.to_lean() for p in (ir.param_postcond or []))
    lines.append(f"  postcondVariables := [\n    {pp}\n  ]")
    param_info = getattr(ir, "_param_produces_variable_info", None)
    if param_info:
        lines.append(f"  producesVariableInfo := [{_var_info_list(param_info)}]")
    lines.append("}")
    lines.append("")
    return lines


def _gen_semantic_graph_v2(ir: T.WorkflowIR, prefix: str) -> list[str]:
    sn = ", ".join(f"{prefix}_semNode{n.id}" for n in ir.nodes)
    ln = ", ".join(f"{prefix}_loopNode{n.id}" for n in ir.nodes if n.is_loop)
    cn = ", ".join(f"{prefix}_condNode{n.id}" for n in ir.nodes if n.is_conditional)
    lines = [f"def {prefix}SemanticGraph : SemanticWorkflowGraph := {{",
             f"  baseGraph := {prefix}Graph",
             f"  paramNode := {prefix}_paramNode",
             f"  semanticNodes := [{sn}]",
             f"  loopNodes := [{ln}]",
             f"  conditionalNodes := [{cn}]"]
    if ir.goal_spec is not None:
        lines.append(f"  goalSpec := {prefix}_goalSpec")
    lines.append(f"  specInvariant := by decide")
    lines.append("}")
    lines.append("")
    return lines


def _gen_unified_report_v2(ir: T.WorkflowIR, prefix: str) -> list[str]:
    thm = ir.name.replace("-", "_")
    hoare_val = "true" if ir.expected_semantically_sound else "false"
    info_val = "true" if getattr(ir, "_expected_info_sound", True) else "false"
    lines = ["/-",
             "=" * 72,
             "UNIFIED LAYER-2 VERIFICATION  (variables + information flow + goal coverage)",
             "=" * 72,
             "-/",
             "",
             f'#eval IO.println ({prefix}SemanticGraph.verifyWorkflowReport (label := "{ir.name}"))',
             "",
             f"theorem {thm}_hoare_sound : ({prefix}SemanticGraph.verifyWorkflow).hoareSound = {hoare_val} := by native_decide"]
    if ir.goal_spec is not None:
        lines.append(f"theorem {thm}_info_sound : ({prefix}SemanticGraph.verifyWorkflow).infoSound = {info_val} := by native_decide")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# v2 L2 semantic block (replaces _gen_semantic + _gen_goal_spec), placed AFTER
# the base graph: goalSpec → paramNode → SemanticGraph(embedded) → unified report.
# ---------------------------------------------------------------------------

def _gen_semantic_v2(ir: T.WorkflowIR, prefix: str, registry_name: str) -> list[str]:
    lines: list[str] = []
    if ir.goal_spec is not None:
        lines.extend(_gen_goal_spec_v2(ir, prefix))
    lines.extend(_gen_param_node_v2(ir, prefix))
    lines.extend(_gen_semantic_graph_v2(ir, prefix))
    lines.extend(_gen_unified_report_v2(ir, prefix))
    return lines


# ---------------------------------------------------------------------------
# loader: attach v2 info fields to the parsed WorkflowIR
# ---------------------------------------------------------------------------

def load_workflow_v2(ir_dict: dict) -> T.WorkflowIR:
    ir = T.WorkflowIR.from_dict(ir_dict)
    raw_nodes = {rn["id"]: rn for rn in ir_dict.get("nodes", [])}
    for n in ir.nodes:
        rn = raw_nodes.get(n.id, {})
        n._info_requires = rn.get("info_requires") or []
        n._produces_variable_info = rn.get("produces_variable_info") or []
        n._produces_context_info = rn.get("produces_context_info") or []
    ir._param_produces_variable_info = ir_dict.get("param_produces_variable_info") or []
    ir._expected_info_sound = bool(ir_dict.get("expected_info_sound", True))
    return ir


# ---------------------------------------------------------------------------
# top-level generator (reuses T.generate_lean for L1 via monkey-patched L2 hooks)
# ---------------------------------------------------------------------------

def generate_layer2_lean_v2(ir: T.WorkflowIR, prefix: str,
                            extra_imports=None, extra_tail=None) -> str:
    """Emit the full new-format Layer-2 Lean. Reuses T.generate_lean's L1 emission
    (imports/header/WorkflowNode defs/base graph/structural theorems) by swapping in
    the v2 semantic emitters; injects the per-plan SG namespace right after
    `namespace AgenticKernel`."""
    sg_imports = list(extra_imports or [])
    saved = (T._gen_semantic_node, T._gen_semantic, T._gen_goal_spec)
    T._gen_semantic_node = _gen_semantic_node_v2
    T._gen_semantic = _gen_semantic_v2
    T._gen_goal_spec = lambda ir, prefix: []  # folded into _gen_semantic_v2
    try:
        src = T.generate_lean(ir, prefix, extra_imports=sg_imports, extra_tail=extra_tail)
    finally:
        T._gen_semantic_node, T._gen_semantic, T._gen_goal_spec = saved

    # Inject the SG namespace right after the first `namespace AgenticKernel` line,
    # so the SubGoalName constants are in scope for the semNode graph-fields below.
    sg_block = "\n".join(_emit_sg_namespace(ir, prefix))
    if sg_block:
        src = src.replace("namespace AgenticKernel\n",
                          "namespace AgenticKernel\n\n" + sg_block + "\n", 1)
    return src


# ---------------------------------------------------------------------------
# Layer 3 (dynamic verification): new-format L2 + the (format-agnostic) L3 tail
# ---------------------------------------------------------------------------

def generate_layer3_lean_v2(layer3_ir: T.Layer3IR, raw_workflow: dict | None = None) -> str:
    """Self-contained Layer-3 Lean: the new-format Layer-2 (this module) with
    the dynamic-verification tail appended (targets
    `AgentVerifier/DynamicVerification/`, namespace `AgenticKernel.Dyn`).

    The V2 tail is produced by `layer3_v2_codegen.render_l3_v2_tail` — the same
    emitter the ELAIP codegen and the standalone import-mode codegen use — so the
    SWE and ELAIP json→Layer-3 paths stay in lock-step. It references the L2
    `SemanticGraph` by name via the by-name builders
    (`ElaipBench.buildStepIdMapByName` / `buildDynamicGraphByName`), so it is
    format-agnostic and works whether the L2 is inlined (here) or imported.

    NOTE: this replaces the legacy behaviour, which spliced the legacy
    `TaskPlanToLean._gen_layer3_tail` (old `AgentVerifier.DynamicVerification.*`
    imports + the old `renderFullReport SemanticGraph goalSpec analyses execState`
    signature). The legacy V1 generator (`TaskPlanToLean.generate_layer3_lean` /
    `_gen_layer3_tail`) and the V1 dynamic layer have since been removed — this is
    the only path."""
    import layer3_v2_codegen as L3V2  # lazy: avoids any import cycle

    workflow_dict = raw_workflow if raw_workflow is not None else layer3_ir.workflow.to_dict()
    # Derive (l2_node_name, trajectory_step_id) entries from the dyn_nodes the
    # IR-init produced (resolves them against the graph by name).
    dyn_nodes = [d.to_dict() for d in layer3_ir.dyn_nodes]
    label = (layer3_ir.banner_title
             or f"{layer3_ir.workflow.name}{layer3_ir.suffix or ''}")
    unified_ir = {
        "ir_kind": "layer3_v2",
        "benchmark": "swe",
        "label": label,
        "suffix": layer3_ir.suffix or "",
        "layer2_ref": {"mode": "inline", "prefix": layer3_ir.prefix,
                       "workflow": workflow_dict},
        "report_path": layer3_ir.report_path,
        "event_log_path": layer3_ir.event_log_path,
        "dyn_nodes": dyn_nodes,
        "exec_state": [[v, raw] for (v, raw) in layer3_ir.exec_state],
        "llm_injections": [i.to_dict() for i in layer3_ir.llm_injections],
        "header_comment": layer3_ir.header_comment,
    }
    return L3V2.generate_layer3_v2_lean(unified_ir)


def main():
    p = argparse.ArgumentParser(description="Generate new-format Layer-2 (or Layer-3) Lean from a v2 IR JSON.")
    p.add_argument("--ir", required=True)
    p.add_argument("--prefix", default="")
    p.add_argument("--out", default="")
    args = p.parse_args()

    ir_dict = json.loads(Path(args.ir).read_text(encoding="utf-8"))
    if ir_dict.get("ir_kind") == "layer3":
        layer3 = T.Layer3IR.from_dict(ir_dict)
        src = generate_layer3_lean_v2(layer3, raw_workflow=ir_dict.get("workflow"))
        kind, nnodes, prefix = "Layer-3", len(layer3.workflow.nodes), layer3.prefix
    else:
        prefix = args.prefix or ir_dict.get("prefix")
        if not prefix:
            print("ERROR: no --prefix and no 'prefix' field in IR", file=sys.stderr); return
        ir = load_workflow_v2(ir_dict)
        src = generate_layer2_lean_v2(ir, prefix)
        kind, nnodes = "Layer-2", len(ir.nodes)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(src, encoding="utf-8")
        print(f"OK: new-format {kind} Lean -> {args.out} ({nnodes} nodes, prefix={prefix!r})")
    else:
        sys.stdout.write(src)


if __name__ == "__main__":
    main()
