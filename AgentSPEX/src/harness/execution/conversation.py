"""Conversation history management for LLM execution.

This module provides utilities for managing conversation history during
workflow execution, including initialization and system prompt setup.
"""

from typing import Any, Dict, List, Optional

from ..prompts.yaml_prompts import (get_yaml_system_prompt,
                                    resolve_system_prompt)
from ..types.context import ContextKeys


def ensure_conversation_history(
    context: Dict[str, Any],
    args,
    system_prompt_override: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Initialize or retrieve conversation history from context.

    If conversation history doesn't exist, creates it with a system prompt.
    The system prompt is either provided directly or generated from context.

    Args:
        context: The workflow context dictionary
        args: EffectiveArgs with model configuration
        system_prompt_override: Optional custom system prompt

    Returns:
        List of conversation messages with system prompt as first message

    Example:
        history = ensure_conversation_history(context, args)
        history.append({"role": "user", "content": instruction})
    """
    history = context.get(ContextKeys.CONVERSATION_HISTORY)
    if history is None or not isinstance(history, list):
        history = []
    if not history:
        if system_prompt_override is not None:
            system_prompt = resolve_system_prompt(system_prompt_override, context)
        else:
            system_prompt = get_yaml_system_prompt(
                context.get(ContextKeys.TASK_NAME, "unknown"),
                context.get(ContextKeys.GOAL, ""),
                args,
                context,
            )
        if system_prompt:
            history.append({"role": "system", "content": system_prompt})
    context[ContextKeys.CONVERSATION_HISTORY] = history
    return history
