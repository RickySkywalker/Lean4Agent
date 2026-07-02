"""Basic step handlers for LLM-driven steps.

This module provides the fundamental step types that interact directly
with the LLM to execute instructions. Basic steps are the building blocks
for more complex workflow patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ...parsing.templates import expand_template_variables
from ...tools.filtering import EffectiveToolConfig
from ...types.context import ContextKeys
from ..conversation import ensure_conversation_history

if TYPE_CHECKING:
    from mcp_client.logger import Logger

    from ...types.config import EffectiveArgs


class BasicStepsMixin:
    """Mixin providing basic step and task step execution.

    These are the most common step types, used for direct LLM interactions
    with optional tool usage and conversation history management.

    Required Attributes:
        llm_executor: LLMExecutor for running LLM completions.
        tools: List of available tool definitions.
    """

    def execute_basic_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[Any, int]:
        """Execute a step with persistent conversation history.

        Steps maintain conversation history across iterations, enabling
        multi-turn interactions with tool use. Each step appends a new
        user message to the workflow-level conversation history and runs
        the model against that shared history.

        Args:
            step_data: Step configuration containing 'step' key with:
                - instruction: The prompt to send to the LLM (required)
                - name: Optional step name for logging
                - system_prompt: Ignored (use workflow-level instead)
                - save_as: Optional variable name to save output to context
            context: Current workflow context dictionary.
            step_number: Identifier for this step in the workflow.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.

        Returns:
            Tuple of (output, tokens) where output is the final LLM response
            and tokens is the total number of tokens used across all iterations.
        """
        step = step_data["step"]
        raw_name = step.get("name", f"step_{step_number}")
        name = expand_template_variables(raw_name, context)
        instruction = step["instruction"]
        expanded_instruction = expand_template_variables(instruction, context)
        logger(f"\n==== Executing step {step_number}: {name} ====")
        logger(f"Instruction: {expanded_instruction}")

        system_prompt = step.get("system_prompt")
        history = ensure_conversation_history(context, args)
        if system_prompt is not None:
            logger(
                "Step system_prompt is ignored; set system_prompt at the workflow level instead."
            )

        history.append({"role": "user", "content": expanded_instruction})
        working_messages = list(history)

        tool_config = EffectiveToolConfig.compute(self.tools, context, step)
        expose_submodules = context.get(ContextKeys.EXPOSE_SUBMODULES_AS_TOOLS, True)
        combined_tools = tool_config.tools + (
            tool_config.submodule_tools if expose_submodules else []
        )

        output, tokens = self.llm_executor.multi_step_tool_call_loop(
            step_number,
            working_messages,
            args,
            logger,
            tools=combined_tools,
            context=context,
            record_assistant_message=True,
            history_messages=history,
            allowed_submodule_names=tool_config.enabled_submodule_names,
        )

        save_as = step.get("save_as")
        if save_as:
            var_name = expand_template_variables(save_as, context)
            try:
                context[var_name] = eval(output)
            except Exception:
                context[var_name] = output
            logger(f"Saved output: {output} to context variable: {var_name}")

        return output, tokens

    def execute_task_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[Any, int]:
        """Execute a task as a fresh, stateless LLM call.

        Tasks send an instruction to the LLM and capture the response.
        They are stateless - each execution is independent without maintaining
        conversation history across tasks.

        Args:
            step_data: Step configuration containing 'task' key with:
                - instruction: The prompt to send to the LLM (required)
                - name: Optional task name for logging
                - system_prompt: Optional custom system prompt
                - save_as: Optional variable name to save output to context
            context: Current workflow context dictionary.
            step_number: Identifier for this step in the workflow.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.

        Returns:
            Tuple of (output, tokens) where output is the LLM response
            and tokens is the number of tokens used.
        """
        task = step_data["task"]
        # Expand template variables in name and instruction
        raw_name = task.get("name", f"task_{step_number}")
        name = expand_template_variables(raw_name, context)
        instruction = task["instruction"]
        expanded_instruction = expand_template_variables(instruction, context)
        system_prompt = task.get("system_prompt")

        logger(f"\n==== Executing task {step_number}: {name} ====")
        logger(f"Instruction: {expanded_instruction}")

        output, tokens = self.llm_executor.execute_llm_step(
            expanded_instruction,
            context.get(ContextKeys.PREV_OUTPUT, ""),
            step_number,
            args,
            logger,
            context,
            system_prompt=system_prompt,
            step_config=task,
        )

        # Save result into working context
        save_as = task.get("save_as")
        if save_as:
            var_name = expand_template_variables(save_as, context)
            try:
                context[var_name] = eval(output)
            except Exception:
                context[var_name] = output
            logger(f"Saved output: {output} to context variable: {var_name}")

        return output, tokens
