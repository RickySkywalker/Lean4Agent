"""Filesystem tools for sandboxed workspace operations."""

from __future__ import annotations

import base64
import shutil

from sandbox_vm.mcp.utils import filename_to_path


def fs_read(path: str, max_bytes: int | None = None, as_base64: bool = False) -> dict:
    """
    Read a file's contents.

    Args:
        path: File path (relative to workspace or absolute).
        max_bytes: Maximum bytes to read. Omit to read entire file.
        as_base64: Return content as base64 instead of text.

    Returns:
        path: Absolute path of the file.
        text: File contents as UTF-8 string (if decodable and as_base64=False).
        data_base64: Base64-encoded contents (if binary or as_base64=True).
    """
    p = filename_to_path(path)
    data = p.read_bytes()
    if max_bytes is not None:
        data = data[:max_bytes]

    if as_base64:
        return {
            "path": str(p),
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    try:
        return {"path": str(p), "text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {
            "path": str(p),
            "data_base64": base64.b64encode(data).decode("ascii"),
        }


def fs_write(path: str, content: str, mode: str = "text", append: bool = False) -> dict:
    """
    Write content to a file. Creates parent directories if needed.

    Args:
        path: Destination file path (relative to workspace or absolute).
        content: Data to write (text string or base64-encoded string).
        mode: "text" for UTF-8 text, "base64" to decode and write binary.
        append: If True, append to file instead of overwriting.

    Returns:
        path: Absolute path of the written file.
        size: File size in bytes after writing.
    """
    p = filename_to_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if mode == "text":
        with p.open("a" if append else "w", encoding="utf-8") as f:
            f.write(content)
    elif mode == "base64":
        with p.open("ab" if append else "wb") as f:
            f.write(base64.b64decode(content))
    else:
        raise ValueError("mode must be 'text' or 'base64'")

    return {"path": str(p), "size": p.stat().st_size}


def fs_list(path: str) -> dict:
    """
    List contents of a directory.

    Args:
        path: Directory path (relative to workspace or absolute).

    Returns:
        path: Absolute path of the directory.
        entries: List of {name, is_dir, size} for each entry. size is None for directories.
        error: Present if directory not found.
    """
    p = filename_to_path(path)
    if not p.exists():
        return {"error": f"not found: {p}"}

    entries = [
        {
            "name": e.name,
            "is_dir": e.is_dir(),
            "size": e.stat().st_size if e.is_file() else None,
        }
        for e in sorted(p.iterdir(), key=lambda x: x.name)
    ]
    return {"path": str(p), "entries": entries}


def fs_mkdir(path: str, parents: bool = True) -> dict:
    """
    Create a directory.

    Args:
        path: Directory path to create (relative to workspace or absolute).
        parents: If True, create parent directories as needed.

    Returns:
        path: Absolute path of the created directory.
    """
    p = filename_to_path(path)
    p.mkdir(parents=parents, exist_ok=True)
    return {"path": str(p)}


def fs_remove(path: str, recursive: bool = False) -> dict:
    """
    Delete a file or directory.

    Args:
        path: Path to delete (relative to workspace or absolute).
        recursive: If True, delete directory and all its contents.

    Returns:
        path: Absolute path that was removed.
    """
    p = filename_to_path(path)
    if recursive and p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)
    return {"path": str(p)}


def fs_move(src: str, dst: str, overwrite: bool = False) -> dict:
    """
    Move or rename a file or directory.

    Args:
        src: Source path (relative to workspace or absolute).
        dst: Destination path (relative to workspace or absolute).
        overwrite: If True, replace existing destination.

    Returns:
        src: Absolute source path.
        dst: Absolute destination path.
    """
    s = filename_to_path(src)
    d = filename_to_path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)

    if d.exists():
        if not overwrite:
            raise ValueError(f"destination exists: {d}")
        if d.is_dir():
            shutil.rmtree(d)
        else:
            d.unlink()

    shutil.move(str(s), str(d))
    return {"src": str(s), "dst": str(d)}
