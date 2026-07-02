"""Shared helpers for layer2_v2 IR authoring scripts."""

from pathlib import Path
import sys

# Make TaskPlanToLean importable regardless of how this script is invoked.
_DEMO_DIR = Path(__file__).resolve().parents[2]
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

import TaskPlanToLean as t  # noqa: E402

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
IR_DIR = REPO_ROOT / "FormalAgentLib" / "VerificationExamples" / "layer2_v2_ir"


def P(kind: str, **kw) -> t.PredicateIR:
    return t.PredicateIR(kind=kind, **kw)


def VP(var_name: str, kind: str, **kw) -> t.VarPredicateIR:
    return t.VarPredicateIR(var_name=var_name, predicate=P(kind, **kw))


def TV(name: str, base_type: str = "TString", predicates=None, value=None) -> t.TypedVar:
    return t.TypedVar(name=name, base_type=base_type, predicates=predicates, value=value)


def GPK(kind: str) -> t.GraphPredicateKeyIR:
    return t.GraphPredicateKeyIR(kind=kind)


def SubGoal(name, variable_name, required_predicate, description="",
            required_graph_predicates=None) -> t.SubGoalSpecIR:
    return t.SubGoalSpecIR(
        name=name,
        variable_name=variable_name,
        required_predicate=required_predicate,
        description=description,
        required_graph_predicates=required_graph_predicates or [],
    )


def save(ir: t.WorkflowIR, stem: str) -> Path:
    IR_DIR.mkdir(parents=True, exist_ok=True)
    path = IR_DIR / f"{stem}.ir.json"
    ir.save_json(str(path))
    print(f"Wrote {path}")
    return path


def seq_edges(n: int) -> list[t.EdgeIR]:
    """Build 0→1, 1→2, ..., (n-2)→(n-1) sequential edges."""
    return [t.EdgeIR(edge_type="seq", from_node=i, to_node=i + 1) for i in range(n - 1)]
