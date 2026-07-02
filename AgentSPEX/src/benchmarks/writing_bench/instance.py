"""Per-query instance processing for WritingBench benchmark."""

import json
from pathlib import Path
from typing import TYPE_CHECKING, List

import yaml

from benchmarks.writing_bench.config import WritingResult

if TYPE_CHECKING:
    from mcp_client.client import MCPClient

__all__ = [
    "save_result",
    "prepare_yaml_for_instance",
    "collect_instance_artifacts",
    "sandbox_query_dir",
]

# File extensions we attempt to collect from the sandbox after a run.
_ARTIFACT_EXTENSIONS = {".md", ".txt", ".tex", ".html"}


def sandbox_query_dir(experiment_name: str, index: int) -> str:
    """Return the sandbox-side output directory for a specific query.

    Mirrors the host-side layout so paths are easy to find::

        outputs/{experiment_name}/query_{index}/

    Args:
        experiment_name: Basename of the user's ``--output-dir``
            (e.g. ``"my_experiment"`` from ``outputs/my_experiment``).
        index: Query index.
    """
    return f"outputs/{experiment_name}/query_{index}"


def save_result(result: WritingResult, instance_dir: Path) -> None:
    """Save a writing result as JSON into the per-instance directory.

    Args:
        result: The WritingResult to save.
        instance_dir: Per-instance host directory, e.g. ``runs/42/``.
    """
    instance_dir.mkdir(parents=True, exist_ok=True)
    output_file = instance_dir / "result.json"

    data = {
        "index": result.index,
        "domain1": result.domain1,
        "domain2": result.domain2,
        "lang": result.lang,
        "status": result.status,
        "response": result.response,
    }
    if result.error:
        data["error"] = result.error

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _resolve_call_paths(steps: list, base_dir: Path) -> None:
    """Recursively resolve relative call.module paths in workflow steps."""
    for step in steps:
        if not isinstance(step, dict):
            continue
        if "call" in step:
            call = step["call"]
            module_path = call.get("module")
            if isinstance(module_path, str) and not Path(module_path).is_absolute():
                call["module"] = str((base_dir / module_path).resolve())
        for key in ("steps", "then", "else"):
            if isinstance(step.get(key), list):
                _resolve_call_paths(step[key], base_dir)
        for key in ("for_each", "while", "if", "parallel", "gather"):
            nested = step.get(key)
            if isinstance(nested, dict):
                for sub_key in ("steps", "then", "else", "calls"):
                    if isinstance(nested.get(sub_key), list):
                        _resolve_call_paths(nested[sub_key], base_dir)


def prepare_yaml_for_instance(
    yaml_file: str,
    query: dict,
    instance_dir: Path,
    experiment_name: str,
) -> str:
    """Create a per-instance YAML from the template with an isolated output_dir.

    Sandbox-side output directory layout (mirrors host naming)::

        outputs/{experiment_name}/
            query_1/
                draft.md
            query_2/
                draft.md
            ...

    Args:
        yaml_file: Path to the YAML template (e.g. ``writing_bench_agent.yaml``).
        query: The benchmark query dict (must contain ``"index"``).
        instance_dir: Host-side per-instance directory where the customised
            YAML will be saved.
        experiment_name: Basename of the user's ``--output-dir``, used to
            build the sandbox path so host and sandbox names are cohesive.

    Returns:
        Absolute path to the customised YAML file.
    """
    template_path = Path(yaml_file).resolve()
    with open(template_path, "r") as f:
        yaml_data = yaml.safe_load(f)

    # Resolve submodule paths relative to the template
    submodules = yaml_data.get("submodules")
    if isinstance(submodules, list):
        for entry in submodules:
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if (
                isinstance(path_value, str)
                and path_value
                and not Path(path_value).is_absolute()
            ):
                entry["path"] = str((template_path.parent / Path(path_value)).resolve())

    # Resolve call.module paths in workflow steps
    _resolve_call_paths(yaml_data.get("workflow", []), template_path.parent)

    if "parameters" not in yaml_data:
        yaml_data["parameters"] = {}

    index = query["index"]

    # Each instance gets its own sandbox output directory, named cohesively
    # with the host-side --output-dir.
    yaml_data["parameters"]["output_dir"] = (
        "/workspace/" + sandbox_query_dir(experiment_name, index) + "/"
    )

    instance_dir.mkdir(parents=True, exist_ok=True)
    custom_yaml_path = instance_dir / f"{index}.yaml"
    with open(custom_yaml_path, "w") as f:
        yaml.dump(yaml_data, f, default_flow_style=False)

    return str(custom_yaml_path)


def collect_instance_artifacts(
    mcp_client: "MCPClient",
    index: int,
    instance_dir: Path,
    experiment_name: str,
) -> List[str]:
    """Read intermediate artifacts back from the sandbox and save to host.

    Attempts to read output files (``draft.md``, ``draft.txt``, etc.)
    from the per-instance sandbox directory.

    Args:
        mcp_client: Active MCP client for the sandbox.
        index: Query index.
        instance_dir: Host-side per-instance directory.
        experiment_name: Basename of the user's ``--output-dir``.

    Returns:
        List of filenames that were successfully collected.
    """
    sandbox_dir = "/workspace/" + sandbox_query_dir(experiment_name, index)
    collected: List[str] = []

    # Try to list the sandbox directory
    try:
        ls_result = mcp_client.invoke(
            "shell_run", {"text": f"ls -1 {sandbox_dir} 2>/dev/null || true"}
        )
        output = ls_result.get("output", "") if isinstance(ls_result, dict) else ""
        filenames = [f.strip() for f in output.strip().split("\n") if f.strip()]
    except Exception:
        filenames = []

    # If ls failed or returned nothing, try known filenames directly
    if not filenames:
        filenames = [f"draft{ext}" for ext in _ARTIFACT_EXTENSIONS]

    for filename in filenames:
        sandbox_path = f"{sandbox_dir}/{filename}"
        try:
            result = mcp_client.invoke("fs_read", {"path": sandbox_path})
            text = None
            if isinstance(result, dict):
                text = result.get("text") or result.get("data")
            if text and text.strip():
                host_path = instance_dir / filename
                host_path.write_text(text, encoding="utf-8")
                collected.append(filename)
        except Exception:
            continue

    return collected
