"""
Workspace manifest: lightweight snapshot of workspace state.

Instead of copying the entire workspace via rsync, we capture a manifest
that records git repo metadata (remote, commit, diff, untracked files)
and small non-git files.  On restore we re-clone, checkout, apply patches,
and write back the small files.

Large or binary files that cannot be stored inline in the manifest are
copied to a *backup_dir* (persistent storage) and referenced by path so
they can be restored later.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Patterns that should always be skipped when scanning the workspace
DEFAULT_SCAN_IGNORES = [
    "logs",
    "outputs",
    "__pycache__",
    ".git",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "reproducibility",
    "node_modules",
    ".venv",
    "venv",
]


def _is_text_file(path: Path, sample_size: int = 8192) -> bool:
    """Heuristic check: read first *sample_size* bytes and look for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\x00" not in chunk
    except Exception:
        return False


def _should_ignore(name: str, ignores: List[str]) -> bool:
    """Check whether *name* matches any ignore pattern (simple glob)."""
    import fnmatch

    for pattern in ignores:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _run_git(cwd: Path, *args: str, timeout: int = 60) -> Optional[str]:
    """Run a git command, return stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _backup_large_file(
    src: Path,
    rel_path: str,
    backup_dir: Path,
    logger_fn: Callable[[str], None],
) -> Optional[str]:
    """Copy a file to *backup_dir* preserving its relative path.

    Returns the absolute path inside backup_dir on success, None on failure.
    """
    dest = backup_dir / "workspace_files" / rel_path
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        logger_fn(f"[Manifest] Large/binary file {rel_path} backed up to {dest}")
        return str(dest)
    except Exception as e:
        logger_fn(f"[Manifest] WARNING: failed to backup {rel_path}: {e}")
        return None


# ── capture ──────────────────────────────────────────────────────────


def capture_workspace_manifest(
    workspace_dir: Path,
    step_id: str,
    ignores: Optional[List[str]] = None,
    max_file_size: int = 1_000_000,  # 1 MB
    max_diff_size: int = 5_000_000,  # 5 MB
    backup_dir: Optional[Path] = None,
    logger: Optional[Callable[[str], None]] = None,
) -> dict:
    """Scan *workspace_dir* and return a lightweight manifest dict.

    Files that are text and smaller than *max_file_size* are stored inline.
    Larger or binary files are copied to *backup_dir* (if provided) and
    referenced by their backup path so they can be restored later.
    """

    def _log(msg: str) -> None:
        if logger:
            try:
                logger(msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    workspace_dir = Path(workspace_dir)
    ignore_list = list(ignores or DEFAULT_SCAN_IGNORES)

    manifest: Dict = {
        "step_id": str(step_id),
        "timestamp": datetime.now().isoformat(),
        "git_repos": [],
        "files": [],
        "directories": [],
    }

    if not workspace_dir.exists():
        _log(
            f"[Manifest] Workspace {workspace_dir} does not exist, returning empty manifest"
        )
        return manifest

    # Collect top-level entries (non-recursive first pass to detect git repos)
    git_repo_paths: List[Path] = []
    regular_entries: List[Path] = []

    for entry in sorted(workspace_dir.iterdir()):
        if _should_ignore(entry.name, ignore_list):
            continue
        if entry.is_dir():
            # Check if this directory is a git repo
            if (entry / ".git").exists():
                git_repo_paths.append(entry)
            else:
                regular_entries.append(entry)
        elif entry.is_file():
            regular_entries.append(entry)

    # ── git repos ────────────────────────────────────────────────────
    for repo_path in git_repo_paths:
        rel_path = str(repo_path.relative_to(workspace_dir))
        remote_url = _run_git(repo_path, "remote", "get-url", "origin")
        commit = _run_git(repo_path, "rev-parse", "HEAD")
        branch = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        diff = _run_git(repo_path, "diff", "HEAD", timeout=120)

        # Truncate large diffs
        diff_truncated = False
        if diff and len(diff) > max_diff_size:
            diff = diff[:max_diff_size]
            diff_truncated = True
            _log(
                f"[Manifest] WARNING: git diff for {rel_path} truncated "
                f"to {max_diff_size} bytes"
            )

        # Untracked files
        untracked_raw = _run_git(
            repo_path, "ls-files", "--others", "--exclude-standard"
        )
        untracked_files: Dict[str, Optional[str]] = {}
        untracked_backup_paths: Dict[str, str] = {}
        if untracked_raw:
            for fname in untracked_raw.splitlines():
                fpath = repo_path / fname
                if not fpath.is_file():
                    continue
                fsize = fpath.stat().st_size
                needs_backup = False
                if fsize > max_file_size:
                    needs_backup = True
                elif not _is_text_file(fpath):
                    needs_backup = True

                if needs_backup:
                    untracked_files[fname] = None
                    if backup_dir:
                        bk = _backup_large_file(
                            fpath,
                            os.path.join(rel_path, fname),
                            backup_dir,
                            _log,
                        )
                        if bk:
                            untracked_backup_paths[fname] = bk
                    else:
                        _log(
                            f"[Manifest] WARNING: untracked file {rel_path}/{fname} "
                            f"({fsize} bytes) too large or binary, no backup_dir"
                        )
                else:
                    try:
                        untracked_files[fname] = fpath.read_text(encoding="utf-8")
                    except Exception:
                        untracked_files[fname] = None

        repo_entry: Dict = {
            "path": rel_path,
            "remote_url": remote_url,
            "branch": branch,
            "commit": commit,
            "diff": diff,
            "diff_truncated": diff_truncated,
            "untracked_files": untracked_files,
            "untracked_backup_paths": untracked_backup_paths,
        }
        manifest["git_repos"].append(repo_entry)
        _log(
            f"[Manifest] Captured git repo: {rel_path} "
            f"(commit={commit[:8] if commit else '?'}, "
            f"diff={len(diff) if diff else 0} bytes, "
            f"untracked={len(untracked_files)})"
        )

    # ── regular files & directories ──────────────────────────────────

    def _record_file(entry: Path, rel: str) -> None:
        """Record a single file entry in the manifest.

        Small text files are stored inline; large or binary files are
        backed up to *backup_dir* (if available) and referenced by path.
        """
        fsize = entry.stat().st_size
        needs_backup = fsize > max_file_size or not _is_text_file(entry)

        if not needs_backup:
            try:
                content = entry.read_text(encoding="utf-8")
                manifest["files"].append(
                    {"path": rel, "content": content, "size": fsize}
                )
                return
            except Exception as e:
                _log(f"[Manifest] WARNING: could not read {rel}: {e}")
                needs_backup = True  # fall through to backup path

        # Large or binary — try backup
        backup_path_str = None
        if backup_dir:
            backup_path_str = _backup_large_file(entry, rel, backup_dir, _log)
        else:
            _log(
                f"[Manifest] WARNING: file {rel} ({fsize} bytes) "
                f"too large or binary, no backup_dir provided"
            )
        manifest["files"].append(
            {
                "path": rel,
                "content": None,
                "size": fsize,
                "backup_path": backup_path_str,
            }
        )

    def _scan_regular(base: Path, rel_prefix: str = "") -> None:
        """Recursively scan non-git entries."""
        for entry in sorted(base.iterdir()):
            if _should_ignore(entry.name, ignore_list):
                continue
            rel = os.path.join(rel_prefix, entry.name) if rel_prefix else entry.name

            if entry.is_dir():
                if (entry / ".git").exists():
                    _log(f"[Manifest] WARNING: nested git repo at {rel} skipped")
                    continue
                children = list(entry.iterdir())
                if not children:
                    manifest["directories"].append(rel)
                else:
                    _scan_regular(entry, rel)
            elif entry.is_file():
                _record_file(entry, rel)

    for entry in regular_entries:
        if entry.is_dir():
            children = list(entry.iterdir())
            if not children:
                manifest["directories"].append(str(entry.relative_to(workspace_dir)))
            else:
                _scan_regular(
                    entry,
                    str(entry.relative_to(workspace_dir)),
                )
        elif entry.is_file():
            _record_file(entry, str(entry.relative_to(workspace_dir)))

    _log(
        f"[Manifest] Capture complete: {len(manifest['git_repos'])} repos, "
        f"{len(manifest['files'])} files, {len(manifest['directories'])} dirs"
    )
    return manifest


# ── restore ──────────────────────────────────────────────────────────


def restore_workspace_from_manifest(
    manifest: dict,
    target_dir: Path,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """Rebuild workspace state from a previously captured manifest.

    Returns True if restore was fully successful, False if partial/failed.
    """

    def _log(msg: str) -> None:
        if logger:
            try:
                logger(msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    success = True

    # ── directories ──────────────────────────────────────────────────
    for d in manifest.get("directories", []):
        try:
            (target_dir / d).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _log(f"[Manifest-Restore] WARNING: could not create dir {d}: {e}")

    # ── git repos ────────────────────────────────────────────────────
    for repo in manifest.get("git_repos", []):
        rel_path = repo["path"]
        repo_dir = target_dir / rel_path
        remote_url = repo.get("remote_url")
        commit = repo.get("commit")
        diff = repo.get("diff")
        untracked = repo.get("untracked_files", {})

        if not remote_url or not commit:
            _log(
                f"[Manifest-Restore] WARNING: skipping repo {rel_path} "
                f"(missing remote_url or commit)"
            )
            success = False
            continue

        # Clone if not already present
        if not repo_dir.exists():
            _log(f"[Manifest-Restore] Cloning {remote_url} -> {rel_path}")
            try:
                result = subprocess.run(
                    ["git", "clone", remote_url, str(repo_dir)],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if result.returncode != 0:
                    _log(
                        f"[Manifest-Restore] ERROR: git clone failed for "
                        f"{rel_path}: {result.stderr}"
                    )
                    success = False
                    continue
            except Exception as e:
                _log(f"[Manifest-Restore] ERROR: git clone failed for {rel_path}: {e}")
                success = False
                continue

        # Checkout the exact commit
        _log(f"[Manifest-Restore] Checking out {commit[:8]} in {rel_path}")
        checkout_result = _run_git(repo_dir, "checkout", commit)
        if checkout_result is None:
            # Try fetching first in case the commit is not available locally
            _run_git(repo_dir, "fetch", "origin", timeout=300)
            checkout_result = _run_git(repo_dir, "checkout", commit)
            if checkout_result is None:
                _log(
                    f"[Manifest-Restore] WARNING: could not checkout "
                    f"{commit[:8]} in {rel_path}"
                )
                success = False

        # Apply diff patch
        if diff:
            _log(f"[Manifest-Restore] Applying patch ({len(diff)} bytes) to {rel_path}")
            try:
                proc = subprocess.run(
                    ["git", "apply", "--allow-empty", "-"],
                    input=diff,
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if proc.returncode != 0:
                    # Try with --reject for partial apply
                    _log(
                        f"[Manifest-Restore] WARNING: git apply failed, "
                        f"trying with --reject: {proc.stderr}"
                    )
                    proc2 = subprocess.run(
                        ["git", "apply", "--reject", "--allow-empty", "-"],
                        input=diff,
                        cwd=str(repo_dir),
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if proc2.returncode != 0:
                        _log(
                            f"[Manifest-Restore] WARNING: git apply --reject "
                            f"also failed for {rel_path}: {proc2.stderr}"
                        )
                        success = False
            except Exception as e:
                _log(
                    f"[Manifest-Restore] WARNING: patch apply error for {rel_path}: {e}"
                )
                success = False

        # Write untracked files
        untracked_backups = repo.get("untracked_backup_paths", {})
        for fname, content in untracked.items():
            fpath = repo_dir / fname
            if content is not None:
                try:
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(content, encoding="utf-8")
                except Exception as e:
                    _log(
                        f"[Manifest-Restore] WARNING: could not write "
                        f"untracked file {rel_path}/{fname}: {e}"
                    )
            elif fname in untracked_backups:
                bk = Path(untracked_backups[fname])
                if bk.exists():
                    try:
                        fpath.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(bk), str(fpath))
                        _log(
                            f"[Manifest-Restore] Restored untracked file from backup: {rel_path}/{fname}"
                        )
                    except Exception as e:
                        _log(
                            f"[Manifest-Restore] WARNING: could not restore {rel_path}/{fname} from backup: {e}"
                        )
                        success = False
                else:
                    _log(
                        f"[Manifest-Restore] WARNING: backup file missing for {rel_path}/{fname}: {bk}"
                    )
                    success = False
            else:
                _log(
                    f"[Manifest-Restore] WARNING: untracked file "
                    f"{rel_path}/{fname} has no saved content and no backup, skipping"
                )

        _log(f"[Manifest-Restore] Repo {rel_path} restored")

    # ── regular files ────────────────────────────────────────────────
    for finfo in manifest.get("files", []):
        rel_path = finfo["path"]
        content = finfo.get("content")
        fpath = target_dir / rel_path

        if content is not None:
            try:
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
            except Exception as e:
                _log(
                    f"[Manifest-Restore] WARNING: could not write file {rel_path}: {e}"
                )
                success = False
            continue

        # No inline content — try backup_path
        bk_path_str = finfo.get("backup_path")
        if bk_path_str:
            bk = Path(bk_path_str)
            if bk.exists():
                try:
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(bk), str(fpath))
                    _log(f"[Manifest-Restore] Restored from backup: {rel_path}")
                except Exception as e:
                    _log(
                        f"[Manifest-Restore] WARNING: could not restore {rel_path} from backup: {e}"
                    )
                    success = False
            else:
                _log(
                    f"[Manifest-Restore] WARNING: backup file missing for {rel_path}: {bk}"
                )
                success = False
        else:
            _log(
                f"[Manifest-Restore] WARNING: file {rel_path} has no saved "
                f"content and no backup, skipping"
            )

    _log(
        f"[Manifest-Restore] Restore complete "
        f"(success={success}, step_id={manifest.get('step_id', '?')})"
    )
    return success
