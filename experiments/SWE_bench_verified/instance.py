"""Instance processing functions for SWE-Bench runner.

This module handles running the agent on individual SWE-Bench instances,
including YAML customization, patch extraction, and result collection.
"""

import json
import re
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import yaml
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS

from .config import AgentArgs, InstanceResult
from .shell_utils import (
    Logger, execute_command_via_shell_run)

if TYPE_CHECKING:
    from harness.agent import AgentSPEX
    from mcp_client.client import MCPClient

__all__ = ["run_instance", "save_patch_to_jsonl", "prepare_yaml_for_instance"]


def save_patch_to_jsonl(
    instance_id: str,
    patch_text: str,
    model_name: str,
    output_file: Path,
) -> None:
    """Append patch to predictions.jsonl for SWE-Bench evaluation."""
    if patch_text and not patch_text.endswith("\n"):
        patch_text += "\n"
    pred = {
        "instance_id": instance_id,
        "model_name_or_path": model_name,
        "model_patch": patch_text,
    }

    with open(output_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(pred) + "\n")

    print(f"Saved patch for {instance_id}")


def _strip_conda_run_prefix(test_cmd: str) -> str:
    """Strip 'conda run -n <env>' or 'conda run --name <env>' prefix from a test command.

    SWE-bench test_cmd values look like 'conda run -n testbed pytest -rA'.
    The Docker container activates the conda env via .bashrc, so we only need
    the bare test runner (e.g. 'pytest -rA').
    """
    # Match: conda run (-n|--name) <env_name> <rest...>
    m = re.match(r"conda\s+run\s+(?:-n|--name)\s+\S+\s+(.+)", test_cmd)
    if m:
        return m.group(1)
    return test_cmd


def _build_regression_test_cmd(instance: Dict[str, Any]) -> str:
    """Build a regression test command from the repo's full test suite."""
    if MAP_REPO_VERSION_TO_SPECS is None:
        return ""

    repo = instance.get("repo", "")
    version = instance.get("version", "")

    try:
        specs = MAP_REPO_VERSION_TO_SPECS[repo][version]
    except (KeyError, TypeError):
        return ""

    test_cmd = specs.get("test_cmd", "")
    if not test_cmd:
        return ""

    return _strip_conda_run_prefix(test_cmd)


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
        # Recurse into nested step lists
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
    instance: Dict[str, Any],
    repo_path: str,
    output_dir: Path,
    conda_env_name: Optional[str] = None,
) -> str:
    """Create customized YAML from template for a specific instance."""
    template_path = Path(yaml_file).resolve()
    with open(template_path, "r") as f:
        yaml_data = yaml.safe_load(f)

    # Resolve submodule paths relative to the template file location
    submodules = yaml_data.get("submodules")
    if isinstance(submodules, list):
        for entry in submodules:
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            path_obj = Path(path_value)
            if not path_obj.is_absolute():
                entry["path"] = str((template_path.parent / path_obj).resolve())

    # Resolve call.module paths in workflow steps (recursively)
    _resolve_call_paths(yaml_data.get("workflow", []), template_path.parent)

    if "parameters" not in yaml_data:
        yaml_data["parameters"] = {}

    yaml_data["parameters"]["code_path"] = repo_path
    yaml_data["parameters"]["instance_id"] = instance["instance_id"]
    yaml_data["parameters"]["problem_statement"] = instance["problem_statement"]
    yaml_data["parameters"]["conda_env_name"] = conda_env_name or "base"
    yaml_data["parameters"]["task_name"] = instance["instance_id"]

    # Build regression test command from PASS_TO_PASS tests
    regression_test_cmd = _build_regression_test_cmd(instance)
    yaml_data["parameters"]["regression_test_cmd"] = regression_test_cmd

    custom_yaml_path = output_dir / f"{instance['instance_id']}.yaml"
    with open(custom_yaml_path, "w") as f:
        yaml.dump(yaml_data, f, default_flow_style=False)

    return str(custom_yaml_path)


def run_instance(
    instance: Dict[str, Any],
    agent: "AgentSPEX",
    mcp_client: "MCPClient",
    args,
    output_dir: Path,
    save_logs: bool = False,
) -> InstanceResult:
    """Run the agent on a single SWE-Bench instance."""
    instance_id = instance["instance_id"]
    problem_statement = instance["problem_statement"]

    host_log_path = output_dir / f"{instance_id}_full.log" if save_logs else None
    log_file = str(output_dir / f"{instance_id}_full.log")
    event_log_file = str(output_dir / f"{instance_id}_agent_events.log")
    host_event_log_path = output_dir / f"{instance_id}_agent_events.log"
    logger = Logger(
        mcp_client=mcp_client,
        log_file=log_file,
        host_log_path=host_log_path,
        event_log_path=event_log_file,
        host_event_log_path=host_event_log_path,
        deduplicate=True,
    )

    logger(f"\n{'#'*80}")
    logger(f"Processing instance: {instance_id}")
    logger(f"{'#'*80}\n")

    try:
        repo_path = "/testbed"
        conda_env_to_use = "testbed"

        custom_yaml_file = prepare_yaml_for_instance(
            args.workflow_file,
            instance,
            repo_path,
            output_dir,
            conda_env_name=conda_env_to_use,
        )

        # Get model from CLI args, or fall back to workflow config
        model = getattr(args, "model", None)
        if not model:
            # Read model from workflow config
            with open(args.workflow_file, "r") as f:
                workflow = yaml.safe_load(f)
            model = workflow.get("config", {}).get("model", "gpt-4.1-mini")

        agent_args = AgentArgs(
            workflow_file=custom_yaml_file,
            model=model,
            problem_statement=problem_statement,
        )

        logger(f"Running agent on {instance_id}...")

        _ = agent.run(agent_args, external_logger=logger)

        for path_key, file_suffix in [
            ("final-output.txt", "_final_output.txt"),
            ("summary.txt", "_summary.txt"),
        ]:
            result = mcp_client.invoke(
                "fs_read", {"path": f"outputs/{instance_id}/{path_key}"}
            )
            if isinstance(result, dict) and "data" in result:
                output_file = output_dir / f"{instance_id}{file_suffix}"
                output_file.write_text(result["data"])

        for step_num in range(1, 50):
            result = mcp_client.invoke(
                "fs_read", {"path": f"outputs/{instance_id}/step-{step_num}-output.txt"}
            )
            if isinstance(result, dict) and "data" in result:
                step_file = output_dir / f"{instance_id}_step_{step_num}_output.txt"
                step_file.write_text(result["data"])
            else:
                break

        # Generate patch in harness: reset index, then stage only
        # modifications to already-tracked files (git add -u skips
        # untracked/new files), and produce the diff.
        execute_command_via_shell_run(
            mcp_client,
            f"cd {repo_path} && git reset HEAD . 2>/dev/null; git add -u",
            logger=logger,
            allow_failure=True,
            log_output=False,
        )
        git_diff_result = execute_command_via_shell_run(
            mcp_client,
            f"cd {repo_path} && git diff --cached",
            logger=logger,
            allow_failure=True,
            log_output=False,
        )
        patch_text = git_diff_result.get("output", "")

        if patch_text.strip():
            if not patch_text.endswith("\n"):
                patch_text += "\n"
            instance_patch_file = output_dir / f"{instance_id}.diff"
            instance_patch_file.write_text(patch_text)
            return InstanceResult(
                instance_id=instance_id,
                success=True,
                patch=patch_text,
            )

        return InstanceResult(
            instance_id=instance_id,
            success=False,
            error="No patch found",
        )

    except Exception as e:
        logger(f"Error processing {instance_id}: {str(e)}")
        tb_str = traceback.format_exc()
        logger(tb_str)
        return InstanceResult(
            instance_id=instance_id,
            success=False,
            error=str(e),
        )
