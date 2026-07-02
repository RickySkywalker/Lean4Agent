"""
SWE-Bench code exploration tools optimized for LLM agents.

These tools enable efficient code investigation and debugging in large codebases:
- find_file(): Locate files by name/path pattern (wildcards or regex)
- search_file(): Search within a specific file with optional context
- search_dir(): Search across entire directories (auto-skips build/cache)
- view_file(): Display file contents with pagination and highlighting

Design philosophy: Intuitive for LLMs, minimal parameters, smart defaults.
All searches skip build artifacts (.git, __pycache__, dist, etc.) automatically.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from fastmcp import Context

from sandbox_vm.tools.session_management import MANAGER
from sandbox_vm.tools.utils import _err, _ok, _sid

# Maximum number of results to return for search/find operations
MAX_RESULTS = 10

# Number of context lines to show before/after edits
CONTEXT_LINES = 3

# Skip patterns for search_dir
SKIP_DIRS = {
    ".git",
    ".egg-info",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    ".env",
}
SKIP_EXTENSIONS = {
    ".pyc",
    ".so",
    ".exe",
    ".dll",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".o",
    ".a",
    ".lib",
}


async def find_file(
    ctx: Context,
    directory: str,
    query: str,
    regex: bool = False,
) -> dict:
    """
    Find files by name/path pattern (recursive). Supports wildcards (*.py, test_*) or regex.

    Args:
        directory: Real path to search (relative or absolute within session, e.g., "tmp/django" or "/code")
        query: Pattern to match - simple string, wildcard (*.py, */models/*.py), or regex
        regex: If True, treat query as regex pattern (default: False)

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """
    rt = MANAGER.get(_sid(ctx))

    # Accept real paths (relative or absolute within session)
    dir_path = Path(directory)
    if not dir_path.is_absolute():
        dir_path = rt.root / dir_path
    dir_path = dir_path.resolve()

    if not dir_path.exists():
        return _err(f"Directory does not exist: {directory}")

    if not dir_path.is_dir():
        return _err(f"Path is not a directory: {directory}")

    try:
        matches = []
        query_lower = query.lower()

        # Compile regex if requested
        regex_pattern = None
        if regex:
            try:
                regex_pattern = re.compile(query, re.IGNORECASE)
            except re.error as e:
                return _err(f"Invalid regex pattern: {str(e)}")

        # Check if query contains wildcard characters
        has_wildcard = any(char in query for char in ["*", "?", "["])

        # Recursively search for matching files
        for file_path in dir_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(dir_path)
                rel_path_str = str(rel_path).lower()
                filename = file_path.name.lower()

                match = False
                if regex_pattern:
                    # Regex matching on relative path
                    match = regex_pattern.search(rel_path_str) is not None
                elif has_wildcard:
                    # Wildcard matching on relative path
                    match = fnmatch.fnmatch(rel_path_str, query_lower)
                else:
                    # Substring matching on both filename and full path
                    match = query_lower in rel_path_str or query_lower in filename

                if match:
                    matches.append(str(rel_path))
                    if len(matches) >= MAX_RESULTS:
                        break

        if not matches:
            result_str = f"No files found matching '{query}' in {directory}"
        else:
            result_str = (
                f"Found {len(matches)} file(s) matching '{query}':\n"
                + "\n".join(matches)
            )
            if len(matches) >= MAX_RESULTS:
                result_str += f"\n\n(Showing first {MAX_RESULTS} results)"

        rt.touch()
        return _ok(result=result_str)

    except Exception as e:
        return _err(f"Error searching directory: {str(e)}")


async def search_file(
    ctx: Context,
    file_path: str,
    query: str,
    regex: bool = False,
    context_lines: int = 0,
) -> dict:
    """
    Search for pattern in a single file. Returns matching lines with optional context.

    Args:
        file_path: Real path to file (relative or absolute within session, e.g., "tmp/django/models.py")
        query: Text or pattern to find
        regex: If True, treat query as regex pattern (default: False)
        context_lines: Show N lines before/after each match (default: 0)

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """
    rt = MANAGER.get(_sid(ctx))

    # Accept real paths (relative or absolute within session)
    f = Path(file_path)
    if not f.is_absolute():
        f = rt.root / f
    f = f.resolve()

    if not f.exists():
        return _err(f"File does not exist: {file_path}")

    if not f.is_file():
        return _err(f"Path is not a file: {file_path}")

    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        matches = []
        match_line_nums = set()

        # Compile regex if requested
        regex_pattern = None
        if regex:
            try:
                regex_pattern = re.compile(query)
            except re.error as e:
                return _err(f"Invalid regex pattern: {str(e)}")

        for line_num, line in enumerate(lines, start=1):
            match = False
            if regex_pattern:
                match = regex_pattern.search(line) is not None
            else:
                match = query in line

            if match:
                match_line_nums.add(line_num)
                # Format: filename (line N): content
                matches.append(f"{f.name} (line {line_num}): {line.strip()}")

                if len(matches) >= MAX_RESULTS:
                    break

        # Add context lines if requested
        if context_lines > 0 and match_line_nums:
            result_parts = [f"Search results for '{query}' in {file_path}:\n"]
            for match_line in sorted(match_line_nums)[:MAX_RESULTS]:
                result_parts.append(f"--- Match at line {match_line} ---")

                # Add context before
                start = max(1, match_line - context_lines)
                if start < match_line:
                    result_parts.append("Context before:")
                    for ctx_line_num in range(start, match_line):
                        result_parts.append(
                            f"{ctx_line_num:6d}: {lines[ctx_line_num - 1]}"
                        )

                # Add the match
                result_parts.append(
                    f"{match_line:6d}> {lines[match_line - 1]} <-- MATCH"
                )

                # Add context after
                end = min(len(lines), match_line + context_lines)
                if end > match_line:
                    result_parts.append("Context after:")
                    for ctx_line_num in range(match_line + 1, end + 1):
                        result_parts.append(
                            f"{ctx_line_num:6d}: {lines[ctx_line_num - 1]}"
                        )
                result_parts.append("")

            result_str = "\n".join(result_parts)
        else:
            if not matches:
                result_str = f"No matches found for '{query}' in {file_path}"
            else:
                result_str = (
                    f"Found {len(matches)} match(es) for '{query}':\n"
                    + "\n".join(matches)
                )
                if len(matches) >= MAX_RESULTS:
                    result_str += f"\n\n(Showing first {MAX_RESULTS} results)"

        rt.touch()
        return _ok(result=result_str)

    except Exception as e:
        return _err(f"Error reading file: {str(e)}")


async def search_dir(
    ctx: Context,
    directory: str,
    query: str,
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 100,
    file_pattern: str = "",
) -> dict:
    """
    Search for pattern across all files in a directory. Auto-skips build/cache/binaries.

    Args:
        directory: Real path to search (relative or absolute within session, e.g., "tmp/django")
        query: Text or regex pattern to find
        case_sensitive: Case-sensitive search (default: False)
        regex: If True, treat query as regex pattern (default: False)
        max_results: Maximum results to return (default: 100)
        file_pattern: Optional filter (e.g., "*.py" for Python files only)

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """
    rt = MANAGER.get(_sid(ctx))

    # Accept real paths (relative or absolute within session)
    dir_path = Path(directory)
    if not dir_path.is_absolute():
        dir_path = rt.root / dir_path
    dir_path = dir_path.resolve()

    if not dir_path.exists():
        return _err(f"Directory does not exist: {directory}")

    if not dir_path.is_dir():
        return _err(f"Path is not a directory: {directory}")

    try:
        matches = []
        search_query = query if case_sensitive else query.lower()

        # Compile regex if requested
        regex_pattern = None
        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex_pattern = re.compile(query, flags)
            except re.error as e:
                return _err(f"Invalid regex pattern: {str(e)}")

        # Compile file pattern if provided
        file_filter = None
        if file_pattern:
            file_filter = file_pattern.lower()

        # Recursively search all files
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip directories in SKIP_DIRS
            if any(part in SKIP_DIRS for part in file_path.parts):
                continue

            # Skip binary files and non-text extensions
            if file_path.suffix in SKIP_EXTENSIONS:
                continue

            # Apply file pattern filter if provided
            if file_filter:
                if not fnmatch.fnmatch(file_path.name.lower(), file_filter):
                    continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()

                for line_num, line in enumerate(lines, start=1):
                    match = False
                    if regex_pattern:
                        match = regex_pattern.search(line) is not None
                    else:
                        check_line = line if case_sensitive else line.lower()
                        match = search_query in check_line

                    if match:
                        # Get relative path from directory
                        rel_path = file_path.relative_to(dir_path)
                        # Format: relative/path/file.py (line N): content
                        matches.append(f"{rel_path} (line {line_num}): {line.strip()}")

                        if len(matches) >= max_results:
                            break

            except Exception:
                # Skip files that can't be read as text
                continue

            if len(matches) >= max_results:
                break

        if not matches:
            result_str = f"No matches found for '{query}' in {directory}"
        else:
            result_str = f"Found {len(matches)} match(es) for '{query}':\n" + "\n".join(
                matches
            )
            if len(matches) >= max_results:
                result_str += f"\n\n(Showing first {max_results} results)"

        rt.touch()
        return _ok(result=result_str)

    except Exception as e:
        return _err(f"Error searching directory: {str(e)}")


async def view_file(
    ctx: Context,
    file_path: str,
    start_line: int = 1,
    num_lines: int = 50,
    highlight_query: str = "",
) -> dict:
    """
    Display file contents with line numbers and optional highlighting.

    Args:
        file_path: Real path to file (relative or absolute within session, e.g., "tmp/django/models.py")
        start_line: First line to display (1-indexed, default: 1)
        num_lines: Number of lines to display (default: 50)
        highlight_query: Optional text to mark with "*" marker while viewing

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """
    rt = MANAGER.get(_sid(ctx))

    # Accept real paths (relative or absolute within session)
    f = Path(file_path)
    if not f.is_absolute():
        f = rt.root / f
    f = f.resolve()

    if not f.exists():
        return _err(f"File does not exist: {file_path}")

    if not f.is_file():
        return _err(f"Path is not a file: {file_path}")

    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        total_lines = len(lines)

        # Validate start_line
        if start_line < 1:
            start_line = 1

        # Calculate range
        end_line = min(start_line + num_lines - 1, total_lines)

        if start_line > total_lines:
            return _err(f"start_line {start_line} exceeds total lines {total_lines}")

        # Build result with line numbers
        result_lines = [f"File: {file_path}"]
        result_lines.append(f"Lines: {start_line}-{end_line} of {total_lines}")
        result_lines.append("-" * 80)

        for line_num in range(start_line - 1, end_line):
            line = lines[line_num]
            # Highlight query if provided
            if highlight_query and highlight_query.lower() in line.lower():
                # Mark the line as containing a match
                result_lines.append(f"{line_num + 1:6d}* {line}")
            else:
                result_lines.append(f"{line_num + 1:6d}  {line}")

        result_lines.append("-" * 80)

        if end_line < total_lines:
            result_lines.append(
                f"(More lines available. Use start_line={end_line + 1} to see more)"
            )

        result_str = "\n".join(result_lines)

        rt.touch()
        return _ok(result=result_str)

    except Exception as e:
        return _err(f"Error reading file: {str(e)}")


async def edit(
    ctx: Context,
    file_path: str,
    start_line: int,
    end_line: int,
    new_content: str,
) -> dict:
    """
    Edit a file by replacing lines with new content, preserving indentation.

    Args:
        file_path: Real path to the file to edit (relative or absolute within session)
        start_line: Starting line number to replace (1-indexed, inclusive)
        end_line: Ending line number to replace (1-indexed, inclusive)
        new_content: New content to insert (multi-line string)

    Returns:
        dict: {"result": str} on success, or {"error": str} on failure
    """
    rt = MANAGER.get(_sid(ctx))

    # Accept real paths (relative or absolute within session)
    f = Path(file_path)
    if not f.is_absolute():
        f = rt.root / f
    f = f.resolve()

    if not f.exists():
        return _err(f"File does not exist: {file_path}")

    if not f.is_file():
        return _err(f"Path is not a file: {file_path}")

    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        total_lines = len(lines)

        # Validate line numbers
        if start_line < 1 or end_line < 1:
            return _err("Line numbers must be >= 1")

        if start_line > total_lines:
            return _err(f"start_line {start_line} exceeds total lines {total_lines}")

        if end_line > total_lines:
            return _err(f"end_line {end_line} exceeds total lines {total_lines}")

        if start_line > end_line:
            return _err(
                f"start_line {start_line} cannot be greater than end_line {end_line}"
            )

        # Detect indentation from the first line being replaced
        def get_indentation(line: str) -> str:
            """Extract leading whitespace from a line."""
            return line[: len(line) - len(line.lstrip())]

        # Get base indentation from the first line being replaced (if it's not empty)
        base_indent = ""
        if start_line <= total_lines and lines[start_line - 1].strip():
            base_indent = get_indentation(lines[start_line - 1])

        # Process new content lines
        new_lines = new_content.splitlines()

        # Auto-indent: if new_content doesn't have indentation but should, apply base_indent
        processed_new_lines = []
        for new_line in new_lines:
            if new_line.strip():  # Non-empty line
                # If line has no indentation and we have a base indent, apply it
                if new_line and new_line[0] not in (" ", "\t") and base_indent:
                    processed_new_lines.append(base_indent + new_line)
                else:
                    processed_new_lines.append(new_line)
            else:
                # Empty line
                processed_new_lines.append(new_line)

        # Build the new file content
        new_file_lines = (
            lines[: start_line - 1] + processed_new_lines + lines[end_line:]
        )

        # Write back to file
        new_content_str = "\n".join(new_file_lines)
        f.write_text(new_content_str, encoding="utf-8")

        # Build informative result message
        lines_removed = end_line - start_line + 1
        lines_added = len(processed_new_lines)

        result_parts = [
            f"File: {file_path}",
            f"Edited lines {start_line}-{end_line} ({lines_removed} lines removed, {lines_added} lines added)",
            "-" * 80,
        ]

        # Show context lines before the edit (from original file)
        context_start = max(1, start_line - CONTEXT_LINES)
        if context_start < start_line:
            result_parts.append("Context before:")
            for line_num in range(context_start, start_line):
                result_parts.append(f"{line_num:6d}  {lines[line_num - 1]}")
            result_parts.append("")

        # Show the new content with line numbers
        result_parts.append("New content:")
        for idx, line in enumerate(processed_new_lines, start=start_line):
            result_parts.append(f"{idx:6d}  {line}")

        # Show context lines after the edit (from new file)
        # Calculate where the context should start in the new file
        new_end_line = start_line + lines_added - 1
        context_end = min(len(new_file_lines), new_end_line + CONTEXT_LINES)
        if context_end > new_end_line:
            result_parts.append("")
            result_parts.append("Context after:")
            for line_num in range(new_end_line + 1, context_end + 1):
                if line_num - 1 < len(new_file_lines):
                    result_parts.append(
                        f"{line_num:6d}  {new_file_lines[line_num - 1]}"
                    )

        result_parts.append("-" * 80)
        result_str = "\n".join(result_parts)

        rt.touch()
        return _ok(result=result_str)

    except Exception as e:
        return _err(f"Error editing file: {str(e)}")
