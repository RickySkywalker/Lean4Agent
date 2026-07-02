"""
Core interpreter that dispatches workflow steps to appropriate handlers.

This module provides the Interpreter class which is the main entry point
for executing YAML workflow steps. It combines dispatch logic with
step handler implementations via mixins.
"""

from typing import Any, Dict, Optional

from mcp_client.logger import Logger

from ..checkpoints.checkpoint_manager import CheckpointManager
from ..submodules.loader import load_submodule_tools_for_yaml
from ..utils.step_utils import get_step_depth, get_step_instruction

# Internal context keys to exclude from variable snapshots
_INTERNAL_KEYS = {
    "task_name",
    "task_output_dir",
    "goal",
    "workflow_file",
    "workflow_dir",
    "workflow_root",
    "conversation_history",
    "submodule_tools",
    "submodule_registry",
    "enabled_submodules",
    "expose_submodules_as_tools",
    "enabled_tools",
    "system_prompt",
    "code_path",
    "conda_env_name",
    "stop_on_return",
    "stop_on_submodule_result",
    "max_workflow_steps",
    "require_submodule_submit",
    "enable_inline_tool_calls",
    "inline_tool_calls_only",
    "allow_inline_tools_without_enable",
    "swebench_mode",
    "enable_git_filtering",
    "require_thought_section",
    "thought_missing_message",
    "thought_footer_message",
    "submit_reminder_message",
}


def _snapshot_variables(context: Dict[str, Any]) -> Dict[str, str]:
    """Extract user-defined variables from context for dashboard display."""
    out = {}
    for k, v in (context or {}).items():
        if k.startswith("_") or k in _INTERNAL_KEYS:
            continue
        s = str(v)
        out[k] = s
    return out


from .llm_executor import LLMExecutor
from .step_handlers import StepHandlersMixin


class Interpreter(StepHandlersMixin):
    """
    Main interpreter for executing YAML workflow steps.

    This class provides the dispatch logic for executing workflow steps,
    delegating actual step execution to handler methods inherited from
    StepHandlersMixin.

    Attributes:
        mcp_client: MCP client for tool invocation.
        tools: List of available tool definitions.
        llm_executor: LLMExecutor for running LLM completions.
        mcp_fs_write: Convenience function for writing files.
        mcp_fs_read: Convenience function for reading files.

    Example:
        interpreter = Interpreter(mcp_client, tools, openai_client)
        output, tokens = interpreter.execute_workflow_step(
            step_data, context, step_number, args, logger
        )
    """

    def __init__(self, mcp_client, tools, llm_client, usage_tracker=None):
        """
        Initialize the interpreter.

        Args:
            mcp_client: MCP client for tool invocation.
            tools: List of available tools.
            llm_client: LLMClient for LLM calls (supports multiple providers via LiteLLM).
            usage_tracker: Optional dict for tracking token usage.
                          If None, creates a default tracker.
        """
        if usage_tracker is None:
            usage_tracker = {
                "prompt_tokens_total": 0,
                "completion_tokens_total": 0,
                "reasoning_tokens_total": 0,
                "cost_total": 0.0,
            }

        self.mcp_client = mcp_client
        self.tools = tools

        # Convenience functions for file operations
        self.mcp_fs_write = self.mcp_client.make_mcp_tool_function(
            "fs_write", ["path", "content"]
        )
        self.mcp_fs_read = self.mcp_client.make_mcp_tool_function(
            "fs_read", ["path", "max_bytes"]
        )

        self.llm_executor: LLMExecutor = LLMExecutor(
            mcp_client=mcp_client,
            tools=tools,
            llm_client=llm_client,
            usage_tracker=usage_tracker,
        )
        # Set back-reference so LLMExecutor can delegate submodule calls
        self.llm_executor.interpreter = self

    def _load_submodule_tools_for_yaml(
        self, yaml_data: Dict[str, Any], yaml_file_path: str
    ):
        """Load submodule tools from a YAML file."""
        return load_submodule_tools_for_yaml(yaml_data, yaml_file_path)

    def execute_workflow_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ):
        """Execute a single workflow step based on its type.

        This is the main entry point for step execution. It logs step
        start/end events and dispatches to the appropriate handler.

        Args:
            step_data: Dictionary containing step configuration.
            context: Workflow context dictionary.
            step_number: Step identifier (can be hierarchical like "1.2.3").
            args: EffectiveArgs with execution configuration.
            logger: Logger for output and event logging.
            checkpoint_manager: Optional checkpoint manager for durability.

        Returns:
            Tuple of (output, tokens) where output is the step result
            and tokens is the number of tokens used.

        Raises:
            Exception: Any exception from step execution is re-raised
                      after logging the error.
        """
        if not isinstance(step_data, dict):
            logger(f"Unknown step type: {step_data}")
            step_id = str(step_number)
            logger.log_event(
                logger,
                "step_start",
                {
                    "step_id": step_id,
                    "step_number": step_id,
                    "name": f"unknown {step_id}",
                    "step_type": "unknown",
                    "instruction": "",
                    "depth": get_step_depth(step_id),
                },
            )
            logger.log_event(
                logger,
                "step_end",
                {
                    "step_id": step_id,
                    "tokens": 0,
                    "status": "error",
                    "error": "Invalid step format (expected mapping)",
                },
            )
            return "", 0

        step_id = str(step_number)
        # Detect step type from the key used in the YAML (e.g. "step", "synthesize", "task")
        _STEP_TYPE_KEYS = {
            "step",
            "task",
            "for_each",
            "if",
            "parallel",
            "while",
            "switch",
            "increment",
            "set_variable",
            "input",
            "call",
            "gather",
            "return",
        }
        step_type = next((k for k in step_data if k in _STEP_TYPE_KEYS), "")
        step_body = step_data.get(step_type) if step_type else {}
        if isinstance(step_body, dict):
            step_name = step_body.get("name", "")
        else:
            step_name = ""
        instruction = get_step_instruction(step_data, context)
        depth = get_step_depth(step_id)

        logger.log_event(
            logger,
            "step_start",
            {
                "step_id": step_id,
                "step_number": step_id,
                "name": step_name,
                "step_type": step_type,
                "instruction": instruction,
                "depth": depth,
                "variables": _snapshot_variables(context),
            },
        )

        try:
            output, tokens = self._dispatch_step(
                step_data, context, step_number, args, logger, checkpoint_manager
            )

            logger.log_event(
                logger,
                "step_end",
                {
                    "step_id": step_id,
                    "tokens": tokens,
                    "status": "completed",
                },
            )
            return output, tokens

        except Exception as e:
            logger.log_event(
                logger,
                "step_end",
                {
                    "step_id": step_id,
                    "tokens": 0,
                    "status": "error",
                    "error": str(e),
                },
            )
            raise

    def _dispatch_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ):
        """Dispatch to the appropriate step handler based on step type.

        Args:
            step_data: Dictionary containing step configuration.
            context: Workflow context dictionary.
            step_number: Step identifier.
            args: EffectiveArgs with execution configuration.
            logger: Logger for output.
            checkpoint_manager: Optional checkpoint manager.

        Returns:
            Tuple of (output, tokens) from the step handler.
        """
        if "step" in step_data:
            return self.execute_basic_step(
                step_data, context, step_number, args, logger
            )
        elif "task" in step_data:
            return self.execute_task_step(step_data, context, step_number, args, logger)
        elif "for_each" in step_data:
            return self.execute_for_each_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "if" in step_data:
            return self.execute_conditional_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "parallel" in step_data:
            return self.execute_parallel_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "while" in step_data:
            return self.execute_while_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "switch" in step_data:
            return self.execute_switch_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "increment" in step_data:
            return self.execute_increment_step(
                step_data, context, step_number, args, logger
            )
        elif "set_variable" in step_data:
            return self.execute_set_variable_step(
                step_data, context, step_number, args, logger
            )
        elif "input" in step_data:
            return self.execute_input_step(
                step_data, context, step_number, args, logger
            )
        elif "call" in step_data:
            return self.execute_call_step(
                step_data, context, step_number, args, logger, checkpoint_manager
            )
        elif "gather" in step_data:
            return self.execute_gather_step(
                step_data,
                context,
                step_number,
                args,
                logger,
                checkpoint_manager=checkpoint_manager,
            )
        elif "return" in step_data:
            return self.execute_return_step(
                step_data, context, step_number, args, logger
            )
        else:
            logger(f"Unknown step type: {step_data}")
            return "", 0


# Backward compatibility aliases
AgentInterpreterBase = Interpreter
AgentInterpreter = Interpreter
