import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..parsing.yaml_parser import YAMLTaskParser
from .specs import SubmoduleFunctionSpec, SubmoduleParamSpec


def normalize_submodule_declarations(
    yaml_data: Dict[str, Any],
    yaml_file_path: str,
) -> List[Dict[str, Any]]:
    """Normalize submodule declarations from YAML data to a standard format."""
    submodules = yaml_data.get("submodules", [])
    if not submodules:
        return []
    if isinstance(submodules, dict):
        submodules = [{"name": name, "path": path} for name, path in submodules.items()]
    if not isinstance(submodules, list):
        raise ValueError("submodules must be a list or mapping")

    base_dir = Path(yaml_file_path).resolve().parent
    normalized = []
    for entry in submodules:
        if isinstance(entry, str):
            entry = {"path": entry}
        if not isinstance(entry, dict):
            raise ValueError("Each submodule entry must be a mapping or string path")
        name = entry.get("name")
        path = entry.get("path") or entry.get("file") or entry.get("filepath")
        if not path:
            raise ValueError("Submodule entry must include a file path")
        module_path = (
            str((base_dir / path).resolve()) if not os.path.isabs(path) else path
        )
        normalized.append({"name": name, "path": module_path})
    return normalized


def parse_submodule_function_declaration(
    yaml_data: Dict[str, Any],
    module_path: str,
    declared_name: Optional[str] = None,
) -> SubmoduleFunctionSpec:
    """Parse a submodule's function declaration from its YAML data."""
    func_decl = yaml_data.get("function")
    if not func_decl or not isinstance(func_decl, dict):
        raise ValueError(
            f"Submodule {module_path} must define a top-level 'function' block"
        )

    func_name = func_decl.get("name") or declared_name
    if not func_name:
        raise ValueError(f"Submodule {module_path} function must define a name")
    if declared_name and func_name != declared_name:
        raise ValueError(
            f"Submodule name mismatch: declared '{declared_name}' but function name is '{func_name}'"
        )

    description = func_decl.get("description") or func_decl.get("docstring") or ""
    return_var = func_decl.get("return", "prev_output")

    params = func_decl.get("parameters", [])
    normalized_params: List[SubmoduleParamSpec] = []

    if isinstance(params, dict):

        def _normalize_param_list(items: Any, source: str) -> List[Dict[str, Any]]:
            if items is None:
                return []
            if not isinstance(items, list):
                items = [items]
            normalized: List[Dict[str, Any]] = []
            for item in items:
                if isinstance(item, str):
                    normalized.append({"name": item, "source": source})
                elif isinstance(item, dict):
                    entry = dict(item)
                    entry["source"] = source
                    normalized.append(entry)
                else:
                    raise ValueError(f"Invalid parameter spec in {module_path}: {item}")
            return normalized

        model_params = _normalize_param_list(params.get("model"), "model")
        context_params = _normalize_param_list(params.get("context"), "context")
        params = model_params + context_params

    if isinstance(params, list):
        for p in params:
            if isinstance(p, str):
                p = {"name": p}
            if not isinstance(p, dict):
                raise ValueError(f"Invalid parameter spec in {module_path}: {p}")
            if not p.get("name"):
                raise ValueError(
                    f"Submodule {module_path} has a parameter without a name"
                )
            normalized_params.append(
                SubmoduleParamSpec(
                    name=p.get("name"),
                    param_type=p.get("type", "string"),
                    description=p.get("description", ""),
                    required=p.get("required", True),
                    source=p.get("source", "model"),
                    default=p.get("default"),
                    schema=p.get("schema"),
                )
            )
    else:
        raise ValueError(f"Invalid parameters format in {module_path}")

    model_params = [p for p in normalized_params if p.source == "model"]
    context_params = [p for p in normalized_params if p.source == "context"]

    return SubmoduleFunctionSpec(
        name=func_name,
        description=description,
        module_path=module_path,
        model_params=model_params,
        context_params=context_params,
        return_var=return_var,
    )


def build_submodule_tool(spec: SubmoduleFunctionSpec) -> Dict[str, Any]:
    """Build a tool definition from a submodule function spec."""
    properties = {}
    required = []
    for p in spec.model_params:
        if not p.name:
            raise ValueError(
                f"Submodule {spec.module_path} has a parameter without a name"
            )
        if p.schema and isinstance(p.schema, dict):
            properties[p.name] = p.schema
        else:
            properties[p.name] = {
                "type": p.param_type or "string",
                "description": p.description or "",
            }
        if p.required:
            required.append(p.name)

    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def load_submodule_tools_for_yaml(
    yaml_data: Dict[str, Any],
    yaml_file_path: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, SubmoduleFunctionSpec]]:
    """
    Load all submodule tools defined in a YAML file.

    Returns:
        Tuple of (tools list, registry dict mapping function name to spec)
    """
    submodules = normalize_submodule_declarations(yaml_data, yaml_file_path)
    if not submodules:
        return [], {}

    tools: List[Dict[str, Any]] = []
    registry: Dict[str, SubmoduleFunctionSpec] = {}
    parser = YAMLTaskParser()

    for entry in submodules:
        declared_name = entry.get("name")
        module_path = entry["path"]
        module_yaml = parser.load_task(module_path)
        spec = parse_submodule_function_declaration(
            module_yaml, module_path, declared_name=declared_name
        )
        if spec.name in registry:
            raise ValueError(f"Duplicate submodule function name: {spec.name}")
        registry[spec.name] = spec
        tools.append(build_submodule_tool(spec))

    return tools, registry
