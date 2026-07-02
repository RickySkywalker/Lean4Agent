"""Shell command utilities for tool execution.

This module provides utilities for shell command handling, including
default injection and submit token detection.
"""

from typing import Any, Dict, Optional

from ..types.context import ContextKeys, Tokens


def inject_shell_defaults(
    tool_name: str,
    tool_args: Dict[str, Any],
    context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Inject default values for shell_run tool based on context.

    Automatically adds working directory and conda environment from
    context if not already specified in the tool arguments.

    Args:
        tool_name: Name of the tool being invoked.
        tool_args: Arguments for the tool.
        context: Execution context with potential defaults.

    Returns:
        Updated tool arguments with defaults injected.

    Example:
        args = inject_shell_defaults("shell_run", {"text": "ls"}, context)
        # If context has CODE_PATH, args will include "cwd"
    """
    if tool_name != "shell_run" or not context:
        return tool_args

    updated = dict(tool_args or {})

    if "cwd" not in updated and context.get(ContextKeys.CODE_PATH):
        updated["cwd"] = context[ContextKeys.CODE_PATH]

    if "conda_env" not in updated and context.get(ContextKeys.CONDA_ENV_NAME):
        updated["conda_env"] = context[ContextKeys.CONDA_ENV_NAME]

    return updated


def is_submit_command(command_text: str) -> bool:
    """Check if command text contains the task completion submit token.

    The submit token signals that the agent should complete the current
    task and submit final output.

    Args:
        command_text: The command text to check.

    Returns:
        True if the submit token is found.

    Example:
        if is_submit_command(shell_output):
            return "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    """
    return Tokens.SUBMIT_COMPLETE in (command_text or "")


# Backward compatibility alias
contains_submit_token = is_submit_command
