"""Submodule and parallel step handlers for calling sub-workflows.

This module provides steps for calling other YAML workflows as submodules,
enabling modular, reusable workflow composition. Supports both sequential
calls, parallel execution via gather steps, and parallel step execution.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from ...checkpoints.checkpoint_manager import CheckpointManager
from ...parsing.templates import expand_template_variables
from ...parsing.yaml_parser import YAMLTaskParser
from ...types.config import EffectiveArgs
from ..conversation import ensure_conversation_history
from ..llm_executor import ToolCallLimitExceeded
from .control import _mark_substep_completed, _skip_completed_substep

if TYPE_CHECKING:
    from mcp_client.logger import Logger


class SubmoduleStepsMixin:
    """Mixin providing submodule call and gather steps.

    These steps enable workflow composition by calling other YAML workflows
    as reusable submodules with parameter passing and result capture.

    Required Attributes:
        mcp_fs_write: Callable for writing files via MCP.
        _load_submodule_tools_for_yaml: Callable to load submodule tools.
        execute_workflow_step: Method for recursive step execution.
    """

    def execute_call_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: Union[EffectiveArgs, Any],
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[Any, int]:
        """Execute a sub-module workflow.

        Calls another YAML workflow file as a reusable sub-module with
        parameter passing. The sub-module runs in an isolated context
        and can return values to the parent workflow.

        Args:
            step_data: Contains 'call' key with:
                - module: Path to the YAML workflow file
                - parameters: Dict of parameters to pass
                - save_as: Variable name to save result
                - return: Variable to return (default: prev_output)
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for resume support.

        Returns:
            Tuple of (result, total_tokens) from the submodule execution.

        Raises:
            RuntimeError: If maximum recursion depth is exceeded.
        """
        # Check if this call step is already completed (for gather/parallel resume support)
        step_id_str = str(step_number)
        if checkpoint_manager and checkpoint_manager.is_completed(step_id_str):
            logger(f"Skipping completed call step {step_id_str}")
            # Try to restore result from saved output
            # For gather calls like "2.g1", check if we have saved output
            # Look in the submodule-specific directory where it was saved
            output_file = (
                Path(context.get("task_output_dir", "."))
                / f"submodule_{step_id_str}"
                / f"step-{step_id_str.replace('.', '-')}-output.txt"
            )
            if not output_file.exists():
                # Fallback to parent directory (for top-level calls)
                output_file = (
                    Path(context.get("task_output_dir", "."))
                    / f"step-{step_id_str.replace('.', '-')}-output.txt"
                )

            if output_file.exists():
                saved_text = output_file.read_text(encoding="utf-8")
                # Try to deserialize back to original type (list, dict, etc.)
                saved_result: Any = saved_text
                try:
                    saved_result = json.loads(saved_text)
                except (json.JSONDecodeError, ValueError):
                    try:
                        saved_result = ast.literal_eval(saved_text)
                    except (ValueError, SyntaxError):
                        pass  # Keep as string
                logger(f"Restored result from {output_file}")
                return saved_result, 0
            # Fallback: return empty result
            return f"[Restored from checkpoint: step {step_id_str}]", 0

        call_config = step_data["call"]
        module_path = expand_template_variables(call_config["module"], context)
        if module_path and not Path(module_path).is_absolute():
            # Smart path resolution:
            # - Paths starting with "modules/" or "workflows/" resolve relative to workflow_root
            # - Other relative paths resolve relative to workflow_dir (current file's directory)
            if module_path.startswith(("modules/", "workflows/")):
                base_dir = context.get("workflow_root", context.get("workflow_dir"))
            else:
                base_dir = context.get("workflow_dir")

            if not base_dir:
                base_file = context.get("workflow_file")
                if base_file:
                    base_dir = str(Path(base_file).resolve().parent)
            # Prefer resolving relative to workflow_dir, but fall back to cwd (project root)
            cand_task_dir = (
                str((Path(base_dir) / module_path).resolve()) if base_dir else None
            )
            cand_cwd = str(Path(module_path).resolve())
            if cand_task_dir and Path(cand_task_dir).exists():
                module_path = cand_task_dir
            elif Path(cand_cwd).exists():
                module_path = cand_cwd
            elif cand_task_dir:
                module_path = cand_task_dir
        params = call_config.get("parameters", {})
        save_as = call_config.get("save_as")
        return_var = call_config.get(
            "return", "prev_output"
        )  # Which variable from sub-module to return

        logger(f"\n==== Calling sub-module {step_number}: {module_path} ====")
        logger(f"Parameters: {params}")
        logger.log_event(
            logger,
            "module_start",
            {
                "step_id": str(step_number),
                "name": module_path,
                "path": module_path,
                "params": params,
            },
        )

        # Check recursion depth to prevent infinite loops
        current_depth = context.get("_call_depth", 0)
        max_depth = context.get("recursion_max_depth", 10)  # Maximum nesting depth
        if current_depth >= max_depth:
            error_msg = f"Maximum call depth ({max_depth}) exceeded. Possible infinite recursion."
            logger(f"ERROR: {error_msg}")
            logger.log_event(
                logger,
                "module_end",
                {
                    "step_id": str(step_number),
                    "name": module_path,
                    "result": error_msg,
                    "status": "error",
                },
            )
            return error_msg, 0

        # Expand parameter values from current context
        expanded_params = {}
        for key, value in params.items():
            expanded_params[key] = expand_template_variables(str(value), context)

        logger(f"Expanded parameters: {expanded_params}")

        # Load sub-module YAML
        sub_parser = YAMLTaskParser()

        # Set environment variables for sub-module parameters
        original_env = {}
        for key, value in expanded_params.items():
            env_key = key.upper()
            original_env[env_key] = os.environ.get(env_key)
            os.environ[env_key] = str(value)

        try:
            # Load and validate sub-module
            yaml_data = sub_parser.load_task(module_path)
            submodule_tools, submodule_registry = self._load_submodule_tools_for_yaml(
                yaml_data, module_path
            )

            # Create effective args for submodule with per-file config support
            # Convert parent args to EffectiveArgs if needed
            parent_effective_args = (
                args
                if isinstance(args, EffectiveArgs)
                else EffectiveArgs.from_args(args)
            )

            # Check if submodule has its own config section
            submodule_config = yaml_data.get("config", {})
            if submodule_config:
                # Submodule has its own config - apply overrides
                effective_args = parent_effective_args.with_yaml_config(
                    submodule_config
                )
                logger(
                    f"Submodule using custom config: model={effective_args.model}, "
                    f"max_tokens={effective_args.max_tokens_per_step}"
                )
            else:
                # No config in submodule - inherit from parent
                effective_args = parent_effective_args
                logger(
                    f"Submodule inheriting parent config: model={effective_args.model}"
                )

            # Create isolated context for sub-module
            sub_context = {
                "task_name": yaml_data["name"],
                "goal": yaml_data["goal"],
                "task_output_dir": f"{context['task_output_dir']}/submodule_{step_number}",
                "sandbox_output_dir": f"{context.get('sandbox_output_dir', context['task_output_dir'])}/submodule_{step_number}",
                "prev_output": context.get("prev_output", ""),
                "submodule_tools": submodule_tools,
                "submodule_registry": submodule_registry,
                "workflow_file": module_path,
                "workflow_dir": str(Path(module_path).resolve().parent),
                "workflow_root": context.get(
                    "workflow_root", str(Path(module_path).resolve().parent)
                ),  # Inherit root from parent
                "_call_depth": current_depth + 1,  # Track recursion depth
                "_parent_context": context,  # Reference to parent (for advanced use cases)
                "stop_on_submodule_result": True,
                "stop_on_return": True,
            }

            # Add sub-module parameters
            if "parameters" in yaml_data:
                sub_context.update(yaml_data["parameters"])
            # Override with parent-provided parameters (expanded)
            if expanded_params:
                sub_context.update(expanded_params)

            # Allow sub-module to override the default system prompt
            sub_system_prompt = yaml_data.get("system_prompt")
            if sub_system_prompt:
                sub_context["system_prompt"] = sub_system_prompt

            # Copy config keys to sub_context (same keys as in agent.run_yaml_task)
            CONFIG_KEYS = [
                "enabled_tools",
                "enabled_submodules",
                "expose_submodules_as_tools",
                "allow_inline_tools_without_enable",
                "inline_tool_calls_only",
                "enable_inline_tool_calls",
                # Note: stop_on_return is already set to True above
                "max_workflow_steps",
                "swebench_mode",
                "enable_git_filtering",
                "require_thought_section",
                "thought_missing_message",
                "thought_footer_message",
                "submit_reminder_message",
            ]
            for key in CONFIG_KEYS:
                if key in submodule_config:
                    sub_context[key] = submodule_config[key]
                elif key in yaml_data:
                    sub_context[key] = yaml_data[key]
                elif key in context:
                    sub_context[key] = context[key]

            if sub_context.get("swebench_mode"):
                sub_context.setdefault("enable_git_filtering", True)
                sub_context.setdefault("require_thought_section", True)

            ensure_conversation_history(sub_context, effective_args)

            logger(f"Sub-module context initialized: {list(sub_context.keys())}")
            logger(f"Executing {len(yaml_data['workflow'])} steps in sub-module")

            # Execute sub-module workflow with effective_args
            total_tokens = 0
            for i, sub_step_data in enumerate(yaml_data["workflow"], 1):
                sub_step_id = f"{step_number}.{i}"

                # Check for completion — respects _ALWAYS_REENTER / _ALWAYS_REEXECUTE
                saved = _skip_completed_substep(
                    sub_step_id, sub_step_data, checkpoint_manager, sub_context, logger
                )
                if saved is not None:
                    # Also try to restore prev_output from file (richer than substep_outputs)
                    step_out_file = (
                        Path(sub_context["task_output_dir"]) / f"step-{i}-output.txt"
                    )
                    if step_out_file.exists():
                        sub_context["prev_output"] = step_out_file.read_text(
                            encoding="utf-8"
                        )
                    else:
                        sub_context["prev_output"] = saved
                    continue

                output, tokens = self.execute_workflow_step(
                    sub_step_data,
                    sub_context,
                    sub_step_id,
                    effective_args,
                    logger,
                    checkpoint_manager=checkpoint_manager,
                )
                sub_context["prev_output"] = output
                total_tokens += tokens

                # Write local step output (sandbox + host mirror)
                step_filename = f"step-{i}-output.txt"
                sandbox_dir = sub_context.get(
                    "sandbox_output_dir", sub_context["task_output_dir"]
                )
                self.mcp_fs_write(f"{sandbox_dir}/{step_filename}", output)

                # Update checkpoint
                host_step_path = f"{sub_context['task_output_dir']}/{step_filename}"
                _mark_substep_completed(
                    sub_step_id, output, sub_step_data, checkpoint_manager
                )
                if checkpoint_manager:
                    checkpoint_manager.best_effort_host_write_text(
                        host_step_path, output, append=False
                    )

            # Get return value from sub-module context
            result = sub_context.get(return_var, sub_context["prev_output"])

            # Save result to parent context if requested
            if save_as:
                var_name = expand_template_variables(save_as, context)
                context[var_name] = result
                logger(f"Saved sub-module output to parent context: {var_name}")

            logger(f"Sub-module completed successfully. Total tokens: {total_tokens}")
            logger(f"Returned value: {result}")
            logger.log_event(
                logger,
                "module_end",
                {
                    "step_id": str(step_number),
                    "name": module_path,
                    "result": result,
                    "status": "completed",
                },
            )

            # Mark the call step as completed for resume support
            if checkpoint_manager:
                # Save output for later restoration
                output_file = (
                    Path(sub_context.get("task_output_dir", "."))
                    / f"step-{str(step_number).replace('.', '-')}-output.txt"
                )
                try:
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    # Serialize as JSON if possible to preserve type on restore
                    try:
                        result_text = json.dumps(result, ensure_ascii=False)
                    except (TypeError, ValueError):
                        result_text = str(result)
                    output_file.write_text(result_text, encoding="utf-8")
                except Exception:
                    pass
                checkpoint_manager.mark_completed(
                    step_id=str(step_number),
                    context=None,
                    artifacts=None,
                    update_context=False,
                )

            return result, total_tokens

        except ToolCallLimitExceeded:
            raise
        except Exception as e:
            error_msg = f"Error executing sub-module {module_path}: {str(e)}"
            logger(f"ERROR: {error_msg}")
            tb = traceback.format_exc()
            logger(f"Traceback: {tb}")
            logger.log_event(
                logger,
                "module_end",
                {
                    "step_id": str(step_number),
                    "name": module_path,
                    "result": error_msg,
                    "status": "error",
                    "traceback": tb,
                },
            )
            return error_msg, 0

        finally:
            # Restore original environment
            for key, original_value in original_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value
            logger(f"Environment variables restored")

    def execute_gather_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: Union[EffectiveArgs, Any],
        logger: Logger,
        list_of_submodule_params: Optional[List[Dict[str, Any]]] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute multiple sub-module calls in parallel and gather results.

        Uses ThreadPoolExecutor for true parallel execution of submodule calls.
        Each call runs in an isolated context copy to avoid interference.

        Args:
            step_data: Contains 'gather' key with:
                - calls: List of call configs (module, parameters, save_as)
                - module: Single module path (when using list_of_submodule_params)
                - save_results_as: Variable to save all results as dict
                - max_workers: Maximum parallel threads (default: len(calls))
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            list_of_submodule_params: Optional parameter list for calling same
                module with different parameters.
            checkpoint_manager: Optional checkpoint manager for resume support.

        Returns:
            Tuple of (summary, total_tokens) where summary describes the
            gathered results and total_tokens is the sum across all calls.
        """
        gather_config = step_data["gather"]

        # Use list_of_submodule_params if provided
        if list_of_submodule_params is not None:
            if "module" not in gather_config:
                raise ValueError(
                    "gather must specify 'module' when using list_of_submodule_params"
                )

            module_path = gather_config["module"]
            calls = []
            for i, params in enumerate(list_of_submodule_params):
                calls.append(
                    {
                        "module": module_path,
                        "parameters": params,
                        "save_as": f"result_{i+1}",
                    }
                )
            save_results_as = gather_config.get("save_results_as")
            max_workers = gather_config.get("max_workers", len(calls))
        else:
            # Use YAML config
            calls = gather_config.get("calls", [])
            save_results_as = gather_config.get("save_results_as")
            max_workers = gather_config.get("max_workers", len(calls))

        logger(
            f"\n==== Executing gather step {step_number}: {len(calls)} PARALLEL calls ===="
        )
        logger(f"Max workers: {max_workers}")

        # Thread-safe lock for logging
        log_lock = threading.Lock()

        def execute_single_call(call_index, call_config):
            """Execute a single call in a separate thread"""
            call_step_data = {"call": call_config}

            with log_lock:
                logger(
                    f"\n--- [Thread-{call_index+1}] Starting gather call {call_index+1}/{len(calls)} ---"
                )
                logger.log_event(
                    logger,
                    "parallel_call_start",
                    {
                        "step_id": str(step_number),
                        "call": call_index + 1,
                        "name": call_config.get("module", ""),
                        "params": call_config.get("parameters", {}),
                    },
                )

            # Create a deep copy of context for each parallel call to avoid interference
            parallel_context = copy.deepcopy(context)

            # Execute the call
            try:
                result, tokens = self.execute_call_step(
                    call_step_data,
                    parallel_context,
                    f"{step_number}.g{call_index+1}",
                    args,
                    logger,
                    checkpoint_manager,
                )

                save_as = call_config.get("save_as")
                if save_as:
                    var_name = expand_template_variables(save_as, context)
                else:
                    var_name = f"gather_result_{call_index+1}"

                with log_lock:
                    logger(
                        f"--- [Thread-{call_index+1}] Completed: {var_name} ({tokens} tokens) ---"
                    )
                    logger.log_event(
                        logger,
                        "parallel_call_end",
                        {
                            "step_id": str(step_number),
                            "call": call_index + 1,
                            "name": call_config.get("module", ""),
                            "result": result,
                            "status": "completed",
                        },
                    )

                return {
                    "index": call_index,
                    "var_name": var_name,
                    "result": result,
                    "tokens": tokens,
                    "success": True,
                    "error": None,
                }

            except ToolCallLimitExceeded:
                raise
            except Exception as e:
                save_as = call_config.get("save_as", f"gather_result_{call_index+1}")
                error_msg = f"Error: {str(e)}"

                with log_lock:
                    logger(
                        f"--- [Thread-{call_index+1}] Error in gather call {call_index+1}: {str(e)} ---"
                    )
                    logger.log_event(
                        logger,
                        "parallel_call_end",
                        {
                            "step_id": str(step_number),
                            "call": call_index + 1,
                            "name": call_config.get("module", ""),
                            "result": error_msg,
                            "status": "error",
                        },
                    )

                return {
                    "index": call_index,
                    "var_name": save_as,
                    "result": error_msg,
                    "tokens": 0,
                    "success": False,
                    "error": str(e),
                }

        # Execute all calls in parallel using ThreadPoolExecutor
        results = {}
        total_tokens = 0

        logger(f"\n🚀 Starting {len(calls)} parallel executions...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_index = {
                executor.submit(execute_single_call, i, call_config): i
                for i, call_config in enumerate(calls)
            }

            # Collect results as they complete
            completed_count = 0
            for future in as_completed(future_to_index):
                try:
                    call_result = future.result()
                except ToolCallLimitExceeded:
                    for f in future_to_index:
                        f.cancel()
                    raise
                completed_count += 1

                # Update context and results
                var_name = call_result["var_name"]
                context[var_name] = call_result["result"]
                results[var_name] = call_result["result"]
                total_tokens += call_result["tokens"]

                with log_lock:
                    logger(
                        f"\n✓ Progress: {completed_count}/{len(calls)} calls completed"
                    )

        logger(f"\n✅ All {len(calls)} parallel calls completed!")

        # Save all results as a dictionary if requested
        if save_results_as:
            var_name = expand_template_variables(save_results_as, context)
            context[var_name] = results
            logger(f"Saved all gather results to context variable: {var_name}")

        # Create a summary output
        summary_lines = [
            f"Gather step completed: {len(calls)} calls executed in parallel"
        ]
        for key, value in results.items():
            value_preview = (
                str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            )
            summary_lines.append(f"  - {key}: {value_preview}")

        summary = "\n".join(summary_lines)
        logger(f"\n{summary}")
        logger(f"Total tokens used in gather: {total_tokens}")

        return summary, total_tokens

    def execute_parallel_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: Union[EffectiveArgs, Any],
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute steps or submodule calls in parallel.

        Supports two execution formats:
        1. List of different steps executed concurrently
        2. Single module called with different parameter sets

        Args:
            step_data: Contains 'parallel' key with either:
                - List of steps to execute in parallel, OR
                - Dict with 'module' and 'parameters_list' keys
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for resume support.

        Returns:
            Tuple of (combined_output, total_tokens) from all parallel executions.

        Example YAML (format 1):
            parallel:
              - step:
                  instruction: "Do task A"
              - step:
                  instruction: "Do task B"

        Example YAML (format 2):
            parallel:
              module: "modules/process.yaml"
              parameters_list: [{'input': 'a'}, {'input': 'b'}]
        """
        parallel_config = step_data["parallel"]

        # Check if it's the new format (module + parameters_list)
        if (
            isinstance(parallel_config, dict)
            and "module" in parallel_config
            and "parameters_list" in parallel_config
        ):
            # New format: parallel submodule calls with different params
            # Delegate to gather
            gather_step_data = {
                "gather": {
                    "module": parallel_config["module"],
                    "save_as_list": parallel_config.get("save_as_list", []),
                    "save_results_as": parallel_config.get("save_results_as"),
                    "max_workers": int(
                        context.get(
                            parallel_config.get("max_workers"),
                            parallel_config.get("max_workers"),
                        )
                    ),
                }
            }

            params_list = parallel_config["parameters_list"]
            # Expand if it's a context variable reference
            if isinstance(params_list, str):
                var_name = (
                    expand_template_variables(params_list, context).strip("{}").strip()
                )
                params_list = context.get(var_name, [])

            return self.execute_gather_step(
                gather_step_data,
                context,
                step_number,
                args,
                logger,
                list_of_submodule_params=params_list,
                checkpoint_manager=checkpoint_manager,
            )
        else:
            # Original format: parallel different steps (sequential execution for now)
            parallel_steps = parallel_config

            logger(f"\n==== Executing parallel steps {step_number} ====")

            all_outputs = []
            total_tokens = 0

            for i, sub_step in enumerate(parallel_steps):
                # Create separate context for each parallel step
                parallel_context = copy.deepcopy(context)
                output, tokens = self.execute_workflow_step(
                    sub_step,
                    parallel_context,
                    f"{step_number}.p{i+1}",
                    args,
                    logger,
                    checkpoint_manager=checkpoint_manager,
                )
                total_tokens += tokens
                all_outputs.append(output)

            combined_output = "\n\n".join(all_outputs)
            return combined_output, total_tokens
