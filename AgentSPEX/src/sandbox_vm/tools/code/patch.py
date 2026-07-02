import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

from sandbox_vm.mcp.utils import filename_to_path

# --- Patch Format Documentation ---
"""
Pseudo-Patch Format:
*** Begin Patch
*** [Operation] File: [filepath]
@@ [text matching a line near the change]
  [context line (unchanged, starts with space)]
- [line to remove (starts with -)]
+ [line to add (starts with +)]
  [another context line]
*** End Patch

Supported Operations:
- Update: Modify existing file content
- Add: Create new file
- Delete: Remove file

Notes:
- Context lines start with a space
- Lines to remove start with '-'
- Lines to add start with '+'
- The @@ line is optional and provides a hint for searching
"""


# --- Helper Classes ---


class PatchHunk:
    """Represents a single change block in a patch."""

    def __init__(self):
        self.operation: str = "Update"  # Update, Add, Delete
        self.filepath: str = ""
        self.search_hint: str = ""  # Text from @@ line
        self.context_before: List[str] = []
        self.old_lines: List[str] = []
        self.new_lines: List[str] = []
        self.context_after: List[str] = []

    def __repr__(self):
        return f"PatchHunk(op={self.operation}, file={self.filepath}, old={len(self.old_lines)}, new={len(self.new_lines)})"


class MatchResult:
    """Result of a fuzzy match search."""

    def __init__(
        self,
        found: bool = False,
        score: float = 0.0,
        start_line: int = -1,
        end_line: int = -1,
    ):
        self.found = found
        self.score = score
        self.start_line = start_line
        self.end_line = end_line

    def __repr__(self):
        return f"MatchResult(found={self.found}, score={self.score:.2f}, lines={self.start_line}-{self.end_line})"


# --- Patch Parsing ---


def _parse_patch_file(patch_content: str) -> List[PatchHunk]:
    """
    Parse a pseudo-patch file into structured hunks.

    Args:
        patch_content: The complete patch file content

    Returns:
        List of PatchHunk objects

    Raises:
        ValueError: If patch format is invalid
    """
    lines = patch_content.split("\n")
    hunks = []
    current_hunk = None
    in_patch = False

    i = 0
    while i < len(lines):
        line = lines[i]

        # Start of a patch block
        if line.strip() == "*** Begin Patch":
            in_patch = True
            current_hunk = PatchHunk()
            i += 1
            continue

        # End of a patch block
        if line.strip() == "*** End Patch":
            if current_hunk:
                hunks.append(current_hunk)
                current_hunk = None
            in_patch = False
            i += 1
            continue

        if not in_patch:
            i += 1
            continue

        # Operation and file line: *** [Operation] File: [filepath]
        if line.startswith("***") and "File:" in line:
            match = re.match(r"\*\*\*\s*(\w+)\s+File:\s*(.+)$", line.strip())
            if match:
                current_hunk.operation = match.group(1).strip()
                current_hunk.filepath = match.group(2).strip()
            i += 1
            continue

        # Search hint line: @@ some text @@
        if line.strip().startswith("@@"):
            current_hunk.search_hint = line.strip().strip("@").strip()
            i += 1
            continue

        # Parse hunk content (context, old, new lines)
        if current_hunk:
            if line.startswith(" "):
                # Context line (starts with space) - remove only the first space marker
                context_line = line[1:]
                # Determine if it's before or after the changes
                if not current_hunk.old_lines and not current_hunk.new_lines:
                    current_hunk.context_before.append(context_line)
                else:
                    current_hunk.context_after.append(context_line)
            elif line.startswith("-"):
                # Line to remove - remove only the '-' marker, preserve indentation
                current_hunk.old_lines.append(line[1:])
            elif line.startswith("+"):
                # Line to add - remove only the '+' marker, preserve indentation
                current_hunk.new_lines.append(line[1:])

        i += 1

    return hunks


# --- Fuzzy Matching ---


def _normalize_line(line: str) -> str:
    """Normalize a line for comparison (strip whitespace, lowercase)."""
    return line.strip().lower()


def _get_indentation(line: str) -> str:
    """Extract the leading whitespace from a line."""
    return line[: len(line) - len(line.lstrip())]


def _strip_indentation(line: str) -> str:
    """Remove leading whitespace from a line."""
    return line.lstrip()


def _detect_indent_style(lines: List[str]) -> tuple:
    """
    Detect indentation style (tabs vs spaces) and unit size from file lines.

    Args:
        lines: Lines from the matched file region

    Returns:
        Tuple of (style, unit_size) where:
        - style: 'tabs' or 'spaces'
        - unit_size: Number of spaces per indent level (or 1 for tabs)
    """
    indents = []

    for line in lines:
        if line and line.strip() and line[0] in " \t":
            indent = _get_indentation(line)
            if indent:
                indents.append(indent)

    if not indents:
        return ("spaces", 4)  # Default fallback

    # Check if using tabs
    if any("\t" in indent for indent in indents):
        return ("tabs", 1)

    # Detect space unit size by finding common indent differences
    indent_sizes = sorted(set(len(indent) for indent in indents))

    if len(indent_sizes) >= 2:
        # Calculate differences between consecutive indent levels
        differences = [
            indent_sizes[i + 1] - indent_sizes[i] for i in range(len(indent_sizes) - 1)
        ]

        # Use the most common difference as the unit
        if differences:
            from collections import Counter

            unit = Counter(differences).most_common(1)[0][0]
            return ("spaces", unit if unit > 0 else 4)

    # Fallback: assume 4 spaces
    return ("spaces", 4)


def _get_min_indentation(lines: List[str]) -> str:
    """
    Get the minimum indentation from a list of lines (the baseline).

    Args:
        lines: List of code lines

    Returns:
        The minimum indentation string found, or empty string if none
    """
    indents = []
    for line in lines:
        if line.strip():  # Only consider non-empty lines
            indents.append(_get_indentation(line))

    if not indents:
        return ""

    return min(indents, key=len)


def _normalize_indent_to_style(
    indent_str: str, target_style: str, target_unit: int
) -> str:
    """
    Normalize an indentation string to match target style.

    Args:
        indent_str: The indentation string to normalize
        target_style: 'tabs' or 'spaces'
        target_unit: Number of spaces per indent level

    Returns:
        Normalized indentation string in target style
    """
    if not indent_str:
        return ""

    # Determine how many indent levels this represents
    if "\t" in indent_str:
        # Source uses tabs
        levels = indent_str.count("\t")
    else:
        # Source uses spaces - try to infer levels
        # Heuristic: assume 4 spaces = 1 level, or use target_unit
        space_count = len(indent_str)
        if target_style == "spaces":
            levels = space_count // target_unit
        else:
            # Converting spaces to tabs, assume 4 spaces = 1 tab
            levels = space_count // 4

    # Generate target indentation
    if target_style == "tabs":
        return "\t" * levels
    else:
        return " " * (levels * target_unit)


def _calculate_relative_indent(
    line: str, base_indent: str, target_style: str, target_unit: int
) -> str:
    """
    Calculate relative indentation beyond a base level and normalize to target style.

    Args:
        line: The line to measure
        base_indent: The baseline indentation (minimum in the block)
        target_style: Target indentation style ('tabs' or 'spaces')
        target_unit: Target indentation unit size

    Returns:
        The relative indentation normalized to target style
    """
    if not line.strip():
        return ""

    line_indent = _get_indentation(line)
    base_len = len(base_indent)

    # If line is less indented than base, it might be dedented (like 'else', 'except')
    # In this case, return empty string (will only use file's base indent)
    if len(line_indent) < base_len:
        return ""

    # Extract the relative indentation (excess beyond base)
    relative_indent_str = line_indent[base_len:]

    # Normalize to target style
    return _normalize_indent_to_style(relative_indent_str, target_style, target_unit)


def _calculate_similarity(text1: List[str], text2: List[str]) -> float:
    """
    Calculate similarity between two text blocks with line-by-line fuzzy matching.

    This function compares blocks line-by-line and averages the similarity scores,
    making it robust to minor variations in each line.

    Args:
        text1: First text block (list of lines)
        text2: Second text block (list of lines)

    Returns:
        Similarity ratio between 0.0 and 1.0
    """
    if len(text1) != len(text2):
        # If different number of lines, fall back to overall similarity
        norm1 = [_normalize_line(line) for line in text1]
        norm2 = [_normalize_line(line) for line in text2]
        matcher = SequenceMatcher(None, norm1, norm2)
        return matcher.ratio()

    # Line-by-line fuzzy matching
    total_score = 0.0
    for line1, line2 in zip(text1, text2):
        norm1 = _normalize_line(line1)
        norm2 = _normalize_line(line2)
        matcher = SequenceMatcher(None, norm1, norm2)
        total_score += matcher.ratio()

    # Return average similarity across all lines
    return total_score / len(text1) if text1 else 0.0


def _find_best_match(
    file_lines: List[str], search_pattern: List[str], threshold: float = 0.75
) -> MatchResult:
    """
    Find the best matching location for a search pattern in file lines.

    Args:
        file_lines: The file content as a list of lines
        search_pattern: The pattern to search for (context + old lines)
        threshold: Minimum similarity score (0.0 to 1.0)

    Returns:
        MatchResult with location and score
    """
    if not search_pattern or not file_lines:
        return MatchResult(found=False)

    pattern_len = len(search_pattern)
    best_score = 0.0
    best_start = -1

    # Sliding window search
    for i in range(len(file_lines) - pattern_len + 1):
        window = file_lines[i : i + pattern_len]
        score = _calculate_similarity(search_pattern, window)

        if score > best_score:
            best_score = score
            best_start = i

    # Check if we found a good enough match
    if best_score >= threshold and best_start >= 0:
        return MatchResult(
            found=True,
            score=best_score,
            start_line=best_start,
            end_line=best_start + pattern_len,
        )

    return MatchResult(found=False, score=best_score)


def _apply_hunk_to_lines(
    file_lines: List[str], hunk: PatchHunk, threshold: float = 0.75
) -> Tuple[List[str], MatchResult]:
    """
    Apply a single hunk to file lines with intelligent indentation handling.

    This function automatically detects indentation style from the matched file
    region and preserves RELATIVE indentation structure from the patch.

    Key features:
    - Detects tabs vs spaces and indentation unit
    - Preserves nested block structure (if/else, try/except, etc.)
    - Uses base + relative indentation model

    Args:
        file_lines: The original file lines
        hunk: The hunk to apply
        threshold: Minimum similarity threshold for matching

    Returns:
        Tuple of (modified_lines, match_result)

    Raises:
        ValueError: If no suitable match is found
    """
    # Build search pattern (context_before + old_lines)
    search_pattern = hunk.context_before + hunk.old_lines

    if not search_pattern:
        raise ValueError("Hunk has no searchable content (context_before + old_lines)")

    # Find best match location
    match = _find_best_match(file_lines, search_pattern, threshold)

    if not match.found:
        raise ValueError(
            f"Could not find suitable match for hunk (best score: {match.score:.2f}, threshold: {threshold})"
        )

    # Get matched region from file
    matched_region = file_lines[match.start_line : match.end_line]

    # Detect indentation style and unit from matched file region
    indent_style, indent_unit = _detect_indent_style(matched_region)

    # Get base indentation from the matched file location (minimum indent in region)
    file_base_indent = _get_min_indentation(matched_region)

    # Get base indentation from the patch (minimum indent in patch lines)
    patch_lines = (
        hunk.context_before + hunk.old_lines + hunk.new_lines + hunk.context_after
    )
    patch_base_indent = _get_min_indentation(patch_lines)

    # Build replacement with proper relative indentation
    replacement = []

    def apply_line_with_indent(line: str) -> str:
        """Apply proper indentation to a line based on its relative indent in patch."""
        if not line.strip():
            # Empty line - preserve as-is
            return line

        # Calculate relative indentation beyond patch base
        relative_indent = _calculate_relative_indent(
            line=line,
            base_indent=patch_base_indent,
            target_style=indent_style,
            target_unit=indent_unit,
        )

        # Final indentation = file base + relative indent
        final_indent = file_base_indent + relative_indent
        return final_indent + _strip_indentation(line)

    # Apply indentation to context_before lines
    for line in hunk.context_before:
        replacement.append(apply_line_with_indent(line))

    # Apply indentation to new_lines
    for line in hunk.new_lines:
        replacement.append(apply_line_with_indent(line))

    # Apply indentation to context_after lines
    for line in hunk.context_after:
        replacement.append(apply_line_with_indent(line))

    # Calculate how many lines to replace
    original_hunk_size = (
        len(hunk.context_before) + len(hunk.old_lines) + len(hunk.context_after)
    )

    # Apply the replacement
    new_lines = (
        file_lines[: match.start_line]
        + replacement
        + file_lines[match.start_line + original_hunk_size :]
    )

    return new_lines, match


# --- Main Function ---
async def apply_patch(
    patch_path: str, threshold: float = 0.75, dry_run: bool = False, backup: bool = True
) -> dict:
    """
    Apply a pseudo-patch file to target files with fuzzy matching.

    This function parses a structured patch file and applies changes to the
    specified files. It uses fuzzy matching to find the best location for
    each change, making it robust to minor variations in the target files.

    Args:
        patch_path: Path to the patch file
        threshold: Minimum similarity score for fuzzy matching (0.0 to 1.0)
                Default: 0.75 (75% similarity required)
        dry_run: If True, parse and match but don't write changes
        backup: If True, create .bak backup before modifying files

    Returns:
        dict: Result containing:
            - patches_applied (int): Number of hunks successfully applied
            - files_modified (list): List of modified file paths
            - details (list): Detailed info for each hunk
            - error (str): Error message if failed
    """
    result = {
        "patches_applied": 0,
        "files_modified": [],
        "details": [],
    }

    try:
        # Read and parse patch file
        patch_file = filename_to_path(patch_path)
        if not patch_file.exists():
            result["error"] = f"Patch file not found: {patch_path}"
            return result

        patch_content = patch_file.read_text(encoding="utf-8")

        # Parse hunks
        hunks = _parse_patch_file(patch_content)

        if not hunks:
            result["error"] = "No valid patch hunks found in file"
            return result

        result["details"].append(f"Parsed {len(hunks)} hunk(s) from patch file")

        # Group hunks by file
        files_to_modify: Dict[str, List[PatchHunk]] = {}
        for hunk in hunks:
            if hunk.filepath not in files_to_modify:
                files_to_modify[hunk.filepath] = []
            files_to_modify[hunk.filepath].append(hunk)

        # Process each file
        for filepath, file_hunks in files_to_modify.items():
            try:
                filepath = str(Path(patch_path).parent / filepath)
                target_file = filename_to_path(filepath)

                # Handle different operations
                first_hunk = file_hunks[0]

                if first_hunk.operation == "Delete":
                    if not dry_run and target_file.exists():
                        target_file.unlink()
                        result["files_modified"].append(str(target_file))
                        result["patches_applied"] += 1
                        result["details"].append(f"Deleted: {filepath}")
                    continue

                elif first_hunk.operation == "Add":
                    # Create new file with content from new_lines
                    if not dry_run:
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        content_lines = []
                        for hunk in file_hunks:
                            content_lines.extend(hunk.new_lines)
                        target_file.write_text(
                            "\n".join(content_lines), encoding="utf-8"
                        )
                        result["files_modified"].append(str(target_file))
                        result["patches_applied"] += len(file_hunks)
                        result["details"].append(
                            f"Created: {filepath} with {len(content_lines)} lines"
                        )
                    continue

                # Update operation - apply hunks
                if not target_file.exists():
                    raise FileNotFoundError(f"Target file not found: {filepath}")

                # Read file
                file_content = target_file.read_text(encoding="utf-8")
                file_lines = file_content.split("\n")

                # Apply each hunk sequentially
                modified_lines = file_lines
                for idx, hunk in enumerate(file_hunks):
                    try:
                        modified_lines, match = _apply_hunk_to_lines(
                            modified_lines, hunk, threshold
                        )
                        result["patches_applied"] += 1
                        result["details"].append(
                            f"Applied hunk {idx+1}/{len(file_hunks)} to {filepath} "
                            f"(match score: {match.score:.2f}, lines: {match.start_line}-{match.end_line})"
                        )
                    except ValueError as e:
                        result["details"].append(
                            f"Failed to apply hunk {idx+1}/{len(file_hunks)}: {e}"
                        )
                        raise

                # Write back modified content
                if not dry_run:
                    # Create backup if requested
                    if backup and target_file.exists():
                        backup_path = target_file.with_suffix(
                            target_file.suffix + ".bak"
                        )
                        backup_path.write_text(file_content, encoding="utf-8")
                        result["details"].append(f"Created backup: {backup_path}")

                    # Write modified file
                    target_file.write_text("\n".join(modified_lines), encoding="utf-8")
                    result["files_modified"].append(str(target_file))
                    result["details"].append(f"Modified: {filepath}")

            except Exception as e:
                error_msg = f"Error processing {filepath}: {str(e)}"
                result["details"].append(error_msg)
                result["error"] = error_msg
                return result

        # Success
        result["files_modified"] = list(
            set(result["files_modified"])
        )  # Remove duplicates

        if dry_run:
            result["details"].append("DRY RUN - No files were actually modified")

    except Exception as e:
        result["error"] = f"Failed to apply patch: {str(e)}"
        result["details"].append(str(e))

    return result
