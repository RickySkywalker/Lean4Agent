"""Generate temporary Lean driver files for verification queries."""

from lean_query.discovery import file_to_module


def generate_driver(
    target_import: str,
    resolved: dict[str, str],
    layer: int,
) -> str:
    """Generate the content of _lean_query_driver.lean.

    Args:
        target_import: Lean module path for the target file
                      (e.g., "VerificationExamples.failed_workflow_1_layer2_v2")
        resolved: Resolved definition names from discovery.
        layer: Which layer to verify (1, 2, or 3).

    Returns:
        Full text of the Lean driver file.
    """
    ns = resolved.get("namespace", "AgenticKernel")
    # workflow_graph is only used by the layer-1/2/3-process bodies; the runtime
    # (gamma) channel target need not define one, so access it lazily.
    graph = resolved.get("workflow_graph", "")

    # The static verification library (`layer1ToJson`, `layer2ToJson`) lives in
    # the `AgenticKernel` namespace; the dynamic layer (`layer3ToJson`,
    # `analyzeAllSteps`, `ElaipBench.*`, `ExecutionTrace.*`, …) lives in
    # `AgenticKernel.Dyn`. The plan's own defs (graph, goalSpec, dynamicGraph,
    # …) live in the file's namespace — which for new-format files is a NESTED
    # namespace like `AgenticKernel.<plan>`. Open what each layer needs so bare
    # references resolve; drop the plan-namespace open when it is just
    # `AgenticKernel` (old-format / flat files) to avoid a redundant line.
    channel = resolved.get("channel", "process")
    runtime = (layer == 3 and channel == "runtime")

    open_lines = ["open AgenticKernel"]
    if ns and ns != "AgenticKernel":
        open_lines.append(f"open {ns}")
    # All of Layer-3 lives in the dynamic layer `AgenticKernel.Dyn`
    # (`analyzeAllSteps`, `layer3ToJson`, `ElaipBench.*`, `ExecutionTrace.*`,
    # and the runtime-gamma `layer3RuntimeToJson`); open it for any layer-3 driver.
    if layer == 3:
        open_lines.append("open AgenticKernel.Dyn")

    lines = [
        f"import AgentVerifier.VerificationJsonOutput",
        f"import {target_import}",
        "",
        *open_lines,
        "",
        "def main : IO Unit := do",
    ]

    if layer == 1:
        lines.extend(_layer1_body(graph))
    elif layer == 2:
        sem_graph = resolved["semantic_graph"]
        goal_spec = resolved["goal_spec"]
        lines.extend(_layer2_body(graph, sem_graph, goal_spec))
    elif layer == 3 and runtime:
        lines.extend(_layer3_runtime_body(resolved))
    elif layer == 3:
        dyn_graph = resolved["dynamic_graph"]
        step_id_map = resolved["step_id_map"]
        llm_injections = resolved["llm_injections"]
        exec_state = resolved["exec_state"]
        event_log_path_var = resolved["event_log_path_var"]
        lines.extend(_layer3_body(
            dyn_graph, step_id_map, llm_injections,
            exec_state, event_log_path_var,
        ))

    return "\n".join(lines) + "\n"


def _layer1_body(graph: str) -> list[str]:
    return [
        f"  let result := {graph}.layer1ToJson",
        f"  IO.println result.pretty",
    ]


def _layer2_body(graph: str, sem_graph: str, goal_spec: str) -> list[str]:
    return [
        f"  let result := {sem_graph}.layer2ToJson (some {goal_spec})",
        f"  IO.println result.pretty",
    ]


def _layer3_runtime_body(resolved: dict) -> list[str]:
    """Per-turn gamma channel: run the RuntimePredicates and emit the runtime_gamma
    JSON (one Lean parse, all turns).  Prefers the ZERO-AXIOM raw-input def
    (`List RuntimeTurnInput` → `layer3RuntimeFromInputsToJson`, where Lean computes
    the whole judgement); falls back to the legacy digested-facts def
    (`List RuntimeTurnFact` → `layer3RuntimeToJson`)."""
    inputs = resolved.get("runtime_inputs")
    if inputs:
        entry, defname = "layer3RuntimeFromInputsToJson", inputs
    else:
        entry, defname = "layer3RuntimeToJson", resolved["runtime_facts"]
    return [
        f"  let result := {entry} {defname}",
        f"  IO.println result.compress",
    ]


def _layer3_body(
    dyn_graph: str, step_id_map: str, llm_injections: str,
    exec_state: str, event_log_path_var: str,
) -> list[str]:
    """Per-step (process) channel, dynamic layer. Per-step analysis rules are
    derived from the final execution state (`ElaipBench.rulesFromState`) — no SWE
    report file is needed — then folded into the unified Layer-3 JSON
    (`layer3ToJson`); the dynamic graph carries the semantic graph + goalSpec."""
    return [
        f"  let trace ← ExecutionTrace.loadEventLog {event_log_path_var}",
        f"  let rules := ElaipBench.rulesFromState {exec_state}",
        f"  let analyses := analyzeAllSteps {dyn_graph} trace {step_id_map} rules {llm_injections}",
        f"  let result := layer3ToJson {dyn_graph} trace analyses (stepIdMap := {step_id_map})",
        f"  IO.println result.pretty",
    ]
