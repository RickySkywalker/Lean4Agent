"""Python dataclasses mirroring Lean verification result types."""

from dataclasses import dataclass, field
from typing import Any, Optional
import json


@dataclass
class TheoremResult:
    name: str
    status: bool


@dataclass
class ReadResolution:
    var_name: str
    type: str
    resolved: bool
    source: str  # "parameter" | "predecessor" | "unresolved"
    type_compatible: bool


@dataclass
class PreconditionResult:
    var_name: str
    predicate_type: str
    predicate_json: dict
    satisfied: bool
    satisfied_by: Optional[str]
    failure_detail: Optional[str]


@dataclass
class NodeLayer1:
    writes_consistent: bool
    reachable_from_entry: bool
    reads: list[ReadResolution]
    writes: list[dict]
    predecessors: list[int] = field(default_factory=list)
    successors: list[int] = field(default_factory=list)


@dataclass
class NodeLayer2:
    preconditions: list[PreconditionResult]
    postconditions: list[dict]
    step_tags: list[str]
    sub_goal_contributions: list[str]
    sub_goal_verifications: list[str]
    info_content_aspects: list[dict]
    implicit_retry_sub_goals: list[str]
    cumulative_state_after: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class PostcondVerdict:
    index: int
    var_name: str
    predicate_type: str
    is_sentinel: bool
    lean_verdict: Optional[dict]
    tool_verdict: Optional[dict]
    llm_verdict: Optional[dict]
    composite: str  # "confirmed" | "falsified" | "sentinel"
    root_cause: Optional[str]


@dataclass
class NodeLayer3:
    trajectory_step_id: str
    execution_status: str
    trace_summary: str
    precondition_at_entry: dict
    postcondition_verdicts: list[PostcondVerdict]
    step_composite: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class PerNodeResult:
    node_id: int
    node_name: str
    step_type: str
    layer1: Optional[NodeLayer1] = None
    layer2: Optional[NodeLayer2] = None
    layer3: Optional[NodeLayer3] = None


@dataclass
class VerificationOutput:
    layer: int
    graph_name: str
    theorem_results: dict
    per_node_results: list[dict]
    graph_level_results: dict
    errors: list[str] = field(default_factory=list)
    raw_json: Optional[dict] = None

    def to_json(self, pretty: bool = True) -> str:
        """Serialize to JSON string."""
        data = self.raw_json if self.raw_json else {
            "layer": self.layer,
            "graph_name": self.graph_name,
            "theorem_results": self.theorem_results,
            "per_node_results": self.per_node_results,
            "graph_level_results": self.graph_level_results,
            "errors": self.errors,
        }
        return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)


def parse_lean_json(raw_stdout: str) -> VerificationOutput:
    """Parse the JSON stdout from the Lean driver into a VerificationOutput."""
    try:
        data = json.loads(raw_stdout)
    except json.JSONDecodeError as e:
        return VerificationOutput(
            layer=0, graph_name="", theorem_results={},
            per_node_results=[], graph_level_results={},
            errors=[f"Failed to parse JSON from Lean output: {e}"],
        )
    return VerificationOutput(
        layer=data.get("layer", 0),
        graph_name=data.get("graph_name", ""),
        theorem_results=data.get("theorem_results", {}),
        per_node_results=data.get("per_node_results", []),
        graph_level_results=data.get("graph_level_results", {}),
        errors=data.get("errors", []),
        raw_json=data,
    )
