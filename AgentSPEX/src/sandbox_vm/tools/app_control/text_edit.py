"""String-based text editing tool for file content manipulation.

Provides a string_replace tool that finds and replaces exact text in files,
similar to Claude Code's Edit tool. Designed for writing/editing workflows
where line-number-based editing is impractical.
"""

from __future__ import annotations

from sandbox_vm.mcp.utils import filename_to_path


def string_replace(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict:
    """
    Replace exact text in a file. The old_string must match exactly (including
    whitespace and indentation). Use for targeted edits to documents.

    Args:
        path: File path (relative to workspace or absolute).
        old_string: The exact text to find and replace. Must be unique in the
            file unless replace_all is True.
        new_string: The replacement text.
        replace_all: If True, replace all occurrences. If False (default),
            the old_string must appear exactly once in the file.

    Returns:
        path: Absolute path of the edited file.
        replacements: Number of replacements made.
        error: Present if the operation failed.
    """
    p = filename_to_path(path)

    if not p.exists():
        return {"error": f"File not found: {path}"}

    if not p.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"Cannot read file: {e}"}

    if old_string == new_string:
        return {"error": "old_string and new_string are identical"}

    count = content.count(old_string)

    if count == 0:
        # Provide helpful context for debugging
        # Show a short snippet of the file to help the user locate the text
        preview = content[:500] + ("..." if len(content) > 500 else "")
        return {
            "error": f"old_string not found in {path}. "
            f"File has {len(content)} chars, {content.count(chr(10))+1} lines. "
            f"Preview:\n{preview}",
        }

    if not replace_all and count > 1:
        return {
            "error": f"old_string appears {count} times in {path}. "
            "Provide more surrounding context to make it unique, "
            "or set replace_all=True to replace all occurrences.",
        }

    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
    p.write_text(new_content, encoding="utf-8")

    return {
        "path": str(p),
        "replacements": count if replace_all else 1,
    }
