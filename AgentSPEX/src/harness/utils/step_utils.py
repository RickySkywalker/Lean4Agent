import json
from typing import Any, Dict, List, Union

from harness.parsing.templates import expand_template_variables


def split_step_value(step_data: Dict[str, Any], key: str) -> tuple[Dict[str, Any], Any]:
    value = step_data.get(key)
    if isinstance(value, dict):
        return value, None
    return {}, value


def get_step_instruction(step_data: Dict[str, Any], context: Dict[str, Any]) -> str:
    if not isinstance(step_data, dict):
        return ""

    step_type = step_data.get("step_type")
    if not step_type:
        return ""

    def expand(value: str) -> str:
        return expand_template_variables(value or "", context)

    simple_instruction_types = {
        "step",
        "task",
    }

    if step_type in simple_instruction_types:
        return expand((step_data.get(step_type) or {}).get("instruction"))

    if step_type == "for_each":
        fe = step_data.get("for_each") or {}
        return f"{fe.get('variable', '')} in {fe.get('in', '')}".strip()

    if step_type in {"if", "while"}:
        return f"{step_type} {(step_data.get(step_type) or {}).get('condition', '')}".strip()

    if step_type == "switch":
        return f"switch {(step_data.get('switch') or {}).get('variable', '')}".strip()

    if step_type in {"call", "gather"}:
        return expand((step_data.get(step_type) or {}).get("module"))

    if step_type == "input":
        cfg, _ = split_step_value(step_data, "input")
        return expand(cfg.get("prompt"))

    if step_type == "increment":
        cfg, scalar = split_step_value(step_data, step_type)
        variable = cfg.get("variable") or (scalar if isinstance(scalar, str) else "")
        return f"{step_type} {variable}".strip()

    if step_type == "set_variable":
        cfg, scalar = split_step_value(step_data, "set_variable")
        if scalar is not None:
            return f"set {scalar}".strip()
        variable = cfg.get("variable") or cfg.get("name", "")
        value = cfg.get("value", "")
        return f"set {variable} = {value}".strip()

    if step_type == "return":
        return _render_return(step_data, context)

    return ""


def _render_return(step_data: Dict[str, Any], context: Dict[str, Any]) -> str:
    ret_val = step_data.get("return")

    if isinstance(ret_val, dict):
        ret_val = ret_val.get("variable", "")

    expanded = expand_template_variables(str(ret_val or ""), context)

    if expanded in context:
        value = context[expanded]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        return f"return {value}".strip()

    return f"return {expanded}".strip()


def get_step_depth(step_id: Union[int, str]) -> int:
    if not step_id:
        return 0

    parts = str(step_id).split(".")
    depth = 0
    skip_next = False

    for part in parts:
        if skip_next:
            skip_next = False
            continue

        if part == "tool":
            skip_next = True

        depth += 1

    return max(0, depth - 1)
