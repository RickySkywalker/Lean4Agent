"""Reproducibility snapshot utilities.

This module provides functionality to create reproducibility snapshots
for agent runs, capturing the exact configuration and code state.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from ..parsing.yaml_parser import YAMLTaskParser
from ..submodules.loader import normalize_submodule_declarations


def create_reproducibility_snapshot(
    output_dir: Path,
    workflow_file: str,
    task_env_file: Optional[str] = None,
    checkpoint_path: Optional[str] = None,
    trace_path: Optional[str] = None,
    resume: bool = False,
    mcp_url: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> Path:
    """Create a reproducibility snapshot for an agent run.

    This function creates a `reproducibility/` directory under the output
    directory containing:
    - run_config.env: Run configuration and CLI args
    - workflow_snapshot.*: Copy of the workflow file used
    - vm.env, host.env, task.env: Environment files used
    - git_HEAD.txt: Git commit SHA
    - git_status.txt: Git status at run start
    - git_diff.patch: Uncommitted changes
    - README.txt: Description of snapshot contents

    Args:
        output_dir: Output directory for the agent run
        workflow_file: Path to workflow file
        task_env_file: Optional path to task environment file
        checkpoint_path: Optional checkpoint path
        trace_path: Optional trace path
        resume: Whether this is a resume run
        mcp_url: MCP server URL
        project_root: Project root directory (auto-detected if not provided)

    Returns:
        Path to the reproducibility directory
    """
    if project_root is None:
        # Auto-detect project root: go up from this file to repo root
        project_root = Path(__file__).parent.parent.parent.parent

    repro_dir = output_dir / "reproducibility"
    repro_dir.mkdir(parents=True, exist_ok=True)

    # Get current timestamp
    try:
        timestamp = subprocess.run(
            ["date", "-Iseconds"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")

    # Write run configuration
    run_config_lines = [
        f"# Run config snapshot at {timestamp}",
        f"output_dir={output_dir}",
        f"reproducibility_dir={repro_dir.resolve()}",
        f"workflow_file={workflow_file}",
    ]
    if task_env_file:
        run_config_lines.append(f"task_env_file={task_env_file}")
    if checkpoint_path:
        run_config_lines.append(f"checkpoint_path={checkpoint_path}")
    if trace_path:
        run_config_lines.append(f"trace_path={trace_path}")
    if resume:
        run_config_lines.append("resume=true")
    if mcp_url:
        run_config_lines.append(f"mcp_url={mcp_url}")
    run_config_lines.append(f"project_root={project_root}")

    (repro_dir / "run_config.env").write_text("\n".join(run_config_lines) + "\n")

    # Copy environment files if they exist
    _copy_file_if_exists(project_root / "config" / "vm.env", repro_dir / "vm.env")
    _copy_file_if_exists(project_root / "config" / "host.env", repro_dir / "host.env")

    if task_env_file:
        env_path = Path(task_env_file)
        if not env_path.is_absolute():
            env_path = project_root / task_env_file
        _copy_file_if_exists(env_path, repro_dir / "task.env")

    # Copy workflow file with appropriate extension
    if workflow_file:
        plan_path = Path(workflow_file)
        if not plan_path.is_absolute():
            plan_path = project_root / workflow_file
        if plan_path.exists():
            # Preserve original extension
            if plan_path.suffix in [".yaml", ".yml", ".json"]:
                dest_name = f"workflow_snapshot{plan_path.suffix}"
            else:
                dest_name = "workflow_snapshot"
            _copy_file_if_exists(plan_path, repro_dir / dest_name)

            # Also copy all submodules referenced (recursively)
            _copy_submodules_for_workflow(plan_path, project_root, repro_dir)

    # Capture git state
    _capture_git_state(project_root, repro_dir)

    # Write README
    readme_content = """Reproducibility snapshot for this sandbox run.
  run_config.env       - CLI args and key run options
  workflow_snapshot.* - exact workflow file used
  submodules/**        - submodule task files referenced by the workflow
  vm.env, host.env, task.env - env files used
  git_HEAD.txt         - commit SHA (or not-a-git-repo)
  git_status.txt       - git status at run start
  git_diff.patch       - uncommitted changes (apply from repo root: git apply reproducibility/git_diff.patch)
"""
    (repro_dir / "README.txt").write_text(readme_content)

    return repro_dir


def _copy_file_if_exists(src: Path, dest: Path) -> bool:
    """Copy a file if it exists.

    Args:
        src: Source file path
        dest: Destination file path

    Returns:
        True if file was copied, False otherwise
    """
    try:
        if src.exists():
            dest.write_bytes(src.read_bytes())
            return True
    except (OSError, IOError):
        pass
    return False


def _collect_submodule_paths(root_plan: Path) -> Set[Path]:
    """Recursively collect all submodule/module YAML paths referenced by a workflow.

    This currently supports:
    - Formal `submodules` declarations (via normalize_submodule_declarations)
    - Workflow modules referenced via `module: "modules/xxx.yaml"` in the YAML
    """
    parser = YAMLTaskParser()
    visited: Set[Path] = set()
    stack = [root_plan]
    root_base = root_plan.parent

    while stack:
        current = stack.pop()
        try:
            yaml_data = parser.load_task(str(current))
        except Exception:
            # If we can't parse a submodule, skip it but continue with others
            continue
        # 1) Collect submodules declared via the `submodules` field
        try:
            submodules = normalize_submodule_declarations(yaml_data, str(current))
        except Exception:
            # If submodule declarations are invalid, skip but continue with other mechanisms
            submodules = []

        for entry in submodules:
            path_str = entry.get("path")
            if not path_str:
                continue
            sub_path = Path(path_str).resolve()
            if sub_path.exists() and sub_path not in visited:
                visited.add(sub_path)
                stack.append(sub_path)

        # 2) Collect workflow modules referenced via `module: "modules/xxx.yaml"`

        def _iter_module_paths(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "module" and isinstance(v, str):
                        yield v
                    else:
                        yield from _iter_module_paths(v)
            elif isinstance(node, list):
                for item in node:
                    yield from _iter_module_paths(item)

        for module_rel in _iter_module_paths(yaml_data):
            # Resolve module path using the same semantics as runtime:
            # - absolute paths are used as-is
            # - relative paths may be resolved using multiple strategies:
            #   * relative to the current file directory
            #   * relative to the root plan directory
            #   * under any sibling "<root_stem>_modules/**" directory (used by UI)
            rel_obj = Path(module_rel)
            candidates: Set[Path] = set()
            if os.path.isabs(module_rel):
                candidates.add(Path(module_rel))
            else:
                # 1) Relative to current file and root plan
                candidates.add((current.parent / rel_obj))
                candidates.add((root_base / rel_obj))

                # 2) Relative to any "<root_stem>_modules/**" directory adjacent to root
                ui_modules_dir = root_base / f"{root_plan.stem}_modules"
                if ui_modules_dir.exists():
                    # Prefer matches where the tail of the path matches module_rel,
                    # but fall back to filename match if needed.
                    tail = (
                        "/".join(rel_obj.parts[-2:])
                        if len(rel_obj.parts) >= 2
                        else rel_obj.name
                    )
                    for p in ui_modules_dir.rglob("*.yaml"):
                        p_posix = p.as_posix()
                        if (
                            p_posix.endswith(module_rel)
                            or p_posix.endswith(tail)
                            or p.name == rel_obj.name
                        ):
                            candidates.add(p)

            for module_path in {c.resolve() for c in candidates}:
                if module_path.exists() and module_path not in visited:
                    visited.add(module_path)
                    stack.append(module_path)
    # Do not include the root plan itself in the submodule set
    visited.discard(root_plan.resolve())
    return visited


def _copy_submodules_for_workflow(
    plan_path: Path, project_root: Path, repro_dir: Path
) -> None:
    """Copy all submodule YAMLs referenced (recursively) by the workflow.

    Submodules are copied under a `submodules/` directory inside the
    reproducibility snapshot. Paths are preserved relative to the project root
    when possible, falling back to basenames otherwise.
    """
    # Discover submodules/modules by parsing YAML relationships. This works
    # uniformly for both CLI and YAML Flow Editor runs, since the latter
    # produces a self-contained run_<id>.yaml that references its modules.
    try:
        submodule_paths = _collect_submodule_paths(plan_path)
    except Exception:
        # Best-effort only: do not fail reproducibility snapshot if this fails
        return

    if not submodule_paths:
        return

    # For simplicity and portability, store all discovered module/submodule YAMLs
    # under a flat `modules/` directory, preserving only the filename. This
    # matches the expected layout used for reproducibility.
    modules_root = repro_dir / "modules"
    for sub_path in sorted(submodule_paths):
        try:
            dest = modules_root / sub_path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            _copy_file_if_exists(sub_path, dest)
        except Exception:
            # Ignore individual copy errors to keep snapshot best-effort
            continue


def ensure_workflow_submodules_snapshot(
    output_dir: Path,
    workflow_file: str,
    project_root: Optional[Path] = None,
) -> None:
    """Ensure that submodules for a given workflow are captured in reproducibility/.

    This is intended to be safe to call even when a reproducibility snapshot
    was already created by an external wrapper script (e.g., run_agent.sh).
    It will:
    - No-op if reproducibility/ or workflow_file do not exist
    - Otherwise, add/update files under reproducibility/submodules/ as needed
    """
    if not workflow_file:
        return

    if project_root is None:
        project_root = Path(__file__).parent.parent.parent.parent

    repro_dir = output_dir / "reproducibility"
    if not repro_dir.exists():
        return

    plan_path = Path(workflow_file)
    if not plan_path.is_absolute():
        plan_path = project_root / workflow_file
    if not plan_path.exists():
        return

    _copy_submodules_for_workflow(plan_path, project_root, repro_dir)


def _capture_git_state(project_root: Path, repro_dir: Path) -> None:
    """Capture git state (HEAD, status, diff) to reproducibility directory.

    Args:
        project_root: Project root directory
        repro_dir: Reproducibility directory to write to
    """
    try:
        # Check if this is a git repository
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            (repro_dir / "git_HEAD.txt").write_text("not-a-git-repo\n")
            return

        # Get HEAD commit SHA
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            (repro_dir / "git_HEAD.txt").write_text(result.stdout)

        # Get git status
        result = subprocess.run(
            ["git", "-C", str(project_root), "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            (repro_dir / "git_status.txt").write_text(result.stdout)

        # Get git diff
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            (repro_dir / "git_diff.patch").write_text(result.stdout)

    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # Git not available or other error - write placeholder
        (repro_dir / "git_HEAD.txt").write_text("git-unavailable\n")
