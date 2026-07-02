"""Semantic verification for AgentSPEX YAML workflow plans.

Validates both structural correctness (YAML syntax, required fields) and
semantic correctness per step type (required sub-fields, variable flow,
parallel/gather constraints). Full formal verification (Lean4-based) is
under development by a collaborator and will complement these checks.

Checks are categorized as:
  - Errors: Plan will fail at runtime. Block execution.
  - Warnings: Plan may produce unexpected behavior. Allow execution but inform user.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness.parsing.yaml_parser import YAMLTaskParser


@dataclass
class VerificationResult:
    """Result of plan verification."""

    is_valid: bool
    error: Optional[str] = None
    plan_data: Optional[dict] = field(default=None, repr=False)
    warnings: list = field(default_factory=list)

    def summary(self) -> str:
        if not self.is_valid:
            return f"Plan is INVALID: {self.error}"
        if self.warnings:
            warnings_str = "; ".join(self.warnings)
            return f"Plan is valid with warnings: {warnings_str}"
        return "Plan is valid — parsed successfully."

    def preview(self, max_steps: int = 10) -> str:
        """Return a short preview of the plan for user approval."""
        if not self.is_valid or not self.plan_data:
            return self.summary()
        data = self.plan_data
        lines = [
            f"Name: {data.get('name', '(unnamed)')}",
            f"Goal: {data.get('goal', '(no goal)')}",
        ]
        config = data.get("config")
        if config:
            model = config.get("model", config.get("model_name"))
            if model:
                lines.append(f"Model: {model}")
        params = data.get("parameters")
        if params:
            lines.append(f"Parameters: {', '.join(str(k) for k in params.keys())}")
        workflow = data.get("workflow", [])
        lines.append(f"Steps: {len(workflow)}")
        for i, step in enumerate(workflow[:max_steps]):
            step_type = next(
                (k for k in step if k in _STEP_TYPES),
                list(step.keys())[0] if step else "?",
            )
            name = ""
            body = step.get(step_type)
            if isinstance(body, dict):
                name = body.get("name", "")
            label = f"  {i + 1}. {step_type}"
            if name:
                label += f": {name}"
            lines.append(label)
        if len(workflow) > max_steps:
            lines.append(f"  ... and {len(workflow) - max_steps} more steps")
        return "\n".join(lines)


_STEP_TYPES = {
    "step",
    "task",
    "for_each",
    "if",
    "while",
    "switch",
    "call",
    "parallel",
    "gather",
    "set_variable",
    "increment",
    "input",
    "return",
}


class PlanVerifier:
    """Semantic verifier for AgentSPEX YAML workflow plans.

    Performs:
    1. YAML syntax check (via yaml.safe_load inside YAMLTaskParser)
    2. Required field validation (name, goal, workflow)
    3. Per-step-type semantic checks (required sub-fields, constraints)
    4. Variable flow analysis (save_as definitions vs {{variable}} references)
    5. Tool name validation against available MCP tools (warnings)
    6. Parallel/gather constraint checking

    Formal verification (Lean4) will be integrated when available.
    """

    def __init__(self, available_tool_names: Optional[set[str]] = None):
        self._parser = YAMLTaskParser()
        self._available_tools = available_tool_names or set()

    def verify(self, plan_path: Path) -> VerificationResult:
        """Verify a plan file with comprehensive semantic checks."""
        try:
            data = self._parser.load_task(str(plan_path))
        except FileNotFoundError:
            return VerificationResult(
                is_valid=False, error=f"File not found: {plan_path}"
            )
        except ValueError as e:
            return VerificationResult(is_valid=False, error=str(e))
        except Exception as e:
            return VerificationResult(is_valid=False, error=f"Parse error: {e}")

        errors = []
        warnings = []

        # Collect defined variables from parameters + save_as in workflow
        defined_vars = set()
        params = data.get("parameters", {})
        if isinstance(params, dict):
            defined_vars.update(params.keys())
        # prev_output is always available
        defined_vars.add("prev_output")

        # Run all checks
        warnings.extend(self._check_tool_names(data))
        workflow = data.get("workflow", [])
        self._check_steps(workflow, errors, warnings, defined_vars, path="workflow")

        if errors:
            error_summary = "; ".join(errors[:5])
            if len(errors) > 5:
                error_summary += f" ... and {len(errors) - 5} more error(s)"
            return VerificationResult(
                is_valid=False,
                error=error_summary,
                plan_data=data,
                warnings=warnings,
            )

        result = VerificationResult(is_valid=True, plan_data=data)
        result.warnings = warnings
        return result

    # ── Per-step-type semantic checks ────────────────────────────────

    def _check_steps(
        self,
        steps: list,
        errors: list[str],
        warnings: list[str],
        defined_vars: set[str],
        path: str,
    ) -> None:
        """Recursively check all steps in a workflow or nested block."""
        if not isinstance(steps, list):
            errors.append(
                f"{path}: expected a list of steps, got {type(steps).__name__}"
            )
            return

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(
                    f"{path}[{i}]: step must be a dict, got {type(step).__name__}"
                )
                continue

            # Identify step type
            step_type = None
            for key in step:
                if key in _STEP_TYPES:
                    step_type = key
                    break

            step_path = f"{path}[{i}]"
            if step_type is None:
                known_keys = list(step.keys())
                errors.append(
                    f"{step_path}: unrecognized step type '{known_keys[0] if known_keys else '?'}'. "
                    f"Valid types: {', '.join(sorted(_STEP_TYPES))}"
                )
                continue

            body = step[step_type]

            # Dispatch to type-specific checker
            checker = getattr(self, f"_check_{step_type}", None)
            if checker:
                checker(body, errors, warnings, defined_vars, step_path)

    def _check_step(self, body, errors, warnings, defined_vars, path):
        """Check 'step' type — stateful, requires instruction."""
        if not isinstance(body, dict):
            errors.append(f"{path}.step: body must be a dict with 'instruction'")
            return
        if "instruction" not in body:
            errors.append(f"{path}.step: missing required field 'instruction'")
        save_as = body.get("save_as")
        if save_as:
            defined_vars.add(save_as)
        if body.get("system_prompt"):
            warnings.append(
                f"{path}.step: 'system_prompt' is IGNORED for 'step' type (only works with 'task')"
            )

    def _check_task(self, body, errors, warnings, defined_vars, path):
        """Check 'task' type — stateless, requires instruction."""
        if not isinstance(body, dict):
            errors.append(f"{path}.task: body must be a dict with 'instruction'")
            return
        if "instruction" not in body:
            errors.append(f"{path}.task: missing required field 'instruction'")
        save_as = body.get("save_as")
        if save_as:
            defined_vars.add(save_as)

    def _check_for_each(self, body, errors, warnings, defined_vars, path):
        """Check 'for_each' type — requires variable, in, steps."""
        if not isinstance(body, dict):
            errors.append(f"{path}.for_each: body must be a dict")
            return
        if "variable" not in body:
            errors.append(f"{path}.for_each: missing required field 'variable'")
        if "in" not in body:
            errors.append(f"{path}.for_each: missing required field 'in'")
        if "steps" not in body:
            errors.append(f"{path}.for_each: missing required field 'steps'")
        else:
            # Add loop variable to defined vars for inner scope
            loop_var = body.get("variable", "")
            inner_vars = defined_vars.copy()
            if loop_var:
                inner_vars.add(loop_var)
            self._check_steps(
                body["steps"], errors, warnings, inner_vars, f"{path}.for_each.steps"
            )

    def _check_while(self, body, errors, warnings, defined_vars, path):
        """Check 'while' type — requires condition, steps, max_iterations."""
        if not isinstance(body, dict):
            errors.append(f"{path}.while: body must be a dict")
            return
        if "condition" not in body:
            errors.append(f"{path}.while: missing required field 'condition'")
        if "steps" not in body:
            errors.append(f"{path}.while: missing required field 'steps'")
        else:
            self._check_steps(
                body["steps"],
                errors,
                warnings,
                defined_vars.copy(),
                f"{path}.while.steps",
            )
        if "max_iterations" not in body:
            errors.append(
                f"{path}.while: missing required field 'max_iterations'. "
                "Without max_iterations, the loop may run indefinitely."
            )

    def _check_if(self, body, errors, warnings, defined_vars, path):
        """Check 'if' type — requires condition, then."""
        if not isinstance(body, dict):
            errors.append(f"{path}.if: body must be a dict")
            return
        if "condition" not in body:
            errors.append(f"{path}.if: missing required field 'condition'")
        if "then" not in body:
            errors.append(f"{path}.if: missing required field 'then'")
        else:
            self._check_steps(
                body["then"], errors, warnings, defined_vars.copy(), f"{path}.if.then"
            )
        if "else" in body:
            self._check_steps(
                body["else"], errors, warnings, defined_vars.copy(), f"{path}.if.else"
            )

    def _check_switch(self, body, errors, warnings, defined_vars, path):
        """Check 'switch' type — requires variable, cases."""
        if not isinstance(body, dict):
            errors.append(f"{path}.switch: body must be a dict")
            return
        if "variable" not in body:
            errors.append(f"{path}.switch: missing required field 'variable'")
        if "cases" not in body:
            errors.append(f"{path}.switch: missing required field 'cases'")
        else:
            cases = body["cases"]
            if isinstance(cases, dict):
                for case_key, case_steps in cases.items():
                    if isinstance(case_steps, list):
                        self._check_steps(
                            case_steps,
                            errors,
                            warnings,
                            defined_vars.copy(),
                            f"{path}.switch.cases.{case_key}",
                        )
        if "default" in body and isinstance(body["default"], list):
            self._check_steps(
                body["default"],
                errors,
                warnings,
                defined_vars.copy(),
                f"{path}.switch.default",
            )

    def _check_call(self, body, errors, warnings, defined_vars, path):
        """Check 'call' type — requires module."""
        if not isinstance(body, dict):
            errors.append(f"{path}.call: body must be a dict with 'module'")
            return
        if "module" not in body:
            errors.append(f"{path}.call: missing required field 'module'")
        save_as = body.get("save_as")
        if save_as:
            defined_vars.add(save_as)

    def _check_parallel(self, body, errors, warnings, defined_vars, path):
        """Check 'parallel' type — validate both formats."""
        if isinstance(body, list):
            # Format 1: list of inline steps — check for save_as misuse
            for i, sub_step in enumerate(body):
                if not isinstance(sub_step, dict):
                    continue
                for step_type, step_body in sub_step.items():
                    if isinstance(step_body, dict) and "save_as" in step_body:
                        errors.append(
                            f"{path}.parallel[{i}].{step_type}: 'save_as' inside parallel "
                            "inline steps does NOT propagate to outer context. The variable "
                            f"'{step_body['save_as']}' will be silently lost. Use sequential "
                            "task/step instead, or use gather with submodule files."
                        )
            # Still check inner steps for other issues
            self._check_steps(
                body, errors, warnings, defined_vars.copy(), f"{path}.parallel"
            )
        elif isinstance(body, dict):
            # Format 2: module + parameters_list (delegates to gather)
            if "module" not in body:
                errors.append(
                    f"{path}.parallel: dict format requires 'module' and 'parameters_list'"
                )
            if "parameters_list" not in body:
                errors.append(
                    f"{path}.parallel: dict format requires 'parameters_list'"
                )
            save_results_as = body.get("save_results_as")
            if save_results_as:
                defined_vars.add(save_results_as)
        else:
            errors.append(
                f"{path}.parallel: must be a list of steps or a dict with module+parameters_list"
            )

    def _check_gather(self, body, errors, warnings, defined_vars, path):
        """Check 'gather' type — requires calls with module paths."""
        if not isinstance(body, dict):
            errors.append(f"{path}.gather: body must be a dict")
            return
        calls = body.get("calls", [])
        if not calls and "module" not in body:
            errors.append(
                f"{path}.gather: must have 'calls' list or 'module' + 'parameters_list'"
            )
        if isinstance(calls, list):
            for i, call_config in enumerate(calls):
                if not isinstance(call_config, dict):
                    errors.append(f"{path}.gather.calls[{i}]: must be a dict")
                    continue
                if "module" not in call_config:
                    errors.append(
                        f"{path}.gather.calls[{i}]: missing required field 'module'. "
                        "gather calls must reference submodule YAML files — "
                        "inline task/step is not supported."
                    )
                save_as = call_config.get("save_as")
                if save_as:
                    defined_vars.add(save_as)
        save_results_as = body.get("save_results_as")
        if save_results_as:
            defined_vars.add(save_results_as)

    def _check_set_variable(self, body, errors, warnings, defined_vars, path):
        """Check 'set_variable' type — requires name."""
        if not isinstance(body, dict):
            errors.append(f"{path}.set_variable: body must be a dict with 'name'")
            return
        if "name" not in body:
            errors.append(f"{path}.set_variable: missing required field 'name'")
        else:
            defined_vars.add(body["name"])

    def _check_increment(self, body, errors, warnings, defined_vars, path):
        """Check 'increment' type — body is just a variable name string."""
        if not isinstance(body, str):
            errors.append(f"{path}.increment: must be a string (variable name)")
        else:
            defined_vars.add(body)

    def _check_input(self, body, errors, warnings, defined_vars, path):
        """Check 'input' type — requires prompt, warn about automated execution."""
        if not isinstance(body, dict):
            errors.append(f"{path}.input: body must be a dict with 'prompt'")
            return
        if "prompt" not in body:
            errors.append(f"{path}.input: missing required field 'prompt'")
        save_as = body.get("save_as", "user_input")
        defined_vars.add(save_as)
        warnings.append(
            f"{path}.input: 'input' steps block automated execution and require "
            "user interaction. Consider using parameters with defaults instead."
        )

    def _check_return(self, body, errors, warnings, defined_vars, path):
        """Check 'return' type — body is a variable name string."""
        # return can be a string (variable name) or omitted
        pass

    # ── Tool name validation ─────────────────────────────────────────

    def _check_tool_names(self, plan_data: dict) -> list[str]:
        """Check enabled_tools values against the available MCP tool set."""
        if not self._available_tools:
            return []

        warnings = []

        # Check plan-level enabled_tools in config
        config = plan_data.get("config", {}) or {}
        plan_tools = config.get("enabled_tools", [])
        if isinstance(plan_tools, list):
            for tool_name in plan_tools:
                if tool_name not in self._available_tools:
                    warnings.append(
                        f"Unrecognized tool in config.enabled_tools: '{tool_name}'"
                    )

        # Check step-level enabled_tools throughout the workflow
        workflow = plan_data.get("workflow", [])
        self._check_steps_tool_names(workflow, warnings)

        return warnings

    def _check_steps_tool_names(self, steps: list, warnings: list) -> None:
        """Recursively check enabled_tools in nested step structures."""
        if not isinstance(steps, list):
            return
        for step in steps:
            if not isinstance(step, dict):
                continue
            for step_type, body in step.items():
                if not isinstance(body, dict):
                    continue
                # Check enabled_tools on this step
                step_tools = body.get("enabled_tools", [])
                if isinstance(step_tools, list):
                    for tool_name in step_tools:
                        if tool_name not in self._available_tools:
                            warnings.append(
                                f"Unrecognized tool in {step_type}.enabled_tools: "
                                f"'{tool_name}'"
                            )
                # Recurse into nested steps (for_each, if, while, etc.)
                for nested_key in ("steps", "then", "else"):
                    nested = body.get(nested_key)
                    if nested:
                        self._check_steps_tool_names(nested, warnings)
