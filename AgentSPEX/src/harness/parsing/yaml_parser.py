"""YAML task parser for workflow definitions.

This module provides the YAMLTaskParser class for loading and parsing
YAML workflow files, including environment variable expansion and
task validation.
"""

import os
import re
from typing import Any, Dict, List, Union

import yaml


class YAMLTaskParser:
    """YAML task parser"""

    def __init__(self):
        self.context = {}
        self.variables = {}

    def load_task(self, file_path: str) -> Dict[str, Any]:
        """Load and parse a YAML task file"""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Expand environment variables first
        content = self._expand_env_variables(content)

        # Parse YAML
        task_data = yaml.safe_load(content)

        # Validate task format
        self._validate_task(task_data)

        return task_data

    def _expand_env_variables(self, content: str) -> str:
        """Expand environment variables and template variables"""

        # Handle ${VAR} and ${VAR:-default} formats
        def replace_var(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                value = os.getenv(var_name, default_value)
            else:
                value = os.getenv(var_expr, match.group(0))

            # If the value contains special YAML characters and needs escaping
            if value and value != match.group(
                0
            ):  # Only if we actually got a value from env
                # Escape backslashes and double quotes for YAML double-quoted strings
                # This handles JSON strings and other special content
                if (
                    "\\" in value
                    or '"' in value
                    or "\n" in value
                    or "\r" in value
                    or "\t" in value
                ):
                    value = value.replace("\\", "\\\\")  # Escape backslashes first
                    value = value.replace('"', '\\"')  # Escape double quotes
                    value = value.replace("\n", "\\n")  # Escape newlines
                    value = value.replace("\r", "\\r")  # Escape carriage returns
                    value = value.replace("\t", "\\t")  # Escape tabs

            return value

        # Replace environment variables
        content = re.sub(r"\$\{([^}]+)\}", replace_var, content)

        return content

    def _validate_task(self, task_data: Dict[str, Any]) -> None:
        """Validate task data format"""
        required_fields = ["name", "goal", "workflow"]
        for field in required_fields:
            if field not in task_data:
                raise ValueError(f"Missing required field: {field}")

        if not isinstance(task_data["workflow"], list):
            raise ValueError("Workflow must be a list of steps")

    def has_config(self, task_data: Dict[str, Any]) -> bool:
        """
        Check if task data has a config section.

        Args:
            task_data: The parsed YAML task data

        Returns:
            True if config section exists, False otherwise
        """
        return "config" in task_data and task_data["config"] is not None

    def get_config_with_defaults(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract config section from task data with default values.

        This method extracts the 'config' section from a YAML task file,
        which can specify execution parameters like model, max_tokens_per_step, etc.

        Args:
            task_data: The parsed YAML task data

        Returns:
            Dictionary with config values. Only includes keys that are
            actually specified in the YAML config section.
        """
        # Default values for execution configuration
        defaults = {
            "model": "gpt-4.1-mini",
            "max_tokens_per_step": 100000,
            "max_tool_calls_per_step": 10,
            "temperature": 0.2,
            "model_kwargs": {},
            "plan_revision_max_steps": 0,
            "swebench_mode": False,
            "enable_git_filtering": False,
            "require_thought_section": False,
        }

        config = task_data.get("config", {}) or {}
        if "model" not in config and "model_name" in config:
            config = dict(config)
            config["model"] = config.get("model_name")

        # Merge: YAML config overrides defaults
        result = {}
        for key, default_value in defaults.items():
            if key in config:
                result[key] = config[key]
            else:
                result[key] = default_value

        return result

    def _parse_step(
        self, step: Dict[str, Any]
    ) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """Parse a single step"""
        step_type = list(step.keys())[0]
        step_data = step[step_type]

        if step_type == "step":
            return self._parse_basic_step(step_data)

        elif step_type == "task":
            return self._parse_task_step(step_data)

        elif step_type == "for_each":
            return self._parse_for_each_step(step_data)

        elif step_type == "if":
            return self._parse_if_step(step_data)

        elif step_type == "while":
            return self._parse_while_step(step_data)

        elif step_type == "switch":
            return self._parse_switch_step(step_data)

        elif step_type == "parallel":
            return self._parse_parallel_step(step_data)

        elif step_type == "increment":
            return self._parse_increment_step(step_data)

        else:
            raise ValueError(f"Unknown step type: {step_type}")

    def _parse_basic_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse step (with conversation history)"""
        return {
            "type": "step",
            "name": step_data.get("name", "unnamed_step"),
            "instruction": self._expand_template(step_data.get("instruction", "")),
            "output_file": step_data.get("output_file"),
        }

    def _parse_task_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse task (stateless)"""
        return {
            "type": "task",
            "name": step_data.get("name", "unnamed_task"),
            "instruction": self._expand_template(step_data.get("instruction", "")),
            "output_file": step_data.get("output_file"),
        }

    def _parse_for_each_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse loop step"""
        return {
            "type": "loop",
            "variable": step_data.get("variable", "item"),
            "source": step_data.get("in", ""),
            "max_iterations": step_data.get("max_iterations", 10),
            "parallel": step_data.get("parallel", False),
            "limit": step_data.get("limit"),
            "body": self._parse_steps_list(step_data.get("steps", [])),
        }

    def _parse_if_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse conditional step"""
        return {
            "type": "conditional",
            "condition": step_data.get("condition", ""),
            "then": self._parse_steps_list(step_data.get("then", [])),
            "else": self._parse_steps_list(step_data.get("else", [])),
        }

    def _parse_while_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse while loop"""
        return {
            "type": "while_loop",
            "condition": step_data.get("condition", ""),
            "max_iterations": step_data.get("max_iterations", 10),
            "steps": self._parse_steps_list(step_data.get("steps", [])),
        }

    def _parse_switch_step(self, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse switch statement"""
        cases = {}
        for case_value, case_steps in step_data.get("cases", {}).items():
            cases[case_value] = self._parse_steps_list(case_steps)

        return {
            "type": "switch",
            "variable": step_data.get("variable", ""),
            "cases": cases,
            "default": self._parse_steps_list(step_data.get("default", [])),
        }

    def _parse_parallel_step(self, step_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse parallel steps"""
        return {"type": "parallel", "steps": self._parse_steps_list(step_data)}

    def _parse_increment_step(self, step_data: str) -> Dict[str, Any]:
        """Parse increment step"""
        return {"type": "increment", "variable": step_data}

    def _parse_steps_list(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse list of steps"""
        parsed_steps = []
        for step in steps:
            parsed_step = self._parse_step(step)
            if parsed_step:
                if isinstance(parsed_step, list):
                    parsed_steps.extend(parsed_step)
                else:
                    parsed_steps.append(parsed_step)
        return parsed_steps

    def _expand_template(self, text: str) -> str:
        """Expand template variables"""
        if not isinstance(text, str):
            return str(text)

        # Replace {{variable}} format variables
        def replace_template_var(match):
            var_name = match.group(1)
            value = self.context.get(var_name, f"{{{{{var_name}}}}}")
            return str(value)  # Ensure a string is returned

        # Replace template variables
        text = re.sub(r"\{\{([^}]+)\}\}", replace_template_var, text)

        return text

    def validate_yaml_syntax(self, file_path: str) -> tuple[bool, str]:
        """Validate YAML syntax"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
            return True, "Valid YAML syntax"
        except yaml.YAMLError as e:
            return False, f"YAML syntax error: {str(e)}"
        except Exception as e:
            return False, f"Error reading file: {str(e)}"


def convert_json_to_yaml(json_file: str, yaml_file: str = None) -> str:
    """Convert existing JSON task to YAML format"""
    import json

    if yaml_file is None:
        yaml_file = json_file.replace(".json", ".yaml")

    with open(json_file, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    # Convert JSON data to YAML-friendly format
    yaml_data = {
        "name": json_data.get("task_name", "converted_task"),
        "goal": json_data.get("goal", ""),
        "config": json_data.get("constraints", {}),
        "workflow": [],
    }

    # Convert control flows
    for i, flow in enumerate(json_data.get("control_flows", [])):
        yaml_step = _convert_control_flow_to_yaml(flow)
        if yaml_step:
            yaml_data["workflow"].append(yaml_step)

    # Save YAML file
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, indent=2)

    return yaml_file


def _convert_control_flow_to_yaml(flow: Dict[str, Any]) -> Dict[str, Any]:
    """Convert JSON control flow to YAML format"""
    flow_type = flow.get("type", "")

    if flow_type == "loop":
        return {
            "for_each": {
                "variable": flow.get("variable", "item"),
                "in": flow.get("source", ""),
                "max_iterations": flow.get("max_iterations", 10),
                "steps": [
                    {"task": {"name": name, "instruction": instruction}}
                    for name, instruction in flow.get("body", {}).items()
                ],
            }
        }

    elif flow_type == "conditional":
        return {
            "if": {
                "condition": flow.get("condition", ""),
                "then": [
                    {
                        "task": {
                            "instruction": flow.get("then", {}).get("instruction", "")
                        }
                    }
                ],
                "else": [
                    {
                        "task": {
                            "instruction": flow.get("else", {}).get("instruction", "")
                        }
                    }
                ],
            }
        }

    elif flow_type == "step":
        return {
            "task": {
                "name": flow.get("name", "task"),
                "instruction": flow.get("instruction", ""),
            }
        }

    return None
