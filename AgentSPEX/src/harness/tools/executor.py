"""Execute tool calls via MCP client.

This module provides a structured way to execute tools and handle their results,
with support for both regular MCP tools and submodule function calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from mcp_client.client import MCPClient


@dataclass
class ToolResult:
    """Result of executing a tool.

    Encapsulates the outcome of a tool execution, including success/failure
    status, output data, and any error information.

    Attributes:
        tool_name: Name of the executed tool.
        tool_args: Arguments that were passed to the tool.
        success: Whether the tool executed successfully.
        output: The tool's output if successful, None otherwise.
        error: Error message if execution failed, None otherwise.
        is_submodule: Whether this was a submodule function call.

    Example:
        result = executor.execute("shell_run", {"command": "ls"})
        if result.success:
            print(f"Output: {result.output}")
        else:
            print(f"Error: {result.error}")
    """

    tool_name: str
    tool_args: Dict[str, Any]
    success: bool
    output: Any = None
    error: Optional[str] = None
    is_submodule: bool = False

    def __str__(self) -> str:
        """Return a human-readable representation."""
        status = "success" if self.success else "failed"
        return f"ToolResult({self.tool_name}, {status})"


class ToolExecutor:
    """Executes tools via MCP client with consistent error handling.

    Provides a unified interface for executing both regular MCP tools
    and submodule function calls, with consistent result handling.

    Attributes:
        mcp_client: The MCP client used for tool invocation.
        submodule_registry: Dictionary mapping submodule names to their specs.

    Example:
        executor = ToolExecutor(mcp_client, submodule_registry)
        result = executor.execute("fs_write", {"path": "/tmp/test.txt", "content": "hello"})
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        submodule_registry: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the tool executor.

        Args:
            mcp_client: MCP client for invoking tools.
            submodule_registry: Optional mapping of submodule names to specs.
        """
        self.mcp_client = mcp_client
        self.submodule_registry: Dict[str, Any] = submodule_registry or {}

    def execute(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        is_catch_exception: bool = False,
    ) -> ToolResult:
        """Execute a single tool and return the result.

        Args:
            tool_name: Name of the tool to execute.
            tool_args: Arguments for the tool.
            is_catch_exception: Whether to catch exceptions internally
                               (passed to MCP client).

        Returns:
            ToolResult containing the execution outcome.
        """
        is_submodule = tool_name in self.submodule_registry

        try:
            output = self.mcp_client.invoke(
                tool_name,
                tool_args,
                is_catch_exception=is_catch_exception,
            )
            return ToolResult(
                tool_name=tool_name,
                tool_args=tool_args,
                success=True,
                output=output,
                is_submodule=is_submodule,
            )
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                tool_args=tool_args,
                success=False,
                error=str(e),
                is_submodule=is_submodule,
            )

    def is_submodule_tool(self, tool_name: str) -> bool:
        """Check if a tool name corresponds to a submodule.

        Args:
            tool_name: The tool name to check.

        Returns:
            True if the tool is a registered submodule.
        """
        return tool_name in self.submodule_registry
