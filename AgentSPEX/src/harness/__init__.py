"""Agent - YAML-based workflow execution framework.

This package provides a framework for executing YAML-defined workflows
using LLMs and tools via the MCP (Model Context Protocol).

Main Entry Points:
    AgentSPEX: Main orchestrator for YAML workflow execution
    EffectiveArgs: Configuration dataclass for agent settings

Example:
    from harness import AgentSPEX, EffectiveArgs

    agent = AgentSPEX(mcp_url="http://localhost:8080")
    result = agent.run(args)
"""

from .agent import AgentSPEX
from .types.config import EffectiveArgs

__all__ = ["AgentSPEX", "EffectiveArgs"]
