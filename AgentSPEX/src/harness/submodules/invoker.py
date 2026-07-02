import json
from typing import Any, Dict, Optional, Union

from ..utils.step_utils import get_step_depth
from .specs import SubmoduleFunctionSpec, extract_submodule_result_value


def prepare_submodule_params(
    spec: SubmoduleFunctionSpec,
    tool_args: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Prepare parameters for a submodule invocation by collecting from context and tool args.

    Args:
        spec: The submodule function specification
        tool_args: Arguments provided by the tool call
        context: Current execution context

    Returns:
        Dictionary of resolved parameters

    Raises:
        ValueError: If required parameters are missing
    """
    params: Dict[str, Any] = {}
    missing = []

    # Collect context parameters
    for p in spec.context_params:
        if p.name in context:
            params[p.name] = context[p.name]
        elif p.default is not None:
            params[p.name] = p.default
        elif p.required:
            missing.append(p.name)

    # Collect model parameters from tool args
    for p in spec.model_params:
        if p.name in tool_args:
            params[p.name] = tool_args[p.name]
        elif p.default is not None:
            params[p.name] = p.default
        elif p.required:
            missing.append(p.name)

    if missing:
        raise ValueError(f"Missing required submodule parameters: {', '.join(missing)}")

    return params


def build_call_step_data(
    spec: SubmoduleFunctionSpec,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the call step data structure for submodule invocation."""
    return {
        "call": {
            "module": spec.module_path,
            "parameters": params,
            "return": spec.return_var,
        }
    }


def log_submodule_start(
    logger,
    step_id: Union[int, str],
    tool_name: str,
    spec: SubmoduleFunctionSpec,
    parent_step_id: Union[int, str, None] = None,
    parent_iteration: Optional[int] = None,
) -> None:
    """Log the start of a submodule invocation."""
    step_id_str = str(step_id)
    logger.log_event(
        logger,
        "step_start",
        {
            "step_id": step_id_str,
            "step_number": step_id_str,
            "name": tool_name,
            "step_type": "submodule_call",
            "instruction": spec.description or "",
            "depth": get_step_depth(step_id_str),
            "parent_step_id": (
                str(parent_step_id) if parent_step_id is not None else None
            ),
            "parent_iteration": parent_iteration,
        },
    )


def log_submodule_end(
    logger,
    step_id: Union[int, str],
    tokens: int,
    status: str = "completed",
    error: Optional[str] = None,
) -> None:
    """Log the end of a submodule invocation."""
    step_id_str = str(step_id)
    event_data = {
        "step_id": step_id_str,
        "tokens": tokens,
        "status": status,
    }
    if error:
        event_data["error"] = error
    logger.log_event(logger, "step_end", event_data)
