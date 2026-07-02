import os
from datetime import datetime
from pathlib import Path

WORKSPACE_DIR = os.environ.get("VM_WORKSPACE")

if not WORKSPACE_DIR:
    raise RuntimeError(
        "Environment variable VM_WORKSPACE is not set. Please set it to your workspace directory."
    )

if not WORKSPACE_DIR.startswith("/"):
    raise RuntimeError("VM_WORKSPACE must be an absolute path starting with /")


# this ensure the path is always under /workspace
def filename_to_path(p: str) -> Path:
    path = Path(p).expanduser()
    # Normalize accidental leading 'workspace/' duplication from callers
    try:
        s = str(path)
        if s.startswith("workspace/"):
            path = Path(s[len("workspace/") :])
    except Exception:
        pass

    # Convert to absolute path under WORKSPACE_DIR if relative
    if not path.is_absolute():
        path = Path(WORKSPACE_DIR) / path

    # Resolve to canonical path (resolves symlinks, '..', etc.)
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as e:
        raise PermissionError(f"Cannot resolve path: {p}") from e

    # Security check: verify resolved path is under WORKSPACE_DIR
    workspace_resolved = Path(WORKSPACE_DIR).resolve()
    try:
        # relative_to raises ValueError if resolved is not under workspace_resolved
        resolved.relative_to(workspace_resolved)
    except ValueError as e:
        raise PermissionError(
            f"Path '{p}' escapes workspace. Resolved to '{resolved}', "
            f"which is outside of workspace '{workspace_resolved}'"
        ) from e

    return resolved


def path_to_filename(p: Path) -> Path:
    """
    Convert any path `p` to a path relative to WORKSPACE_DIR.
    If not under /workspace, we force it to be under WORKSPACE_DIR using filename_to_path.

    This ensures the output path is always relative to WORKSPACE_DIR.
    """
    workspace_resolved = Path(WORKSPACE_DIR).resolve()
    if str(p).startswith(str(workspace_resolved) + "/"):
        return p.relative_to(workspace_resolved)

    full_path = filename_to_path(str(p))
    return full_path.relative_to(workspace_resolved)


def tool_log(message: str = ""):
    try:
        log_file = filename_to_path(os.environ.get("TOOL_LOG_FILE"))
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")
    except Exception as e:
        pass
    return


def tool_result_ok(results) -> bool:
    if results is None:
        return False
    if not isinstance(results, dict):
        return True

    return "error" not in results
