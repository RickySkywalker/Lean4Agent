#!/usr/bin/env python3
"""
build_layer2_ir.py — One-shot generator of ELAIP-Bench Layer-2 IR JSONs.

For each ELAIP plan YAML (passed_workflow_1..6, failed_workflow_1..6 + the baseline plan),
walk the workflow tree, flatten nested if/while/switch/for_each blocks into a
linear list of executable `.step` nodes, attach the canonical ELAIP
postcondition predicates per `save_as` variable, and emit a JSON IR that
downstream Layer-3 tooling consumes.

The output schema is deliberately ELAIP-specific (rather than mirroring the
SWE WorkflowIR shape) — ELAIP Layer-2 `.lean` files are hand-written, not
generated from this IR, so we don't need to round-trip through TaskPlanToLean.

NEW FORMAT (Solution 2): the hand-written Layer-2 `.lean` files now use the
restructured node-field idiom — graph contributions/verifications/retries and
information flow live in dedicated `SemanticWorkflowNode` fields (NOT
`markSubGoal*` postcond markers), the goal spec is embedded in the graph's
`goalSpec` field, and one `verifyWorkflowReport` replaces the old per-channel
evals. When authoring or regenerating these files, follow
`LAYER2_NEW_FORMAT.md` in this directory. `goal_spec_def` / `semantic_graph_def`
below stay valid (the goal spec is also kept as a top-level def for Layer-3).
To mechanically port an old-format file, use
`leanagent/tools/port_to_new_layer2.py`.

Schema:
{
  "ir_kind": "elaip_layer2",
  "plan_name": "passed_workflow_1",
  "plan_kind": "best" | "worst" | "baseline",
  "yaml_path": "<repo-relative path>",
  "layer2_module": "TestVerifications.«ELAIP-Bench_selscted».best.<plan>_layer2_v2",
  "prefix": "passed_workflow_1",
  "semantic_graph_def": "passed_workflow_1SemanticGraph",
  "goal_spec_def": "passed_workflow_1_goalSpec",
  "name": "elaipbench_agent_passed_workflow_1",
  "goal": "...",
  "parameters": [
    {"name": "...", "predicates": [{"kind": "isNonEmptyString"}, ...]},
    ...
  ],
  "nodes": [
    {
      "id": 0,
      "name": "skim_paper_overview",
      "step_type": "task" | "step" | "discover" | "for_each" | "while" | "if"
                  | "switch" | "set_variable" | "increment" | "synthesize"
                  | "finalize_*",
      "save_as": "paper_overview",
      "reads_templates": ["paper_content"],
      "instruction_excerpt": "<first 500 chars>",
      "postconds": [
        {"var_name": "paper_overview", "predicate_kind": "nameExists",
         "semantic_description": "..."},
        ...
      ],
      "branch_path": ["MA-MCQ"],     # absent for top-level steps
      "loop_iter": null,             # for_each / while bodies — placeholder
      "executable": true             # set_variable/increment are NOT executable steps
    },
    ...
  ],
  "edges": [
    {"from": 0, "to": 1, "kind": "seq"},
    ...
  ],
  "entry": 0,
  "exits": [N, ...]
}

Run:
  python experiments/elaip_LeanEvolve/build_layer2_ir.py
  # -> FormalAgentLib/VerificationExamples/elaipbench_layer2_v2_ir/<plan>_layer2_v2.ir.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
DEFAULT_OUT_DIR = REPO_ROOT / "FormalAgentLib/VerificationExamples/elaipbench_layer2_v2_ir"
DEFAULT_PLANS_DIR = REPO_ROOT / "experiments/elaipbench"
DEFAULT_BASELINE = DEFAULT_PLANS_DIR / "elaipbench_agent.yaml"

# Variable names that ELAIP plans typically `save_as`. Predicate annotations
# below are keyed by these names — the schema check we emit at Layer 3 is the
# same regardless of which step writes the variable.
ELAIP_VAR_PREDICATES: dict[str, list[dict]] = {
    "paper_overview": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "paper_structure": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "section_outline": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "section_headings": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "question_analysis": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
        {"kind": "ext", "key": {"family": "user.elaip", "name": "questionTypeEnum"}},
    ],
    "search_keywords": [
        {"kind": "nameExists"},
        {"kind": "isValidList"},
    ],
    "keyword_passages": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "evidence": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
        {"kind": "ext", "key": {"family": "user.elaip", "name": "boundedEvidenceList"}},
        {"kind": "ext", "key": {"family": "user.elaip", "name": "verbatimSubstring"}},
    ],
    "evidence_quality_check": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
    ],
    "option_judgment": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
        {"kind": "isValidJson"},
        {"kind": "ext", "key": {"family": "user.elaip", "name": "verdictEnumValid"}},
    ],
    "final_response": [
        {"kind": "nameExists"},
        {"kind": "isNonEmptyString"},
    ],
    "recheck_count": [
        {"kind": "nameExists"},
    ],
}

# Human-readable semantic description per predicate kind, copied into the IR
# so downstream LLM prompts can read meanings without dispatching on `.ext`.
SEMANTIC_DESCRIPTIONS: dict[str, str] = {
    "nameExists": "the variable is bound at this point in the workflow",
    "isNonEmptyString": "the saved variable serialises to a non-empty string",
    "isValidJson": "the saved variable's serialised form parses as JSON",
    "isValidList": "the saved variable parses as a JSON array",
    "user.elaip:questionTypeEnum":
        "saved variable's `question_type` field ∈ "
        "[Single-answer, Multiple-answer, SA-MCQ, MA-MCQ]",
    "user.elaip:boundedEvidenceList":
        "saved variable contains an `evidence_snippets` JSON array of length ≤ 5",
    "user.elaip:verbatimSubstring":
        "every snippet's `text` field appears verbatim (character-exact) in `paper_content`",
    "user.elaip:verdictEnumValid":
        "saved variable is a JSON dict whose A/B/C/D entries each have "
        "`verdict ∈ [supported, contradicted, not_established]`",
}


def predicate_description(pred: dict) -> str:
    if pred.get("kind") == "ext":
        key = pred.get("key", {})
        full = f"{key.get('family')}:{key.get('name')}"
        return SEMANTIC_DESCRIPTIONS.get(full, f"extension predicate {full}")
    return SEMANTIC_DESCRIPTIONS.get(pred.get("kind", ""), pred.get("kind", ""))


def annotated_postconds(save_as: str | None) -> list[dict]:
    """Look up the canonical postcondition predicates for a given save_as
    variable. Each entry includes the predicate spec + a semantic description
    so downstream prompts don't have to consult a separate table."""
    if not save_as:
        return []
    preds = ELAIP_VAR_PREDICATES.get(save_as, [{"kind": "nameExists"}])
    out = []
    for p in preds:
        entry = dict(p)
        entry["var_name"] = save_as
        entry["semantic_description"] = predicate_description(p)
        out.append(entry)
    return out


def first_str(s: Any, n: int = 500) -> str:
    if not isinstance(s, str):
        return ""
    return s if len(s) <= n else s[:n] + "..."


def extract_template_reads(instruction: str) -> list[str]:
    """Find {{var}} references in an instruction. Crude regex; matches
    {{x}}, {{x.y}}, etc. Returns the unique base names ('x' for 'x.y')."""
    if not isinstance(instruction, str):
        return []
    found = re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z0-9_]+)*\s*\}\}", instruction)
    seen = set()
    out: list[str] = []
    for f in found:
        if f not in seen:
            out.append(f)
            seen.add(f)
    return out


# Each entry returned by `flatten_workflow` carries enough info to build a
# downstream Layer-3 codegen and predicate projection.
def flatten_workflow(workflow: list, branch_path: tuple[str, ...] = ()) -> list[dict]:
    """Walk a YAML `workflow:` block and return a flat list of nodes.
    Recursively descends into for_each / while / switch / if blocks. Records
    the branch_path so callers can identify nested-vs-top-level steps."""
    out: list[dict] = []
    for entry in workflow or []:
        if not isinstance(entry, dict):
            continue
        # Single-key dicts are the YAML node-kind discriminator.
        if "step" in entry or "task" in entry:
            kind = "step" if "step" in entry else "task"
            body = entry.get(kind) or {}
            out.append({
                "raw_kind": kind,
                "name": body.get("name", "<anon>"),
                "step_type": kind,
                "save_as": body.get("save_as"),
                "instruction_excerpt": first_str(body.get("instruction"), 500),
                "reads_templates": extract_template_reads(body.get("instruction", "")),
                "branch_path": list(branch_path),
                "executable": True,
            })
        elif "discover" in entry:
            body = entry.get("discover") or {}
            out.append({
                "raw_kind": "discover",
                "name": body.get("name", "<anon-discover>"),
                "step_type": "discover",
                "save_as": body.get("name"),  # discover writes its own name
                "instruction_excerpt": first_str(body.get("instruction"), 500),
                "reads_templates": [body.get("from")] if body.get("from") else [],
                "branch_path": list(branch_path),
                "executable": True,
            })
        elif "for_each" in entry:
            body = entry.get("for_each") or {}
            inner = body.get("steps") or []
            out.extend(flatten_workflow(inner,
                                        branch_path + (f"for_each:{body.get('variable', '?')}",)))
        elif "while" in entry:
            body = entry.get("while") or {}
            inner = body.get("steps") or []
            out.extend(flatten_workflow(inner,
                                        branch_path + (f"while:{body.get('condition', '?')[:30]}",)))
        elif "if" in entry:
            body = entry.get("if") or {}
            cond = body.get("condition", "?")
            then_steps = body.get("then") or []
            else_steps = body.get("else") or []
            out.extend(flatten_workflow(then_steps, branch_path + (f"if:{cond[:30]}=true",)))
            out.extend(flatten_workflow(else_steps, branch_path + (f"if:{cond[:30]}=false",)))
        elif "switch" in entry:
            body = entry.get("switch") or {}
            cases = body.get("cases") or {}
            for case_name, case_steps in cases.items():
                out.extend(flatten_workflow(case_steps or [], branch_path + (f"switch:{case_name}",)))
            default_steps = body.get("default") or []
            if default_steps:
                out.extend(flatten_workflow(default_steps, branch_path + ("switch:default",)))
        elif "set_variable" in entry:
            body = entry.get("set_variable") or {}
            out.append({
                "raw_kind": "set_variable",
                "name": f"set_variable:{body.get('name', '?')}",
                "step_type": "set_variable",
                "save_as": body.get("name"),
                "instruction_excerpt": "",
                "reads_templates": [],
                "branch_path": list(branch_path),
                "executable": False,
            })
        elif "increment" in entry:
            tgt = entry.get("increment", "?")
            out.append({
                "raw_kind": "increment",
                "name": f"increment:{tgt}",
                "step_type": "increment",
                "save_as": tgt if isinstance(tgt, str) else None,
                "instruction_excerpt": "",
                "reads_templates": [],
                "branch_path": list(branch_path),
                "executable": False,
            })
        elif "synthesize" in entry:
            body = entry.get("synthesize") or {}
            out.append({
                "raw_kind": "synthesize",
                "name": body.get("name", "<anon-synth>"),
                "step_type": "synthesize",
                "save_as": body.get("save_as"),
                "instruction_excerpt": first_str(body.get("instruction"), 500),
                "reads_templates": extract_template_reads(body.get("instruction", "")),
                "branch_path": list(branch_path),
                "executable": True,
            })
        # Other YAML kinds (validate, return, etc.) are ignored — ELAIP plans
        # don't use them.
    return out


def parameters_from_yaml(plan: dict) -> list[dict]:
    raw_params = plan.get("parameters") or {}
    out: list[dict] = []
    for name, default in raw_params.items():
        # Heuristic: paper_content / question / question_type_instruction are
        # non-empty at runtime; question_type is enum-like.
        preds: list[dict] = [{"kind": "nameExists"}]
        if name in ("paper_content", "question", "question_type_instruction"):
            preds.append({"kind": "isNonEmptyString"})
        if name == "question_type":
            preds.append({"kind": "isNonEmptyString"})
        out.append({
            "name": name,
            "default": default if isinstance(default, str) else "",
            "predicates": preds,
        })
    return out


def derive_plan_kind(plan_name: str) -> str:
    if plan_name.startswith("passed_workflow"):
        return "best"
    if plan_name.startswith("failed_workflow"):
        return "worst"
    return "baseline"


def plan_to_workflow_file(plan_name: str) -> str:
    """The plan name is already the hand-written Layer-2 `.lean` file stem
    (passed_workflow_N / failed_workflow_N)."""
    return plan_name


def derive_layer2_module(plan_name: str, plan_kind: str) -> str:
    """The hand-written ELAIP Layer-2 specs live at
    FormalAgentLib/StaticSemanticWorkflowExamples/ELAIP-Bench/{passed,failed}_workflow_N.lean
    (passed_workflow_N -> passed_workflow_N, failed_workflow_N -> failed_workflow_N). The
    `ELAIP-Bench` directory hyphen requires guillemets in the module path."""
    return f"StaticSemanticWorkflowExamples.«ELAIP-Bench».{plan_to_workflow_file(plan_name)}"


def derive_open_namespace(plan_name: str) -> str:
    """Each hand-written ELAIP Layer-2 file declares its graph + goalSpec inside
    `namespace AgenticKernel.<plan>_layer2_new`, so the generated Layer-3 file
    must `open` that namespace to see `<plan>_layer2SemanticGraph`."""
    return f"AgenticKernel.{plan_name}_layer2_new"


def build_ir(yaml_path: Path, plan_name: str | None = None) -> dict:
    plan = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    plan_name = plan_name or yaml_path.stem
    plan_kind = derive_plan_kind(plan_name)
    nodes_flat = flatten_workflow(plan.get("workflow") or [])

    nodes: list[dict] = []
    for idx, n in enumerate(nodes_flat):
        nodes.append({
            "id": idx,
            "name": n["name"],
            "step_type": n["step_type"],
            "raw_kind": n["raw_kind"],
            "save_as": n["save_as"],
            "reads_templates": n["reads_templates"],
            "instruction_excerpt": n["instruction_excerpt"],
            "branch_path": n["branch_path"],
            "executable": n["executable"],
            "postconds": annotated_postconds(n["save_as"]) if n["executable"] else [],
        })

    # Sequential edges over the flattened list (best-effort — branch
    # interleaving is recorded in `branch_path` but doesn't break edges).
    edges = [
        {"from": i, "to": i + 1, "kind": "seq"}
        for i in range(len(nodes) - 1)
    ]

    entry = 0 if nodes else None
    # Exit candidates: nodes whose save_as is `final_response`. Fallback: last node.
    exits = [n["id"] for n in nodes if n["save_as"] == "final_response"]
    if not exits and nodes:
        exits = [nodes[-1]["id"]]

    # Per-plan Lean def names. The Layer-2 .lean file uses `<plan>SemanticGraph`
    # and `<plan>_goalSpec` as the canonical def names for the SemanticWorkflowGraph
    # and the GoalSpecification, respectively. The prefix matches the per-node ID
    # prefix used in the .lean (e.g. `passed_workflow_1_nodeId0`).
    return {
        "ir_kind": "elaip_layer2",
        "plan_name": plan_name,
        "plan_kind": plan_kind,
        "yaml_path": str(yaml_path.relative_to(REPO_ROOT)) if str(yaml_path).startswith(str(REPO_ROOT)) else str(yaml_path),
        "layer2_module": derive_layer2_module(plan_name, plan_kind),
        "open_namespace": derive_open_namespace(plan_name),
        "prefix": plan_name,
        "semantic_graph_def": f"{plan_name}_layer2SemanticGraph",
        "goal_spec_def": f"{plan_name}_goalSpec",
        "name": plan.get("name", plan_name),
        "goal": plan.get("goal", ""),
        "parameters": parameters_from_yaml(plan),
        "nodes": nodes,
        "edges": edges,
        "entry": entry,
        "exits": exits,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--plans-dir", default=str(DEFAULT_PLANS_DIR),
                   help=f"Directory containing the ELAIP plan YAMLs (default: {DEFAULT_PLANS_DIR})")
    p.add_argument("--baseline-yaml", default=str(DEFAULT_BASELINE),
                   help=f"Optional baseline plan YAML (default: {DEFAULT_BASELINE})")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                   help=f"Output directory for per-plan IR JSONs (default: {DEFAULT_OUT_DIR})")
    p.add_argument("--single", default="",
                   help="If given, only build this plan (e.g. passed_workflow_1) and print to stdout")
    args = p.parse_args()

    plans_dir = Path(args.plans_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.single:
        yaml_path = plans_dir / f"{args.single}.yaml"
        if not yaml_path.exists():
            print(f"ERROR: {yaml_path} not found", file=sys.stderr)
            sys.exit(2)
        ir = build_ir(yaml_path, args.single)
        out_path = out_dir / f"{args.single}_layer2_v2.ir.json"
        out_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"OK: {args.single} -> {out_path} "
              f"({len(ir['nodes'])} nodes, {len(ir['edges'])} edges, "
              f"entry={ir['entry']}, exits={ir['exits']})")
        return

    # Default: build for every passed_workflow_*.yaml + failed_workflow_*.yaml + baseline
    targets: list[tuple[str, Path]] = []
    for yaml_path in sorted(plans_dir.glob("passed_workflow_*.yaml")):
        targets.append((yaml_path.stem, yaml_path))
    for yaml_path in sorted(plans_dir.glob("failed_workflow_*.yaml")):
        targets.append((yaml_path.stem, yaml_path))
    if Path(args.baseline_yaml).exists():
        targets.append(("elaipbench_agent_baseline", Path(args.baseline_yaml)))

    if not targets:
        print(f"ERROR: no plan YAMLs found under {plans_dir}", file=sys.stderr)
        sys.exit(2)

    for plan_name, yaml_path in targets:
        ir = build_ir(yaml_path, plan_name)
        out_path = out_dir / f"{plan_name}_layer2_v2.ir.json"
        out_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        n_exec = sum(1 for n in ir["nodes"] if n["executable"])
        print(f"OK: {plan_name:36s} -> {out_path.name}  "
              f"(nodes={len(ir['nodes'])}, executable={n_exec}, "
              f"entry={ir['entry']}, exits={ir['exits']})")


if __name__ == "__main__":
    main()
