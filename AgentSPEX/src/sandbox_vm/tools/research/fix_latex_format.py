"""LaTeX format fixing tool for ensuring correct LaTeX syntax in generated content."""

import re
from typing import Match

from sandbox_vm.tools.utils import _err, _ok


def fix_latex_format(content: str) -> dict:
    """
    Fix LaTeX format issues in content, including:
    - Convert Markdown syntax to LaTeX (**, *, `code`)
    - Fix double backslashes (\\ -> \)
    - Escape special characters (_ -> \_, & -> \&, # -> \#)
    - Fix citation keys (ensure \cite{} format)
    - Remove literal \n characters
    - Fix section headers and formatting

    Args:
        content: LaTeX content that may contain format issues.

    Returns:
        {"fixed_content": str} on success, or {"error": str, "message": str} on failure

    Examples:
        >>> result = fix_latex_format("**bold** text with _underscore_")
        >>> print(result["fixed_content"])
        "\\textbf{bold} text with \\_underscore\\_"

        >>> result = fix_latex_format("\\section{Method}\\nSome text")
        >>> print(result["fixed_content"])
        "\\section{Method}\n\nSome text"
    """
    if not content or not isinstance(content, str):
        return _err("INVALID_INPUT", message="content must be a non-empty string")

    try:
        fixed = content

        # STEP 1: Fix mixed Markdown+LaTeX (e.g., **text\textbf{more** -> \textbf{text more})
        fixed = re.sub(
            r"\*\*([^\*]*?)\\textbf\{([^\}]*?)\*\*", r"\\textbf{\1\2}", fixed
        )
        fixed = re.sub(r"\\textbf\{([^\}]*?)\*\*", r"\\textbf{\1}", fixed)
        fixed = re.sub(r"\*\*([^\*]*?)\\textbf\{", r"\\textbf{\1", fixed)

        # STEP 2: **bold** -> \textbf{bold}
        def replace_bold(match):
            text = match.group(1)
            # Don't convert if it looks like it's already LaTeX or in math mode
            if "\\" in text or "$" in text:
                return match.group(0)
            return f"\\textbf{{{text}}}"

        fixed = re.sub(r"\*\*([^\*]+?)\*\*", replace_bold, fixed)

        # STEP 3: *italic* -> \textit{italic} (single asterisk, not **)
        def replace_italic(match):
            text = match.group(1)
            if "\\" in text or "$" in text:
                return match.group(0)
            return f"\\textit{{{text}}}"

        fixed = re.sub(
            r"(?<!\*)\*([^\*\s][^\*]*?[^\*\s])\*(?!\*)", replace_italic, fixed
        )

        # STEP 4: `code` -> \texttt{code} (with special char escaping)
        def replace_code(match):
            text = match.group(1)
            if "\\" in text:
                return match.group(0)
            # Escape special LaTeX characters in code
            text = text.replace("_", "\\_").replace("#", "\\#").replace("%", "\\%")
            return f"\\texttt{{{text}}}"

        fixed = re.sub(r"`([^`]+?)`", replace_code, fixed)

        # STEP 5: Fix double backslashes (\\ -> \) but preserve correct ones
        # Only replace double backslashes that are clearly errors (like \\section, \\cite)
        # Pattern: \\ followed by a letter (command) -> single \
        fixed = re.sub(r"\\(\\[a-zA-Z])", r"\1", fixed)

        # STEP 6: Fix citation keys - ensure standalone keys are wrapped in \cite{}
        # Pattern: word_word or word_year (like Gao_2024) not in \cite{} -> \cite{key}
        def fix_citation_key(match):
            key = match.group(0)
            # Check if it's already in a citation command
            start_pos = match.start()
            # Look backwards for \cite{ or \citet{ or \citep{
            before = fixed[:start_pos]
            if re.search(r"\\cite[a-z]*\{[^}]*$", before):
                return key  # Already in citation, don't change
            return f"\\cite{{{key}}}"

        # Match patterns like: word_word, word_year, etc. (common citation key formats)
        fixed = re.sub(
            r"\b([A-Z][a-z]+_[0-9]{4}|[A-Z][a-z]+[A-Z][a-z]+_[0-9]{4})\b",
            fix_citation_key,
            fixed,
        )

        # STEP 7: Escape special characters (_ -> \_, & -> \&, # -> \#)
        # But NOT inside \cite{}, \texttt{}, math mode ($...$ or \[...\]), or existing escapes
        # Strategy: Replace protected regions with placeholders (using safe chars), escape, then restore
        # Note: Use placeholders without special chars to avoid them being escaped

        protected_regions = []
        # Use a placeholder format that doesn't contain special chars that need escaping
        placeholder_base = "PROTECTEDREGION{}PROTECTED"

        # Find and replace protected regions (collect all matches first, then replace in reverse order)
        patterns = [
            (r"\\cite\{[^}]+\}", "cite"),
            (r"\\texttt\{[^}]+\}", "texttt"),
            (r"\$[^$]+\$", "math_inline"),
            (r"\\\[.*?\\\]", "math_display"),
        ]

        # Collect all matches with their positions
        all_matches = []
        for pattern, tag in patterns:
            for match in re.finditer(pattern, fixed, re.DOTALL):
                all_matches.append((match.start(), match.end(), match.group(0)))

        # Sort by start position in reverse order (process from end to start to maintain positions)
        all_matches.sort(key=lambda x: x[0], reverse=True)

        # Replace with placeholders
        for start, end, original in all_matches:
            placeholder = placeholder_base.format(len(protected_regions))
            protected_regions.append((placeholder, original))
            fixed = fixed[:start] + placeholder + fixed[end:]

        # Now escape special chars (not already escaped)
        fixed = re.sub(r"(?<!\\)_", r"\\_", fixed)
        fixed = re.sub(r"(?<!\\)&", r"\\&", fixed)
        fixed = re.sub(r"(?<!\\)#", r"\\#", fixed)

        # Restore protected regions (in reverse order of replacement)
        for placeholder, original in protected_regions:
            fixed = fixed.replace(placeholder, original)

        # STEP 8: Remove literal \n (replace with actual newlines)
        # Handle both \\n (escaped) and \n (single backslash) patterns
        fixed = re.sub(r"\\\\n", "\n", fixed)  # \\n -> newline
        fixed = re.sub(r"(?<!\\)\\n", "\n", fixed)  # \n -> newline (but not \\n)

        # STEP 8.1: Remove trailing literal \n at the end of content
        # Remove literal \n at the very end (after converting to newlines)
        fixed = re.sub(r"\\n\s*$", "", fixed)

        # STEP 8.1: Remove trailing \n at the end of content
        # Remove literal \n at the very end (after all processing)
        fixed = re.sub(r"\\n\s*$", "", fixed)
        # Also remove trailing newlines (actual newlines, not literal \n)
        fixed = fixed.rstrip("\n")

        # STEP 9: Fix section headers - ensure proper format
        # Ensure \section{...} is followed by a blank line
        fixed = re.sub(r"(\\section\{[^}]+\})\s*\n*", r"\1\n\n", fixed)
        fixed = re.sub(r"(\\subsection\{[^}]+\})\s*\n*", r"\1\n\n", fixed)
        fixed = re.sub(r"(\\begin\{abstract\})\s*\n*", r"\1\n\n", fixed)

        # STEP 9.1: Fix paragraph headers - ensure proper format
        # Ensure \paragraph{...} is followed by a blank line (if not already)
        fixed = re.sub(r"(\\paragraph\{[^}]+\})([^\n])", r"\1\n\2", fixed)
        fixed = re.sub(r"(\\paragraph\{[^}]+\})\s*\n([^\n])", r"\1\n\n\2", fixed)

        # STEP 9.2: Remove instruction text that shouldn't be in the output
        # Remove patterns like "\textbf{CRITICAL}: After calling the tool..."
        fixed = re.sub(r"\\textbf\{CRITICAL\}[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"CRITICAL[^.]*\.", "", fixed, flags=re.DOTALL)
        # Remove common instruction patterns
        fixed = re.sub(r"After calling the tool[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"extract ONLY[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"it's a JSON object[^.]*\.", "", fixed, flags=re.DOTALL)

        # STEP 9.3: Fix algorithm commands - ensure all uppercase
        # LaTeX algorithmic package requires uppercase commands
        algorithm_commands = {
            r"\\State\b": r"\\STATE",
            r"\\For\b": r"\\FOR",
            r"\\If\b": r"\\IF",
            r"\\While\b": r"\\WHILE",
            r"\\EndFor\b": r"\\ENDFOR",
            r"\\EndIf\b": r"\\ENDIF",
            r"\\EndWhile\b": r"\\ENDWHILE",
            r"\\Return\b": r"\\RETURN",
            r"\\EndFor\b": r"\\ENDFOR",
            r"\\EndIf\b": r"\\ENDIF",
            r"\\EndWhile\b": r"\\ENDWHILE",
        }
        for pattern, replacement in algorithm_commands.items():
            fixed = re.sub(pattern, replacement, fixed)

        # STEP 9.4: Fix math symbols without $ delimiters
        # Wrap standalone math symbols like \hat{y}, \bar{x}, \tilde{z} with $
        # But NOT if already in math mode ($...$ or \[...\] or equation environment)
        # Strategy: Protect existing math regions, then fix standalone symbols

        # First, protect existing math regions
        math_protected = []
        math_placeholder_base = "MATHREGION{}MATH"

        # Find and protect math regions
        math_patterns = [
            (r"\$[^$]+\$", "inline"),
            (r"\\\[.*?\\\]", "display"),
            (r"\\begin\{equation\}.*?\\end\{equation\}", "equation"),
            (r"\\begin\{align\}.*?\\end\{align\}", "align"),
            (r"\\begin\{equation\*\}.*?\\end\{equation\*\}", "equation_star"),
        ]

        math_matches = []
        for pattern, tag in math_patterns:
            for match in re.finditer(pattern, fixed, re.DOTALL):
                math_matches.append((match.start(), match.end(), match.group(0)))

        # Sort by start position in reverse order
        math_matches.sort(key=lambda x: x[0], reverse=True)

        # Replace with placeholders
        for start, end, original in math_matches:
            placeholder = math_placeholder_base.format(len(math_protected))
            math_protected.append((placeholder, original))
            fixed = fixed[:start] + placeholder + fixed[end:]

        # Now fix standalone math symbols (not in protected regions)
        # Common math symbols: \hat{}, \bar{}, \tilde{}, \vec{}, \dot{}, \ddot{}, etc.
        # Only wrap if not already in math mode (we've protected math regions above)
        math_symbol_patterns = [
            r"\\hat\{[^}]+\}",
            r"\\bar\{[^}]+\}",
            r"\\tilde\{[^}]+\}",
            r"\\vec\{[^}]+\}",
            r"\\dot\{[^}]+\}",
            r"\\ddot\{[^}]+\}",
            r"\\overline\{[^}]+\}",
            r"\\underline\{[^}]+\}",
        ]

        # Wrap standalone math symbols with $ (they're not in protected math regions)
        for pattern in math_symbol_patterns:
            # Match the pattern and wrap it with $
            fixed = re.sub(pattern, lambda m: f"${m.group(0)}$", fixed)

        # Restore protected math regions
        for placeholder, original in math_protected:
            fixed = fixed.replace(placeholder, original)

        # STEP 10: Fix multiple consecutive newlines
        fixed = re.sub(r"\n{3,}", "\n\n", fixed)

        # STEP 11: Remove markdown code blocks if present
        fixed = re.sub(r"```latex\s*(.*?)\s*```", r"\1", fixed, flags=re.DOTALL)
        fixed = re.sub(r"```\s*(.*?)\s*```", r"\1", fixed, flags=re.DOTALL)

        # STEP 12: Remove document structure commands (if present)
        patterns_to_remove = [
            r"\\documentclass(?:\[[^\]]*\])?\{[^\}]+\}",
            r"\\begin\{document\}",
            r"\\end\{document\}",
            r"\\maketitle",
            r"\\title\{.*?\}",
        ]
        for pattern in patterns_to_remove:
            fixed = re.sub(pattern, "", fixed, flags=re.DOTALL)

        return _ok(fixed_content=fixed.strip())

    except Exception as e:
        return _err("PROCESSING_ERROR", message=f"Failed to fix LaTeX format: {str(e)}")
