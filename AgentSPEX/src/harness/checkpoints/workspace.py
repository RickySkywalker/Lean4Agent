"""
Workspace backup and restore utilities.

This module provides functions for backing up and restoring workspace directories
during checkpoint operations.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

# Default patterns to ignore during backup/restore
DEFAULT_IGNORES = [
    "logs",
    "outputs",
    "__pycache__",
    ".git",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "reproducibility",
]


def backup_workspace(
    source_dir: Path,
    target_dir: Path,
    additional_ignores: Optional[List[str]] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Backup the source directory to the target directory using rsync for incremental sync.
    Falls back to shutil.copytree if rsync is not available.

    Args:
        source_dir: The directory to backup (e.g., HOST_WORKSPACE).
        target_dir: The destination directory (e.g., inside outputs).
        additional_ignores: List of patterns to ignore in addition to defaults.
        logger: Optional logger callable for status messages.

    Returns:
        True if backup succeeded, False otherwise.
    """

    def _log(msg: str) -> None:
        try:
            if logger:
                logger(msg)
            else:
                print(msg)
        except Exception:
            print(msg)  # Fallback if logger fails (e.g. log file path missing)

    source_dir = Path(source_dir)
    target_dir = Path(target_dir)

    if not source_dir.exists():
        _log(f"[Checkpoint] Backup skipped: source {source_dir} does not exist")
        return False

    # Ensure target parent exists
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    # Build ignore patterns
    ignores = list(DEFAULT_IGNORES)
    if additional_ignores:
        ignores.extend(additional_ignores)

    # Try rsync first (incremental, faster for subsequent backups)
    try:
        # Build rsync command
        # Use --no-owner --no-group to avoid permission errors when syncing
        # files created by different users (e.g., docker container vs host).
        # Use --ignore-errors so unreadable files (e.g. container-created) don't fail the whole backup.
        cmd = [
            "rsync",
            "-a",
            "--delete",
            "--no-owner",
            "--no-group",
            "--ignore-errors",
        ]
        for pattern in ignores:
            cmd.extend(["--exclude", pattern])
        # Trailing slash on source means "contents of"
        cmd.extend([f"{source_dir}/", f"{target_dir}/"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        # 0 = success; 23 = partial (some files skipped, e.g. permission denied)
        if result.returncode not in (0, 23):
            raise subprocess.SubprocessError(f"rsync failed: {result.stderr}")
        if result.returncode == 23:
            _log(
                "[Checkpoint] Workspace backed up (rsync, partial: some files skipped due to permissions)"
            )
        else:
            _log(
                f"[Checkpoint] Workspace backed up (rsync): {source_dir} -> {target_dir}"
            )
        return True

    except (FileNotFoundError, subprocess.SubprocessError) as e:
        # rsync not available or failed, fall back to shutil
        _log(
            f"[Checkpoint] rsync unavailable or failed ({e}), falling back to shutil.copytree"
        )
        try:
            ignore_func = shutil.ignore_patterns(*ignores)

            def _safe_copy(src, dst):
                try:
                    shutil.copy2(src, dst)
                except (PermissionError, OSError):
                    pass  # Skip unreadable files (e.g. container-created)

            shutil.copytree(
                source_dir,
                target_dir,
                dirs_exist_ok=True,
                ignore=ignore_func,
                copy_function=_safe_copy,
            )
            _log(
                f"[Checkpoint] Workspace backed up (shutil): {source_dir} -> {target_dir}"
            )
            return True
        except Exception as e2:
            _log(f"[Checkpoint] ERROR: Failed to backup workspace: {e2}")
            return False
    except Exception as e:
        _log(f"[Checkpoint] ERROR: Failed to backup workspace: {e}")
        return False


def restore_workspace(
    backup_dir: Path,
    target_dir: Path,
    additional_ignores: Optional[List[str]] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Restore workspace from backup during resume using rsync.
    Falls back to shutil.copytree if rsync is not available.

    Args:
        backup_dir: The backup directory to restore from.
        target_dir: The destination directory (e.g., HOST_WORKSPACE).
        additional_ignores: List of patterns to ignore in addition to defaults.
        logger: Optional logger callable for status messages.

    Returns:
        True if restore succeeded, False otherwise.
    """

    def _log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    backup_dir = Path(backup_dir)
    target_dir = Path(target_dir)

    if not backup_dir.exists():
        _log(f"[Checkpoint] Restore skipped: backup {backup_dir} does not exist")
        return False

    # Check if backup has any content
    if not any(backup_dir.iterdir()):
        _log(f"[Checkpoint] Restore skipped: backup {backup_dir} is empty")
        return False

    # Ensure target exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Build ignore patterns
    ignores = list(DEFAULT_IGNORES)
    if additional_ignores:
        ignores.extend(additional_ignores)

    # Try rsync first
    try:
        # Use --checksum to force sync based on content, not just timestamps
        # This ensures backed-up content overwrites modified files
        # Use --no-owner --no-group to avoid permission errors
        cmd = ["rsync", "-a", "--checksum", "--no-owner", "--no-group"]
        # Note: We don't use --delete on restore to preserve any new files in target
        for pattern in ignores:
            cmd.extend(["--exclude", pattern])
        cmd.extend([f"{backup_dir}/", f"{target_dir}/"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise subprocess.SubprocessError(f"rsync failed: {result.stderr}")

        _log(f"[Checkpoint] Workspace restored (rsync): {backup_dir} -> {target_dir}")
        return True

    except (FileNotFoundError, subprocess.SubprocessError) as e:
        # rsync not available or failed, fall back to shutil
        _log(
            f"[Checkpoint] rsync unavailable or failed ({e}), falling back to shutil.copytree"
        )
        try:
            ignore_func = shutil.ignore_patterns(*ignores)
            shutil.copytree(
                backup_dir, target_dir, dirs_exist_ok=True, ignore=ignore_func
            )
            _log(
                f"[Checkpoint] Workspace restored (shutil): {backup_dir} -> {target_dir}"
            )
            return True
        except Exception as e2:
            _log(f"[Checkpoint] ERROR: Failed to restore workspace: {e2}")
            return False
    except Exception as e:
        _log(f"[Checkpoint] ERROR: Failed to restore workspace: {e}")
        return False


def restore_task_files(
    backup_dir: Path,
    target_dir: Path,
    task_output_subdir: str,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Restore only the specific task's output files from backup.

    This method restores:
    1. The task's output directory (e.g., outputs/<task_name>/)
    2. Any other non-outputs files in the workspace

    Args:
        backup_dir: The backup directory (e.g., workspace_persistent).
        target_dir: The target workspace directory (e.g., HOST_WORKSPACE).
        task_output_subdir: The relative path to the task's output dir (e.g., "outputs/my_task").
        logger: Optional logger callable.

    Returns:
        True if restore succeeded, False otherwise.
    """

    def _log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    backup_dir = Path(backup_dir)
    target_dir = Path(target_dir)

    if not backup_dir.exists():
        _log(f"[Checkpoint] Task restore skipped: backup {backup_dir} does not exist")
        return False

    success = True
    task_outputs_found = False

    # 1. Restore the specific task's output directory
    task_backup = backup_dir / task_output_subdir
    task_target = target_dir / task_output_subdir

    if task_backup.exists():
        task_target.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Use --ignore-errors to continue even if some files can't be transferred
            # Use --partial to keep partially transferred files
            cmd = [
                "rsync",
                "-a",
                "--checksum",
                "--no-owner",
                "--no-group",
                "--ignore-errors",
                "--partial",
                "--exclude",
                "logs",
                "--exclude",
                "__pycache__",
                f"{task_backup}/",
                f"{task_target}/",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            # rsync returns 23 for partial transfer (some files couldn't be transferred)
            if result.returncode not in (0, 23):
                raise subprocess.SubprocessError(f"rsync failed: {result.stderr}")
            if result.returncode == 23:
                _log(
                    "[Checkpoint] Task outputs partially restored (some files skipped due to permissions)"
                )
            else:
                _log(
                    f"[Checkpoint] Task outputs restored (rsync): {task_backup} -> {task_target}"
                )
            task_outputs_found = True
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            _log(f"[Checkpoint] rsync failed ({e}), trying shutil.copytree")
            try:
                ignore_func = shutil.ignore_patterns("logs", "__pycache__", "*.pyc")

                # Use copy_function that ignores errors
                def safe_copy(src, dst):
                    try:
                        shutil.copy2(src, dst)
                    except (PermissionError, OSError):
                        pass  # Ignore permission errors

                shutil.copytree(
                    task_backup,
                    task_target,
                    dirs_exist_ok=True,
                    ignore=ignore_func,
                    copy_function=safe_copy,
                )
                _log(
                    f"[Checkpoint] Task outputs restored (shutil): {task_backup} -> {task_target}"
                )
                task_outputs_found = True
            except Exception as e2:
                _log(f"[Checkpoint] ERROR: Could not restore task outputs: {e2}")
                success = False
    else:
        _log(f"[Checkpoint] No backup found for task outputs: {task_backup}")
        # Not a failure if no backup exists - may be first run

    # 2. Restore non-outputs files (e.g., downloaded files, created directories)
    # Only sync directories that are NOT "outputs"
    try:
        for item in backup_dir.iterdir():
            if item.name in ["outputs", "logs", "__pycache__", ".git"]:
                continue

            target_item = target_dir / item.name

            if item.is_dir():
                try:
                    cmd = [
                        "rsync",
                        "-a",
                        "--checksum",
                        "--no-owner",
                        "--no-group",
                        "--exclude",
                        "logs",
                        "--exclude",
                        "__pycache__",
                        f"{item}/",
                        f"{target_item}/",
                    ]
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=300
                    )
                    if result.returncode != 0:
                        # Try shutil fallback
                        shutil.copytree(
                            item,
                            target_item,
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("logs", "__pycache__"),
                        )
                except Exception:
                    try:
                        shutil.copytree(
                            item,
                            target_item,
                            dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("logs", "__pycache__"),
                        )
                    except Exception as e:
                        _log(
                            f"[Checkpoint] Warning: Could not restore {item.name}: {e}"
                        )
            elif item.is_file():
                try:
                    target_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target_item)
                except Exception as e:
                    _log(
                        f"[Checkpoint] Warning: Could not restore file {item.name}: {e}"
                    )

    except Exception as e:
        _log(f"[Checkpoint] Warning: Error during non-outputs restore: {e}")

    if success:
        _log(f"[Checkpoint] Task workspace restored for: {task_output_subdir}")

    return success


def best_effort_host_write_text(
    path: str | Path,
    content: str,
    *,
    append: bool = False,
) -> None:
    """
    Best-effort mirror write on host filesystem.

    Rationale: MCP fs_write writes into the sandbox workspace (container /workspace),
    while checkpoints are persisted on the host. Mirroring key artifacts to the host
    keeps outputs self-contained under the host output_dir.

    Args:
        path: Path to write to
        content: Content to write
        append: If True, append instead of overwrite
    """
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with p.open("a", encoding="utf-8") as f:
                f.write(str(content))
        else:
            p.write_text(str(content), encoding="utf-8")
    except Exception:
        # Best-effort mirror write on host filesystem; failure here is non-critical.
        return
