"""Targeted text replacement tool for surgical edits to files."""

from pathlib import Path

from sandbox_vm.tools.utils import _err, _ok


def patch_text(file_path: str, old_text: str, new_text: str) -> dict:
    """
    Apply a targeted text replacement to a file.

    Replaces the first occurrence of old_text with new_text in the specified file.
    This is useful for making surgical edits to LaTeX files without rewriting the
    entire file, avoiding issues with LLM-introduced formatting changes.

    Args:
        file_path: Path to the file to modify (relative to /workspace or absolute).
        old_text: The exact text to find and replace (first occurrence only).
        new_text: The replacement text.

    Returns:
        {
            "ok": True,
            "message": str  # e.g. "OK: replaced 1 occurrence in path"
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = patch_text("outputs/paper/sections/method.tex",
        ...     "old paragraph text", "new improved text")
        >>> print(result["message"])
        "OK: replaced 1 occurrence in outputs/paper/sections/method.tex"
    """
    if not file_path or not isinstance(file_path, str):
        return _err("INVALID_INPUT", message="file_path must be a non-empty string")
    if old_text is None or not isinstance(old_text, str):
        return _err("INVALID_INPUT", message="old_text must be a string")
    if new_text is None or not isinstance(new_text, str):
        return _err("INVALID_INPUT", message="new_text must be a string")

    # Resolve path
    p = Path(file_path)
    if not p.is_absolute():
        p = Path("/workspace") / file_path.lstrip("/")

    if not p.exists():
        return _err("FILE_NOT_FOUND", message=f"File not found: {file_path}")

    try:
        content = p.read_text(encoding="utf-8")

        if old_text not in content:
            # Show a snippet of the old_text for debugging
            snippet = repr(old_text[:200])
            return _err(
                "NOT_FOUND",
                message=f"Old text not found in {file_path}. First 200 chars: {snippet}",
            )

        content = content.replace(old_text, new_text, 1)
        p.write_text(content, encoding="utf-8")

        return _ok(message=f"OK: replaced 1 occurrence in {file_path}")

    except Exception as e:
        return _err("PATCH_ERROR", message=f"Failed to patch file: {e}")
