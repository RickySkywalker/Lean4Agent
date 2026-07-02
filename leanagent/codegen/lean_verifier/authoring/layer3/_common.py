"""Shared helpers for Layer 3 IR authoring scripts.

All three reference files wrap the same Layer 2 plan (passed_workflow_1_v2). We
reuse the Layer 2 IR JSON produced in Stage 1 instead of re-authoring the
workflow from scratch.
"""

from pathlib import Path
import sys

_DEMO_DIR = Path(__file__).resolve().parents[2]
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

import TaskPlanToLean as t  # noqa: E402

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
IR_DIR = REPO_ROOT / "FormalAgentLib" / "VerificationExamples" / "layer3_ir"
LAYER2_IR_PATH = (
    REPO_ROOT / "FormalAgentLib" / "VerificationExamples"
    / "layer2_v2_ir" / "passed_workflow_1_layer2_v2.ir.json"
)

# Standard step-id map for all three examples — agent emits 1..5, Layer 2
# uses NodeId 0..4.
STANDARD_STEP_ID_MAP = [
    ("1", 0),
    ("2", 1),
    ("3", 2),
    ("4", 3),
    ("5", 4),
]

# Standard dyn_nodes wiring for the 5-node passed_workflow_1_v2 graph.
STANDARD_DYN_NODES = [
    t.DynNodeSpecIR("passed_workflow_1_v2_semNode0", "1", "explore_repository"),
    t.DynNodeSpecIR("passed_workflow_1_v2_semNode1", "2", "reproduce_issue"),
    t.DynNodeSpecIR("passed_workflow_1_v2_semNode2", "3", "fix_issue"),
    t.DynNodeSpecIR("passed_workflow_1_v2_semNode3", "4", "verify_fix"),
    t.DynNodeSpecIR("passed_workflow_1_v2_semNode4", "5", "create_patch"),
]


def load_passed_workflow_1_v2_workflow() -> "t.WorkflowIR":
    """Load the shared Layer 2 WorkflowIR from Stage 1."""
    return t.WorkflowIR.load_json(str(LAYER2_IR_PATH))


def save(ir: "t.Layer3IR", stem: str) -> Path:
    IR_DIR.mkdir(parents=True, exist_ok=True)
    path = IR_DIR / f"{stem}.ir.json"
    ir.save_json(str(path))
    print(f"Wrote {path}")
    return path
