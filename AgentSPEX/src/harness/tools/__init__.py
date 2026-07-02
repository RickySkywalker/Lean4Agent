"""Tool execution infrastructure for the agent framework.

This package provides components for tool execution, filtering, and formatting:
- EffectiveToolConfig: Compute effective tools for a step
- ToolExecutor: Execute tools via MCP client
- ToolResult: Result dataclass for tool execution
- Shell utilities: inject_shell_defaults, is_submit_command
- Formatting: format_tool_result, format_tool_call_message
"""

from .executor import ToolExecutor, ToolResult
from .filtering import EffectiveToolConfig
from .formatting import format_inline_tool_result
from .messages import format_tool_call_message, format_tool_result_message
from .shell import inject_shell_defaults, is_submit_command

__all__ = [
    # Filtering
    "EffectiveToolConfig",
    # Executor
    "ToolExecutor",
    "ToolResult",
    # Shell utilities
    "inject_shell_defaults",
    "is_submit_command",
    # Formatting
    "format_inline_tool_result",
    "format_tool_call_message",
    "format_tool_result_message",
]
