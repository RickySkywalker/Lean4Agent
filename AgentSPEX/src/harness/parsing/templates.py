import re
from typing import Any, Dict

from .conditions import _SENTINEL, resolve_dotted_path


def expand_template_variables(text: str, context: Dict[str, Any]) -> str:
    """Expand template variables in text using context"""
    if not isinstance(text, str):
        return str(text)

    def replace_var(match):
        var_name = match.group(1)
        # Handle dot notation for nested dict access (e.g., {{dict.key}}, {{A.B.C}})
        if "." in var_name:
            val = resolve_dotted_path(var_name, context)
            if val is not _SENTINEL:
                return str(val)
            return match.group(0)  # Keep original if path cannot be resolved
        return str(context.get(var_name, match.group(0)))

    # Replace {{variable}} patterns
    expanded_text = re.sub(r"\{\{([^}]+)\}\}", replace_var, text)
    return expanded_text
