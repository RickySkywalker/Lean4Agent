"""Effective tool configuration computation.

This module provides utilities for computing the effective set of tools
and submodules available for a given workflow step, taking into account
both plan-level and step-level filtering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from ..types.context import ContextKeys
from ..types.serialization import get_tool_name


@dataclass
class EffectiveToolConfig:
    """Computed effective tools and submodules for a specific context and step.

    This class encapsulates the logic for determining which tools and submodules
    are available for a given step, applying both plan-level and step-level
    filtering rules.

    Attributes:
        tools: List of effective tool definitions after filtering.
        submodule_tools: List of effective submodule tool definitions.
        enabled_submodule_names: List of submodule names that are enabled.

    Example:
        config = EffectiveToolConfig.compute(
            all_tools=agent.tools,
            context=workflow_context,
            step_config=step.get("task", {}),
        )
        available_tools = config.tools + config.submodule_tools
    """

    tools: List[Dict[str, Any]]
    submodule_tools: List[Dict[str, Any]]
    enabled_submodule_names: List[str]

    @classmethod
    def compute(
        cls,
        all_tools: List[Dict[str, Any]],
        context: Dict[str, Any],
        step_config: Optional[Dict[str, Any]] = None,
    ) -> EffectiveToolConfig:
        """Compute effective tool configuration for a step.

        Applies filtering rules to determine which tools and submodules
        are available for the current step:
        - If both plan and step specify enabled tools, uses intersection
        - If only one specifies, uses that list
        - If neither specifies, all tools are available

        Args:
            all_tools: Complete list of available tool definitions.
            context: Workflow context containing plan-level settings.
            step_config: Optional step-specific configuration.

        Returns:
            EffectiveToolConfig with filtered tools and submodules.
        """

        def normalize_enabled_list(value: Any) -> Optional[List[str]]:
            if value is None:
                return None
            if isinstance(value, (list, tuple, set)):
                return [str(v) for v in value]
            return [str(value)]

        def compute_effective_set(
            plan_key: str,
            step_key: str,
        ) -> Optional[Set[str]]:
            """Compute effective enabled set from plan and step configs."""
            plan_enabled = normalize_enabled_list(context.get(plan_key))
            step_enabled = (
                normalize_enabled_list(step_config.get(step_key))
                if step_config
                else None
            )

            if plan_enabled is not None and step_enabled is not None:
                return set(plan_enabled) & set(step_enabled)
            elif step_enabled is not None:
                return set(step_enabled)
            elif plan_enabled is not None:
                return set(plan_enabled)
            return None

        # Compute effective tools
        tools_enabled = compute_effective_set(
            ContextKeys.ENABLED_TOOLS, ContextKeys.ENABLED_TOOLS
        )
        if tools_enabled is None:
            effective_tools = all_tools
        else:
            effective_tools = [
                tool for tool in all_tools if get_tool_name(tool) in tools_enabled
            ]

        # Compute effective submodule tools
        available_submodule_tools = context.get(ContextKeys.SUBMODULE_TOOLS, [])
        submodules_enabled = compute_effective_set(
            ContextKeys.ENABLED_SUBMODULES, ContextKeys.ENABLED_SUBMODULES
        )
        if not available_submodule_tools:
            effective_submodule_tools = []
        elif submodules_enabled is None:
            effective_submodule_tools = available_submodule_tools
        else:
            effective_submodule_tools = [
                tool
                for tool in available_submodule_tools
                if get_tool_name(tool) in submodules_enabled
            ]

        # Compute enabled submodule names
        submodule_registry = context.get(ContextKeys.SUBMODULE_REGISTRY) or {}
        available_names = list(submodule_registry.keys())
        if not available_names and context.get(ContextKeys.SUBMODULE_TOOLS):
            available_names = [
                get_tool_name(tool)
                for tool in context.get(ContextKeys.SUBMODULE_TOOLS, [])
                if get_tool_name(tool)
            ]

        if not available_names:
            enabled_submodule_names = []
        elif submodules_enabled is None:
            enabled_submodule_names = available_names
        else:
            enabled_submodule_names = [
                name for name in available_names if name in submodules_enabled
            ]

        return cls(
            tools=effective_tools,
            submodule_tools=effective_submodule_tools,
            enabled_submodule_names=enabled_submodule_names,
        )
