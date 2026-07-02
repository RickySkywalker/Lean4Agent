from pathlib import Path
from typing import Union

from fastmcp import Context


def _ok(**k):
    return {**k}


def _err(msg: str, **k):
    return {"error": msg, **k}


def _sid(ctx: Context) -> str:
    sid = getattr(ctx, "session_id", None)
    if not sid:
        raise KeyError("session_id missing")
    return sid


def _to_vpath(
    session_root: Union[Path, str], real_path: Union[Path, str], *, prefix: bool = False
) -> str:
    """
    Convert a real path under `session_root` to a vpath.

    Raises PermissionError if `real_path` is outside `session_root`.
    """
    rp = Path(real_path).resolve()
    base = Path(session_root).resolve()
    if not str(rp).startswith(str(base)):
        raise PermissionError("real path not under session root")
    rel = rp.relative_to(base)
    v = "/" + str(rel)
    return ("sandbox:" + v) if prefix else v


def _from_vpath(session_root: Union[Path, str], vpath: str) -> Path:
    """
    Convert a vpath back into a real path inside `session_root`.

    Raises ValueError for malformed input
    Raises PermissionError if resolution would escape the session root.
    """
    if not vpath:
        raise ValueError(f"invalid vpath: {vpath!r}")
    if isinstance(vpath, Path):
        vpath = str(vpath)

    if vpath.startswith("sandbox:/"):
        vpath = vpath[len("sandbox:") :]

    if not vpath.startswith("/"):
        vpath = "/" + vpath

    base = Path(session_root).resolve()
    rp = (base / vpath.lstrip("/")).resolve()

    if not str(rp).startswith(str(base)):
        raise PermissionError("vpath escapes session root")
    return rp
