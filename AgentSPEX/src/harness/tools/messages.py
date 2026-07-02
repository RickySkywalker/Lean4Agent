"""Tool message formatting utilities.

This module provides utilities for formatting tool calls and results
into the message format expected by the LLM conversation.
"""

from typing import Any, Dict


def format_tool_call_message(tool_call: Any) -> Dict[str, Any]:
    """Format a tool call into a message format.

    Converts an LLM tool call response object into a dictionary
    format suitable for conversation history.

    Args:
        tool_call: The tool call object from LLM response.

    Returns:
        Formatted tool call dict for message history.

    Example:
        tool_call_dict = format_tool_call_message(response.tool_calls[0])
        messages.append({"role": "assistant", "tool_calls": [tool_call_dict]})
    """
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def format_tool_result_message(
    tool_call_id: str,
    tool_name: str,
    content: str,
) -> Dict[str, Any]:
    """Format a tool result into a message format.

    Creates a tool result message suitable for adding to conversation
    history after a tool has been executed.

    Args:
        tool_call_id: ID of the tool call being responded to.
        tool_name: Name of the tool that was executed.
        content: Result content (usually JSON string).

    Returns:
        Formatted tool result message.

    Example:
        result_msg = format_tool_result_message(
            tool_call_id="call_123",
            tool_name="shell_run",
            content='{"returncode": 0, "output": "hello"}'
        )
        messages.append(result_msg)
    """
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": content,
    }
