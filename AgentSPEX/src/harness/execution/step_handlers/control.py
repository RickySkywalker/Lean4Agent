"""Control flow step handlers for loops and conditionals.

This module provides step types that control execution flow:
- for_each: Iterate over a list of items
- if/else: Conditional branching
- while: Loop while a condition is true
- switch: Multi-way branching based on variable value
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from ...parsing.conditions import evaluate_condition
from ...parsing.templates import expand_template_variables
from ...types.serialization import safe_json_dumps

if TYPE_CHECKING:
    from mcp_client.logger import Logger

    from ...checkpoints.checkpoint_manager import CheckpointManager
    from ...types.config import EffectiveArgs


# Step types that are cheap and must re-execute to correctly modify context.
# Never skip these — just let them run again.
_ALWAYS_REEXECUTE = frozenset({"set_variable", "increment"})

# Control-flow container steps that must always be *re-entered* on resume.
# They build context through their sub-steps (set_variable, save_as, etc.),
# so skipping the container entirely would lose those context mutations.
# Internal sub-steps have their own skip/mark logic.
_ALWAYS_REENTER = frozenset({"for_each", "while", "if", "switch", "parallel", "gather"})


def _step_type(step_data: Dict[str, Any]) -> Optional[str]:
    """Return the step type key (e.g. 'step', 'input', 'set_variable')."""
    for key in step_data:
        if key != "step_type":
            return key
    return None


def _get_save_as(step_data: Dict[str, Any]) -> Optional[str]:
    """Extract the ``save_as`` variable name from any step type."""
    for key in ("step", "input", "call", "task"):
        inner = step_data.get(key)
        if isinstance(inner, dict) and "save_as" in inner:
            return inner["save_as"]
    return None


def _skip_completed_substep(
    step_id: str,
    step_data: Dict[str, Any],
    checkpoint_manager: Optional[CheckpointManager],
    context: Dict[str, Any],
    logger: Logger,
) -> Optional[str]:
    """If *step_id* is already completed in the checkpoint, return its saved
    output (or "" if none was stored).  Otherwise return ``None`` to signal
    that the step still needs to execute.

    Also processes ``save_as`` so downstream steps can reference the variable.
    Steps in ``_ALWAYS_REEXECUTE`` are never skipped.
    """
    if checkpoint_manager is None:
        return None
    # Cheap context-modifying steps must always re-run
    stype = _step_type(step_data)
    if stype in _ALWAYS_REEXECUTE:
        return None
    # Control-flow containers must always be re-entered so their inner
    # sub-steps can rebuild context (set_variable, save_as, etc.)
    if stype in _ALWAYS_REENTER:
        return None
    if not checkpoint_manager.is_completed(step_id):
        return None
    saved = checkpoint_manager.get_substep_output(step_id)
    output = saved if saved is not None else ""
    logger(f"[Checkpoint] Skipping completed sub-step {step_id}")

    # Restore save_as variable into context
    save_as = _get_save_as(step_data)
    if save_as and output:
        var_name = expand_template_variables(save_as, context)
        try:
            context[var_name] = eval(output)
        except Exception:
            context[var_name] = output
        logger(f"[Checkpoint] Restored context variable: {var_name}")

    return output


def _mark_substep_completed(
    step_id: str,
    output: str,
    step_data: Dict[str, Any],
    checkpoint_manager: Optional[CheckpointManager],
) -> None:
    """Mark a sub-step as completed and persist its output.

    For ``input`` steps, an empty output means the user likely did not
    provide any input (e.g. EOF / interrupt).  In that case we do NOT
    mark the step completed so it will be re-prompted on resume.
    """
    if checkpoint_manager is None:
        return
    # Guard: don't checkpoint an input step that returned empty
    if _step_type(step_data) == "input" and not output:
        return
    checkpoint_manager.mark_completed(step_id)
    checkpoint_manager.save_substep_output(step_id, output)


class ControlFlowMixin:
    """Mixin providing control flow steps: for_each, if/else, while, switch.

    These steps enable complex workflow patterns by allowing iteration,
    conditional execution, and multi-way branching.

    Required Attributes:
        execute_workflow_step: Method for recursive step execution.
    """

    def execute_for_each_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute a for_each loop over items.

        Iterates over a list, executing nested steps for each item.
        The current item is made available in context via the variable name.

        Args:
            step_data: Step configuration containing 'for_each' key with:
                - variable: Name of the loop variable
                - in: List to iterate over (or context variable name)
                - steps: List of steps to execute per iteration
                - limit: Optional maximum number of iterations
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for sub-step resume.

        Returns:
            Tuple of (combined_output, total_tokens) where combined_output
            is all iteration outputs joined with newlines.
        """
        for_each = step_data["for_each"]
        variable = for_each["variable"]
        in_list = for_each["in"]
        steps = for_each["steps"]
        limit = for_each.get("limit")

        logger(f"\n==== Executing for_each loop {step_number} ====")
        logger(f"Variable: {variable}, In: {in_list}")

        # Get the list to iterate over
        if isinstance(in_list, str):
            # Try to get from context or use as literal
            iteration_list = context.get(in_list, [in_list])
        elif isinstance(in_list, list):
            iteration_list = in_list
        else:
            iteration_list = [str(in_list)]

        if limit:
            iteration_list = iteration_list[:limit]

        all_outputs = []
        total_tokens = 0

        for i, item in enumerate(iteration_list):
            logger(f"\n--- For-each iteration {i+1}: {variable}={item} ---")

            # Create new context for this iteration
            iter_context = context
            iter_context[variable] = item

            # Execute all steps in this iteration
            for j, sub_step in enumerate(steps):
                sub_step_id = f"{step_number}.{i+1}.{j+1}"

                # Check checkpoint – skip if already completed
                saved = _skip_completed_substep(
                    sub_step_id, sub_step, checkpoint_manager, iter_context, logger
                )
                if saved is not None:
                    output = saved
                    tokens = 0
                else:
                    output, tokens = self.execute_workflow_step(
                        sub_step,
                        iter_context,
                        sub_step_id,
                        args,
                        logger,
                        checkpoint_manager=checkpoint_manager,
                    )
                    _mark_substep_completed(
                        sub_step_id, output, sub_step, checkpoint_manager
                    )

                iter_context["prev_output"] = output
                total_tokens += tokens
                all_outputs.append(f"Iteration {i+1} ({variable}={item}): {output}")

        combined_output = "\n\n".join(all_outputs)
        return combined_output, total_tokens

    def execute_conditional_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute if/then/else conditional branching.

        Evaluates a condition and executes either the 'then' or 'else' branch.

        Args:
            step_data: Step configuration containing 'if' key with:
                - condition: Expression to evaluate
                - then: Steps to execute if condition is true
                - else: Optional steps to execute if condition is false
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for sub-step resume.

        Returns:
            Tuple of (combined_output, total_tokens) from executed branch.
        """
        raw_condition = step_data["if"]["condition"]
        then_steps = step_data["if"]["then"]
        else_steps = step_data["if"].get("else", [])

        # Expand template variables (e.g. {{A.B}}) before evaluation
        condition = expand_template_variables(raw_condition, context)

        logger(f"\n==== Executing conditional step {step_number} ====")
        logger(f"Condition: {raw_condition} -> {condition}")

        condition_met = evaluate_condition(condition, context)

        steps_to_execute = then_steps if condition_met else else_steps
        logger(
            f"Condition {'met' if condition_met else 'not met'}, executing {'then' if condition_met else 'else'} branch"
        )

        all_outputs = []
        total_tokens = 0

        for i, sub_step in enumerate(steps_to_execute):
            sub_step_id = f"{step_number}.{'then' if condition_met else 'else'}.{i+1}"

            saved = _skip_completed_substep(
                sub_step_id, sub_step, checkpoint_manager, context, logger
            )
            if saved is not None:
                output = saved
                tokens = 0
            else:
                output, tokens = self.execute_workflow_step(
                    sub_step,
                    context,
                    sub_step_id,
                    args,
                    logger,
                    checkpoint_manager=checkpoint_manager,
                )
                _mark_substep_completed(
                    sub_step_id, output, sub_step, checkpoint_manager
                )

            context["prev_output"] = output
            total_tokens += tokens
            all_outputs.append(output)

        combined_output = "\n\n".join(all_outputs)
        return combined_output, total_tokens

    def execute_while_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute a while loop with condition checking.

        Repeatedly executes nested steps while the condition remains true.
        Has a configurable maximum iteration limit to prevent infinite loops.

        Args:
            step_data: Step configuration containing 'while' key with:
                - condition: Expression to evaluate before each iteration
                - steps: List of steps to execute per iteration
                - max_iterations: Optional limit (default 25)
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for sub-step resume.

        Returns:
            Tuple of (combined_output, total_tokens) from all iterations.
        """
        w = step_data["while"]
        raw_condition = w.get("condition", "")
        steps = w.get("steps", [])
        # Currently, while loop limits max 25 iters
        max_iterations = int(w.get("max_iterations", 25))

        logger(
            f"\n==== Executing while loop {step_number}: condition '{raw_condition}' ===="
        )
        outputs = []
        tokens_total = 0
        iteration = 0
        # Expand templates each iteration (context may change between iterations)
        while iteration < max_iterations and evaluate_condition(
            expand_template_variables(raw_condition, context), context
        ):
            iteration += 1
            logger(f"-- While iteration {iteration}")
            logger("%" * 20)
            logger(f"Context: {safe_json_dumps(context)}")
            logger("%" * 20)
            for j, sub_step in enumerate(steps):
                sub_step_id = f"{step_number}.{iteration}.{j+1}"

                saved = _skip_completed_substep(
                    sub_step_id, sub_step, checkpoint_manager, context, logger
                )
                if saved is not None:
                    out = saved
                    t = 0
                else:
                    out, t = self.execute_workflow_step(
                        sub_step,
                        context,
                        sub_step_id,
                        args,
                        logger,
                        checkpoint_manager=checkpoint_manager,
                    )
                    _mark_substep_completed(
                        sub_step_id, out, sub_step, checkpoint_manager
                    )

                context["prev_output"] = out
                tokens_total += t
                outputs.append(out)
                logger(f"-- While iteration {iteration}, in-while step {j+1}")
                logger("@" * 20)
                logger(f"Context: {safe_json_dumps(context)}")
                logger("@" * 20)

        return "\n\n".join(outputs), tokens_total

    def execute_switch_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> Tuple[str, int]:
        """Execute switch/case style multi-way branching.

        Selects and executes one branch based on a variable's value.
        Falls back to default branch if no case matches.

        Args:
            step_data: Step configuration containing 'switch' key with:
                - variable: Context variable to switch on
                - cases: Dict mapping values to step lists
                - default: Optional steps if no case matches
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            checkpoint_manager: Optional checkpoint manager for sub-step resume.

        Returns:
            Tuple of (combined_output, total_tokens) from selected branch.
        """
        sw = step_data["switch"]
        variable = sw.get("variable")
        cases = sw.get("cases", {})
        default_steps = sw.get("default", [])

        # Resolve variable value from context (after template expansion)
        var_value = context.get(variable)
        logger(
            f"\n==== Executing switch {step_number} on '{variable}' = '{var_value}' ===="
        )

        selected_steps = cases.get(var_value)
        if selected_steps is None:
            selected_steps = default_steps

        outputs = []
        tokens_total = 0
        for i, sub_step in enumerate(selected_steps):
            sub_step_id = f"{step_number}.case.{i+1}"

            saved = _skip_completed_substep(
                sub_step_id, sub_step, checkpoint_manager, context, logger
            )
            if saved is not None:
                out = saved
                t = 0
            else:
                out, t = self.execute_workflow_step(
                    sub_step,
                    context,
                    sub_step_id,
                    args,
                    logger,
                    checkpoint_manager=checkpoint_manager,
                )
                _mark_substep_completed(sub_step_id, out, sub_step, checkpoint_manager)

            context["prev_output"] = out
            tokens_total += t
            outputs.append(out)

        return "\n\n".join(outputs), tokens_total
