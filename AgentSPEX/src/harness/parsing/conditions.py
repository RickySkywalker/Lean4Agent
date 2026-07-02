import ast
import json
import re
from typing import Any, Dict

# Sentinel object to distinguish "not found" from a resolved None value
_SENTINEL = object()

# Matches ```lang\n...\n``` code-block wrappers produced by LLMs
_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _try_parse_dict(value: str) -> Any:
    """Try to parse a string as a dict (JSON or Python literal).

    Handles LLM output that wraps JSON in markdown code blocks, e.g.::

        ```json
        {"key": "value"}
        ```

    Returns the parsed dict on success, or ``_SENTINEL`` on failure.
    """
    text = value.strip()

    # Strip markdown code-block wrappers if present
    m = _CODE_BLOCK_RE.search(text)
    if m:
        text = m.group(1).strip()

    # Try JSON first (most common LLM output format)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Try Python literal (e.g. single-quoted keys, True/False/None)
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass

    return _SENTINEL


def resolve_dotted_path(path: str, context: Dict[str, Any]) -> Any:
    """Resolve a dotted path like 'A.B.C' through nested dicts in context.

    Walks each segment of the dot-separated path, descending into nested
    dictionaries.  If a segment's value is a string, attempts to parse it
    as JSON/dict (with optional markdown code-block stripping) before
    continuing the traversal.

    Returns ``_SENTINEL`` if any segment cannot be resolved.

    Args:
        path: Dot-separated path string (e.g. "result.status", "A.B.C")
        context: Context dictionary (may contain nested dicts)

    Returns:
        The resolved value, or ``_SENTINEL`` if the path cannot be followed.
    """
    parts = path.split(".")
    current = context
    for part in parts:
        # If current is a string, try to parse it as a dict first
        if isinstance(current, str):
            parsed = _try_parse_dict(current)
            if parsed is _SENTINEL:
                return _SENTINEL
            current = parsed

        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _SENTINEL
    return current


def resolve_operand(operand: str, context: Dict[str, Any]) -> Any:
    """
    Resolve an operand to its actual value.

    Args:
        operand: Operand string (variable name, number, or quoted string)
        context: Context dictionary containing variables

    Returns:
        Resolved value (int, float, str, or original value from context)
    """
    operand = operand.strip()

    # Check if it's a quoted string - return the string without quotes
    if (operand.startswith('"') and operand.endswith('"')) or (
        operand.startswith("'") and operand.endswith("'")
    ):
        return operand[1:-1]  # Remove quotes

    # Check if it's a dotted path for nested dict access (e.g., result.status, A.B.C)
    # Only treat as dotted path if it starts with a letter/underscore (not a number like 3.14)
    if "." in operand and (operand[0].isalpha() or operand[0] == "_"):
        val = resolve_dotted_path(operand, context)
        if val is not _SENTINEL:
            return val

    # Try to parse as number (int or float)
    try:
        if "." in operand:
            return float(operand)
        else:
            return int(operand)
    except ValueError:
        pass

    # Must be a variable name - get from context, or return as-is if not found
    return context.get(operand, operand)


def _evaluate_single_condition(cond: str, context: Dict[str, Any]) -> bool:
    """Evaluate a single comparison or truthiness expression.

    This handles one atomic condition (no ``and``/``or``).

    Supports:
    - Numeric comparisons: "iteration < 10", "score >= 0.5"
    - String comparisons: "status == DONE", "result != FAILED"
    - Dotted-path operands: "result.status == DONE", "A.B.C >= 3"
    - Variable-to-variable: "var1 == var2"
    - Truthiness: "has_data", "result.ready"
    """
    cond = cond.strip()
    if not cond:
        return False

    # Match comparison operators
    # Operands can be: identifiers with optional dot notation for nested
    # dict access (e.g. result.status or A.B.C), numbers, or quoted strings.
    _ident = r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*"
    _number = r"[+-]?[0-9]+(?:\.[0-9]+)?"
    _quoted = r'"[^"]*"|\'[^\']*\''
    pattern = rf"^({_ident}|{_number}|{_quoted})\s*(==|!=|<=|>=|<|>)\s*({_ident}|{_number}|{_quoted})$"
    m = re.match(pattern, cond)

    if m:
        left_str, op, right_str = m.groups()

        # Resolve operands to their actual values
        left_val = resolve_operand(left_str, context)
        right_val = resolve_operand(right_str, context)

        # Try numeric comparison first (if both values can be converted to numbers)
        try:
            left_num = (
                float(left_val) if not isinstance(left_val, (int, float)) else left_val
            )
            right_num = (
                float(right_val)
                if not isinstance(right_val, (int, float))
                else right_val
            )

            if op == "==":
                return left_num == right_num
            elif op == "!=":
                return left_num != right_num
            elif op == "<":
                return left_num < right_num
            elif op == ">":
                return left_num > right_num
            elif op == "<=":
                return left_num <= right_num
            elif op == ">=":
                return left_num >= right_num

        except (ValueError, TypeError):
            # Not both numeric - fall back to string comparison
            left_str_val = str(left_val)
            right_str_val = str(right_val)

            if op == "==":
                return left_str_val == right_str_val
            elif op == "!=":
                return left_str_val != right_str_val
            elif op in ["<", ">", "<=", ">="]:
                if op == "<":
                    return left_str_val < right_str_val
                elif op == ">":
                    return left_str_val > right_str_val
                elif op == "<=":
                    return left_str_val <= right_str_val
                elif op == ">=":
                    return left_str_val >= right_str_val

    # Truthiness check: variable name or dotted path
    if "." in cond and (cond[0].isalpha() or cond[0] == "_"):
        val = resolve_dotted_path(cond, context)
        if val is not _SENTINEL:
            return bool(val)
    elif cond in context:
        return bool(context.get(cond))

    return False


# Regex used to split on ` and ` / ` or ` while respecting word boundaries.
# Requires whitespace on both sides so identifiers like "commandline" are safe.
_AND_SPLIT = re.compile(r"\s+and\s+")
_OR_SPLIT = re.compile(r"\s+or\s+")


def evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate a condition expression, optionally with ``and`` / ``or`` connectives.

    Supports:
    - Single comparisons: ``"score >= 0.5"``
    - Compound (and): ``"status == DONE and score >= 0.5"``
    - Compound (or):  ``"mode == fast or mode == turbo"``
    - Mixed:          ``"A == 1 and B == 2 or C == 3"``
      (standard precedence: ``and`` binds tighter than ``or``)
    - Dotted paths:   ``"result.status == DONE"``
    - Truthiness:     ``"has_data"``

    Template variables (``{{...}}``) should be expanded *before* calling this
    function — the callers in ``control.py`` handle that.

    Args:
        condition: Condition string to evaluate.
        context: Context dictionary containing variables.

    Returns:
        Boolean result of the condition evaluation.
    """
    if not condition:
        return False

    cond = condition.strip()

    # Split on ` or ` first (lower precedence), then ` and ` (higher precedence).
    or_clauses = _OR_SPLIT.split(cond)

    for or_clause in or_clauses:
        and_clauses = _AND_SPLIT.split(or_clause)
        # All sub-conditions in an and-group must be True
        if all(_evaluate_single_condition(c, context) for c in and_clauses):
            return True

    return False
