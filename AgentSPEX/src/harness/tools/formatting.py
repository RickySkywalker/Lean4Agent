"""Tool result formatting utilities.

This module provides utilities for formatting tool results for display
to the LLM in a human-readable format.
"""

import json
from typing import Any, Optional


def format_inline_tool_result(
    function_name: str, payload: Any, thought_footer_message: Optional[str] = None
) -> str:
    """Format a tool result for display to the LLM.

    Handles special formatting for specific tools (like shell_run) and
    provides generic formatting for other tools.

    Args:
        function_name: Name of the tool that produced the result.
        payload: The tool's result payload.
        thought_footer_message: When set, appended as a footer to shell_run results.

    Returns:
        Formatted string representation of the result.

    Example:
        result = format_inline_tool_result("shell_run", {"returncode": 0, "output": "hello"})
        # Returns: "Return code: 0\\nOutput: hello"
    """
    # Unwrap nested result structures
    if (
        isinstance(payload, dict)
        and "result" in payload
        and isinstance(payload["result"], dict)
    ):
        payload = payload["result"]

    if function_name == "shell_run":
        return _format_shell_run(payload, thought_footer_message=thought_footer_message)

    return _format_generic_result(payload)


def _format_shell_run(
    payload: Any, thought_footer_message: Optional[str] = None
) -> str:
    """Format shell_run tool result.

    Args:
        payload: The shell_run result containing returncode, output, and optionally error/warning.
        thought_footer_message: When set, appended after the output.

    Returns:
        Formatted string with return code, output, and any errors/warnings.
    """
    if not isinstance(payload, dict):
        return "Return code: None\nOutput: None"

    if "error" in payload:
        return f"Return code: {payload.get('returncode')}\nOutput: {payload.get('output')}\nError: {payload.get('error')}"

    if "warning" in payload:
        return f"Return code: {payload.get('returncode')}\nOutput: {payload.get('output')}\nWarning: {payload.get('warning')}"

    base = f"Return code: {payload.get('returncode')}\nOutput: {payload.get('output')}"
    if thought_footer_message:
        return base + f"\n\n{thought_footer_message}"
    return base


def _format_generic_result(payload: Any) -> str:
    """Format a generic tool result.

    Args:
        payload: Any tool result payload.

    Returns:
        Formatted string representation.
    """
    if payload is None:
        return "Result: None"

    if isinstance(payload, dict):
        try:
            rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
        except Exception:
            rendered = str(payload)
        return f"Result:\n{rendered}"

    return f"Result: {payload}"
