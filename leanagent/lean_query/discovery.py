"""Regex-based parsing of Lean files to discover definition names."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lean_query.config import ConfigError

PATTERNS = {
    "workflow_graph":  re.compile(r"^def\s+(\w+)\s*:\s*WorkflowGraph\s*:=", re.MULTILINE),
    "semantic_graph":  re.compile(r"^def\s+(\w+)\s*:\s*SemanticWorkflowGraph\s*:=", re.MULTILINE),
    "goal_spec":       re.compile(r"^def\s+(\w+)\s*:\s*GoalSpecification\s*:=", re.MULTILINE),
    "dynamic_graph":   re.compile(r"^def\s+(\w+)\s*:\s*DynamicVerificationGraph\s*:=", re.MULTILINE),
    "step_id_map":     re.compile(r"^def\s+(\w+)\s*:\s*StepIdMap\s*:=", re.MULTILINE),
    "llm_injections":  re.compile(r"^def\s+(\w+)\s*:\s*List\s+PerPredicateLLMInjection\s*:=", re.MULTILINE),
    "exec_state":      re.compile(r"^def\s+(\w+)\s*:\s*NodeExecutionState\s*:=", re.MULTILINE),
    "runtime_facts":   re.compile(r"^def\s+(\w+)\s*:\s*List\s+RuntimeTurnFact\s*:=", re.MULTILINE),
    # the zero-axiom form: RAW per-turn inputs, judged ENTIRELY in Lean (conv ab6eb9d9).
    "runtime_inputs":  re.compile(r"^def\s+(\w+)\s*:\s*List\s+RuntimeTurnInput\s*:=", re.MULTILINE),
    "report_path":     re.compile(r'^def\s+(\w+)\s*:\s*System\.FilePath\s*:=\s*\n?\s*"(.+?)"', re.MULTILINE),
    "event_log_path":  re.compile(r'^def\s+(\w+)\s*:\s*System\.FilePath\s*:=\s*\n?\s*"(.+?)"', re.MULTILINE),
}

# Capture the full (possibly dotted) namespace path. New-format files nest the
# plan under `namespace AgenticKernel.<plan>`, so a bare `\w+` would drop the
# tail and leave the plan's defs unresolvable in the generated driver.
NAMESPACE_RE = re.compile(r"^namespace\s+([\w.]+)", re.MULTILINE)


@dataclass
class DiscoveredDefs:
    """Definitions discovered in a Lean verification file."""
    namespace: Optional[str] = None
    workflow_graph: Optional[str] = None
    semantic_graph: Optional[str] = None
    goal_spec: Optional[str] = None
    dynamic_graph: Optional[str] = None
    step_id_map: Optional[str] = None
    llm_injections: Optional[str] = None
    exec_state: Optional[str] = None
    runtime_facts: Optional[str] = None
    runtime_inputs: Optional[str] = None
    report_path_var: Optional[str] = None
    event_log_path_var: Optional[str] = None
    # For report/event_log, also capture the actual path values
    report_path_value: Optional[str] = None
    event_log_path_value: Optional[str] = None


def discover_definitions(lean_file_path: str) -> DiscoveredDefs:
    """Parse a Lean file to discover definition names for verification entities.

    Args:
        lean_file_path: Path to the .lean file.

    Returns:
        DiscoveredDefs with all found definition names.
    """
    content = Path(lean_file_path).read_text()
    defs = DiscoveredDefs()

    # Namespace
    ns_match = NAMESPACE_RE.search(content)
    if ns_match:
        defs.namespace = ns_match.group(1)

    # Simple definitions (first match for each)
    for field_name in ["workflow_graph", "semantic_graph", "goal_spec",
                       "dynamic_graph", "step_id_map", "llm_injections", "exec_state",
                       "runtime_facts", "runtime_inputs"]:
        pattern = PATTERNS[field_name]
        match = pattern.search(content)
        if match:
            setattr(defs, field_name, match.group(1))

    # FilePath definitions — find all and assign first two as report/event_log
    filepath_re = re.compile(r'^def\s+(\w+)\s*:\s*System\.FilePath\s*:=\s*\n?\s*"(.+?)"', re.MULTILINE)
    filepath_matches = list(filepath_re.finditer(content))
    if len(filepath_matches) >= 1:
        defs.report_path_var = filepath_matches[0].group(1)
        defs.report_path_value = filepath_matches[0].group(2)
    if len(filepath_matches) >= 2:
        defs.event_log_path_var = filepath_matches[1].group(1)
        defs.event_log_path_value = filepath_matches[1].group(2)

    return defs


def detect_available_layers(defs: DiscoveredDefs) -> list[int]:
    """Detect which verification layers are available based on discovered definitions."""
    layers = []
    if defs.workflow_graph:
        layers.append(1)
    if defs.semantic_graph and defs.goal_spec:
        layers.append(2)
    if defs.dynamic_graph:
        layers.append(3)
    return layers


def resolve_config(lean_file_path: str, config) -> dict[str, str]:
    """Discover definitions, merge with config overrides, validate all required exist.

    Returns resolved name mapping. Raises ConfigError if required field missing.
    """
    defs = discover_definitions(lean_file_path)

    resolved = {}

    # Namespace
    if config.namespace == "auto":
        resolved["namespace"] = defs.namespace or "AgenticKernel"
    else:
        resolved["namespace"] = config.namespace

    # Resolve each field: use config override if not "auto", else use discovered
    field_map = {
        "workflow_graph": ("workflow_graph", defs.workflow_graph),
        "semantic_graph": ("semantic_graph", defs.semantic_graph),
        "goal_spec": ("goal_spec", defs.goal_spec),
        "dynamic_graph": ("dynamic_graph", defs.dynamic_graph),
        "step_id_map": ("step_id_map", defs.step_id_map),
        "llm_injections": ("llm_injections", defs.llm_injections),
        "exec_state": ("exec_state", defs.exec_state),
        "runtime_facts": ("runtime_facts", defs.runtime_facts),
        "runtime_inputs": ("runtime_inputs", defs.runtime_inputs),
        "report_path_var": ("report_path_var", defs.report_path_var),
        "event_log_path_var": ("event_log_path_var", defs.event_log_path_var),
    }

    for config_field, (key, discovered) in field_map.items():
        config_val = getattr(config, config_field, None)
        if config_val and config_val != "auto":
            resolved[key] = config_val
        elif discovered:
            resolved[key] = discovered
        # else: remains unset

    # Pass the channel through so the driver generator can branch.
    resolved["channel"] = getattr(config, "channel", "process")

    # Validate required fields for the requested layer (+ layer-3 sub-channel).
    if config.layer == 3 and resolved["channel"] == "runtime":
        # The per-turn gamma channel needs EITHER the zero-axiom raw-input def
        # (`List RuntimeTurnInput`, preferred — Lean judges) OR the legacy digested
        # `List RuntimeTurnFact` def. driver_gen picks the matching entry point.
        if "runtime_inputs" not in resolved and "runtime_facts" not in resolved:
            raise ConfigError(
                f"runtime channel needs a `def <name> : List RuntimeTurnInput :=` "
                f"(or legacy `List RuntimeTurnFact`) in {lean_file_path}."
            )
        needed = []  # custom-validated above
    else:
        required_fields = {
            1: ["workflow_graph"],
            2: ["workflow_graph", "semantic_graph", "goal_spec"],
            # Layer-3 driver: per-step rules come from exec_state (no SWE
            # report file), and the dynamic graph carries the semantic graph +
            # goalSpec, so only the dynamic-layer defs + the event log are needed.
            3: ["dynamic_graph", "step_id_map", "llm_injections",
                "exec_state", "event_log_path_var"],
        }
        needed = required_fields.get(config.layer, [])

    for field_name in needed:
        if field_name not in resolved:
            raise ConfigError(
                f"Required definition '{field_name}' not found in {lean_file_path} "
                f"and not specified in config. Set '{field_name}' explicitly."
            )

    return resolved


def file_to_module(target_file: str) -> str:
    """Convert a relative Lean file path to a Lean module import path.

    Example: "VerificationExamples/failed_workflow_2_layer2_v2.lean"
           → "VerificationExamples.failed_workflow_2_layer2_v2"
    """
    return target_file.replace(".lean", "").replace("/", ".").replace("\\", ".")
