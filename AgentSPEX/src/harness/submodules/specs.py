import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SubmoduleParamSpec:
    name: str
    param_type: str = "string"
    description: str = ""
    required: bool = True
    source: str = "model"  # "model" or "context"
    default: Any = None
    schema: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SubmoduleFunctionSpec:
    name: str
    description: str
    module_path: str
    model_params: List[SubmoduleParamSpec] = field(default_factory=list)
    context_params: List[SubmoduleParamSpec] = field(default_factory=list)
    return_var: str = "prev_output"


def extract_submodule_result_value(value: Any) -> Optional[str]:
    def _extract_from_text(text: str) -> Optional[str]:
        if not text:
            return None
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("RETURN:"):
                return None
            first_payload = stripped.split("RETURN:", 1)[1].strip()
            rest_lines = []
            for rest in lines[idx + 1 :]:
                rest_stripped = rest.strip()
                if rest_stripped.startswith("RETURN:"):
                    rest_lines.append(rest_stripped.split("RETURN:", 1)[1].strip())
                else:
                    rest_lines.append(rest)
            if rest_lines:
                return "\n".join([first_payload] + rest_lines)
            return first_payload
        return None

    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("output", "content", "result", "stdout"):
            if key in value and isinstance(value[key], str):
                extracted = _extract_from_text(value[key])
                if extracted is not None:
                    return extracted
    if isinstance(value, str):
        return _extract_from_text(value)
    try:
        serialized = json.dumps(value, default=str)
    except Exception:
        serialized = str(value)
    return _extract_from_text(serialized)
