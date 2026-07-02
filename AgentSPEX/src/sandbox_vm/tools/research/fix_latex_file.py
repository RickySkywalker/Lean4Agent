"""LaTeX file fixing tool that directly modifies files in place."""

import os
import re
from pathlib import Path

from sandbox_vm.tools.utils import _err, _ok


def fix_latex_file(file_path: str) -> dict:
    """
    Fix LaTeX format issues in a file by reading, fixing, and writing back.

    This tool directly modifies the file in place, avoiding issues with
    variable expansion and JSON serialization that can occur when saving
    fixed content through LLM calls.

    Args:
        file_path: Path to the LaTeX file to fix (relative to workspace or absolute).

    Returns:
        {"message": str} on success, or {"error": str, "message": str} on failure

    Examples:
        >>> result = fix_latex_file("sections/method.tex")
        >>> print(result["message"])
        "Fixed LaTeX format in sections/method.tex"
    """
    if not file_path or not isinstance(file_path, str):
        return _err("INVALID_INPUT", message="file_path must be a non-empty string")

    try:
        # Resolve path (handle both relative and absolute paths)
        if not Path(file_path).is_absolute():
            # Assume relative to workspace
            workspace_root = Path(os.environ.get("VM_WORKSPACE", "/workspace"))
            full_path = workspace_root / file_path.lstrip("/")
        else:
            full_path = Path(file_path)

        # Check if file exists
        if not full_path.exists():
            return _err("FILE_NOT_FOUND", message=f"File not found: {file_path}")

        # Read file content
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return _err("READ_ERROR", message=f"Failed to read file: {str(e)}")

        if not content:
            return _err("EMPTY_FILE", message="File is empty")

        # Apply the same fixes as fix_latex_format
        fixed = content

        # STEP 1: Fix mixed Markdown+LaTeX
        fixed = re.sub(
            r"\*\*([^\*]*?)\\textbf\{([^\}]*?)\*\*", r"\\textbf{\1\2}", fixed
        )
        fixed = re.sub(r"\\textbf\{([^\}]*?)\*\*", r"\\textbf{\1}", fixed)
        fixed = re.sub(r"\*\*([^\*]*?)\\textbf\{", r"\\textbf{\1", fixed)

        # STEP 2: **bold** -> \textbf{bold}
        def replace_bold(match):
            text = match.group(1)
            if "\\" in text or "$" in text:
                return match.group(0)
            return f"\\textbf{{{text}}}"

        fixed = re.sub(r"\*\*([^\*]+?)\*\*", replace_bold, fixed)

        # STEP 3: *italic* -> \textit{italic}
        def replace_italic(match):
            text = match.group(1)
            if "\\" in text or "$" in text:
                return match.group(0)
            return f"\\textit{{{text}}}"

        fixed = re.sub(
            r"(?<!\*)\*([^\*\s][^\*]*?[^\*\s])\*(?!\*)", replace_italic, fixed
        )

        # STEP 4: `code` -> \texttt{code}
        def replace_code(match):
            text = match.group(1)
            if "\\" in text:
                return match.group(0)
            text = text.replace("_", "\\_").replace("#", "\\#").replace("%", "\\%")
            return f"\\texttt{{{text}}}"

        fixed = re.sub(r"`([^`]+?)`", replace_code, fixed)

        # STEP 5: Fix double backslashes (\\ -> \)
        # Protect \% first (don't convert \\% to \% accidentally)
        fixed = re.sub(r"\\%", "PERCENTAGEPLACEHOLDER", fixed)
        # Fix \\ followed by a letter (command) -> single \
        fixed = re.sub(r"\\(\\[a-zA-Z])", r"\1", fixed)
        # Also fix \\[ and \\] (display math)
        fixed = re.sub(r"\\\\\[", r"\[", fixed)
        fixed = re.sub(r"\\\\\]", r"\]", fixed)
        # Fix other common double backslashes
        fixed = re.sub(r"\\\\section", r"\\section", fixed)
        fixed = re.sub(r"\\\\subsection", r"\\subsection", fixed)
        fixed = re.sub(r"\\\\paragraph", r"\\paragraph", fixed)
        fixed = re.sub(r"\\\\cite", r"\\cite", fixed)
        fixed = re.sub(r"\\\\begin", r"\\begin", fixed)
        fixed = re.sub(r"\\\\end", r"\\end", fixed)
        # Restore \%
        fixed = fixed.replace("PERCENTAGEPLACEHOLDER", "\\%")

        # STEP 6: Fix citation issues
        # Fix [\cite{...}] -> \cite{...}
        fixed = re.sub(r"\[\\cite\{([^}]+)\}\]", r"\\cite{\1}", fixed)

        # Fix citation keys (standalone keys -> \cite{key})
        def fix_citation_key(match):
            key = match.group(0)
            start_pos = match.start()
            before = fixed[:start_pos]
            if re.search(r"\\cite[a-z]*\{[^}]*$", before):
                return key
            return f"\\cite{{{key}}}"

        fixed = re.sub(
            r"\b([A-Z][a-z]+_[0-9]{4}|[A-Z][a-z]+[A-Z][a-z]+_[0-9]{4})\b",
            fix_citation_key,
            fixed,
        )

        # Fix [\cite{...}] again (in case it was created by the previous step)
        # This handles cases where [key] was converted to [\cite{key}]
        fixed = re.sub(r"\[\\cite\{([^}]+)\}\]", r"\\cite{\1}", fixed)

        # Fix unclosed \cite{...} at the end of file or line
        # Find all \cite{ patterns and check if they're closed
        cite_open_pattern = r"\\cite\{"
        cite_close_pattern = r"\\cite\{[^}]*\}"

        # Find positions of all \cite{
        cite_positions = []
        for match in re.finditer(cite_open_pattern, fixed):
            cite_positions.append(match.start())

        # For each \cite{, check if it has a matching }
        for pos in reversed(cite_positions):
            # Find the content after \cite{
            start = pos + len("\\cite{")
            remaining = fixed[start:]
            # Look for the closing }
            # But be careful - } might be part of the citation content
            # We need to find the } that closes this \cite{
            brace_count = 0
            close_pos = -1
            for i, char in enumerate(remaining):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    if brace_count == 0:
                        # Found the closing }
                        close_pos = start + i
                        break
                    brace_count -= 1

            if close_pos == -1:
                # No closing } found, add one at the end
                fixed = fixed + "}"

        # STEP 7: Escape special characters
        protected_regions = []
        placeholder_base = "PROTECTEDREGION{}PROTECTED"

        patterns = [
            (r"\\cite\{[^}]+\}", "cite"),
            (r"\\texttt\{[^}]+\}", "texttt"),
            (r"\$[^$]+\$", "math_inline"),
            (r"\\\[.*?\\\]", "math_display"),
            (r"\\\(.*?\\\)", "math_inline_paren"),  # Protect \(...\) format
        ]

        all_matches = []
        for pattern, tag in patterns:
            for match in re.finditer(pattern, fixed, re.DOTALL):
                all_matches.append((match.start(), match.end(), match.group(0)))

        all_matches.sort(key=lambda x: x[0], reverse=True)

        for start, end, original in all_matches:
            placeholder = placeholder_base.format(len(protected_regions))
            protected_regions.append((placeholder, original))
            fixed = fixed[:start] + placeholder + fixed[end:]

        fixed = re.sub(r"(?<!\\)_", r"\\_", fixed)
        fixed = re.sub(r"(?<!\\)&", r"\\&", fixed)
        fixed = re.sub(r"(?<!\\)#", r"\\#", fixed)

        for placeholder, original in protected_regions:
            fixed = fixed.replace(placeholder, original)

        # STEP 8: Remove literal \n
        fixed = re.sub(r"\\\\n", "\n", fixed)
        fixed = re.sub(r"(?<!\\)\\n", "\n", fixed)
        fixed = re.sub(r"\\n\s*$", "", fixed)
        fixed = fixed.rstrip("\n")

        # STEP 9: Fix section headers
        fixed = re.sub(r"(\\section\{[^}]+\})\s*\n*", r"\1\n\n", fixed)
        fixed = re.sub(r"(\\subsection\{[^}]+\})\s*\n*", r"\1\n\n", fixed)
        fixed = re.sub(r"(\\begin\{abstract\})\s*\n*", r"\1\n\n", fixed)

        # STEP 9.1: Fix paragraph headers
        fixed = re.sub(r"(\\paragraph\{[^}]+\})([^\n])", r"\1\n\2", fixed)
        fixed = re.sub(r"(\\paragraph\{[^}]+\})\s*\n([^\n])", r"\1\n\n\2", fixed)

        # STEP 9.2: Remove instruction text
        fixed = re.sub(r"\\textbf\{CRITICAL\}[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"CRITICAL[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"After calling the tool[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"extract ONLY[^.]*\.", "", fixed, flags=re.DOTALL)
        fixed = re.sub(r"it's a JSON object[^.]*\.", "", fixed, flags=re.DOTALL)

        # STEP 9.3: Fix algorithm commands
        algorithm_commands = {
            r"\\State\b": r"\\STATE",
            r"\\For\b": r"\\FOR",
            r"\\If\b": r"\\IF",
            r"\\While\b": r"\\WHILE",
            r"\\EndFor\b": r"\\ENDFOR",
            r"\\EndIf\b": r"\\ENDIF",
            r"\\EndWhile\b": r"\\ENDWHILE",
            r"\\Return\b": r"\\RETURN",
        }
        for pattern, replacement in algorithm_commands.items():
            fixed = re.sub(pattern, replacement, fixed)

        # STEP 9.4: Fix math symbols without $ delimiters
        math_protected = []
        math_placeholder_base = "MATHREGION{}MATH"

        math_patterns = [
            (r"\$[^$]+\$", "inline"),
            (r"\\\[.*?\\\]", "display"),
            (r"\\\(.*?\\\)", "inline_paren"),  # Protect \(...\) format
            (r"\\begin\{equation\}.*?\\end\{equation\}", "equation"),
            (r"\\begin\{align\}.*?\\end\{align\}", "align"),
            (r"\\begin\{equation\*\}.*?\\end\{equation\*\}", "equation_star"),
        ]

        math_matches = []
        for pattern, tag in math_patterns:
            for match in re.finditer(pattern, fixed, re.DOTALL):
                math_matches.append((match.start(), match.end(), match.group(0)))

        math_matches.sort(key=lambda x: x[0], reverse=True)

        for start, end, original in math_matches:
            placeholder = math_placeholder_base.format(len(math_protected))
            math_protected.append((placeholder, original))
            fixed = fixed[:start] + placeholder + fixed[end:]

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

        for pattern in math_symbol_patterns:
            fixed = re.sub(pattern, lambda m: f"${m.group(0)}$", fixed)

        for placeholder, original in math_protected:
            fixed = fixed.replace(placeholder, original)

        # STEP 10: Fix math mode issues
        # Fix multiple $ signs ($$ -> $, but preserve $$ for display math)
        # First, protect display math \[...\]
        display_math_protected = []
        display_placeholder_base = "DISPLAYMATH{}MATH"

        display_matches = list(re.finditer(r"\\\[.*?\\\]", fixed, re.DOTALL))
        display_matches.sort(key=lambda x: x[0], reverse=True)

        for match in display_matches:
            placeholder = display_placeholder_base.format(len(display_math_protected))
            display_math_protected.append((placeholder, match.group(0)))
            fixed = fixed[: match.start()] + placeholder + fixed[match.end() :]

        # Fix multiple $ in inline math (but not $$ which is display math)
        # Pattern: $...$$ -> $...$ (remove extra $)
        fixed = re.sub(r"(\$[^$]+)\$\$+", r"\1$", fixed)
        # Pattern: $$...$ -> $...$ (remove leading $)
        fixed = re.sub(r"\$\$+([^$]+\$)", r"$\1", fixed)
        # Pattern: standalone $$ -> $ (but be careful)
        # Actually, $$ is valid for display math, so we should preserve it
        # But if it's clearly an error (like $\hat{y}$$), fix it
        fixed = re.sub(r"(\$[^$]+\$)\$\$", r"\1", fixed)

        # Restore display math
        for placeholder, original in display_math_protected:
            fixed = fixed.replace(placeholder, original)

        # Fix unclosed $ in algorithm environment
        # Protect algorithm environments first
        algorithm_protected = []
        algo_placeholder_base = "ALGOREGION{}ALGO"

        algo_pattern = r"\\begin\{algorithm\}.*?\\end\{algorithm\}"
        algo_matches = list(re.finditer(algo_pattern, fixed, re.DOTALL))
        algo_matches.sort(key=lambda x: x[0], reverse=True)

        for match in algo_matches:
            placeholder = algo_placeholder_base.format(len(algorithm_protected))
            algorithm_protected.append((placeholder, match.group(0)))
            fixed = fixed[: match.start()] + placeholder + fixed[match.end() :]

        # Fix math mode issues in algorithm (after restoring)
        for i, (placeholder, algo_content) in enumerate(algorithm_protected):
            # Fix patterns like "$\hat{y}$$" -> "$\hat{y}$" (remove extra $)
            # Pattern: $...$$ -> $...$
            algo_content = re.sub(r"(\$[^$]+)\$\$+", r"\1$", algo_content)

            # Fix patterns like "\hat{y}$$" (without opening $) -> "$\hat{y}$"
            algo_content = re.sub(r"(\\hat\{[^}]+\})\$\$+", r"$\1$", algo_content)

            # Fix patterns like "\hat{y}" without $ -> "$\hat{y}$" (in STATE lines)
            # Pattern: \STATE ... \hat{y} ... -> \STATE ... $\hat{y}$ ...
            algo_content = re.sub(
                r"(\\STATE[^$]*?)(\\hat\{[^}]+\})(?![$\\])", r"\1$\2$", algo_content
            )

            # Fix patterns like "Compute \hat{y} \gets" -> "Compute $\hat{y} \gets$"
            # But be careful - if it's already in $...$, don't double-wrap
            algo_content = re.sub(
                r"(Compute |\()(\\hat\{[^}]+\})", r"\1$\2$", algo_content
            )

            # Fix patterns like "\hat{y} \gets" without $ -> "$\hat{y} \gets$"
            # But only if not already in math mode
            algo_content = re.sub(
                r"(?<!\$)(\\hat\{[^}]+\}) (\\gets|\\leftarrow)",
                r"$\1 \2$",
                algo_content,
            )

            # Fix patterns like "A_p, \tilde{H}_p" (variables without $) -> "$A_p, \tilde{H}_p$"
            # Pattern: variable patterns like X_p, H_p, etc. in STATE lines
            # But only if they're not already in math mode
            # This is tricky - we need to identify math expressions
            # For now, fix common patterns like "A_p, \tilde{H}_p" -> "$A_p, \tilde{H}_p$"
            algo_content = re.sub(
                r"(\\STATE[^$]*?)([A-Z]_[a-z]|\\tilde\{H\}_[pq])(?![$\\])",
                lambda m: (
                    m.group(1) + f"${m.group(2)}$"
                    if "$" not in m.group(1)[-10:]
                    else m.group(0)
                ),
                algo_content,
            )

            # Fix patterns like "$A\_p, $\tilde{H}$\_p$" -> "$A_p, \tilde{H}_p$"
            # This involves both nested $ blocks and adjacent math blocks
            # Strategy:
            # 1. First merge nested $ blocks (like "$A\_p, $\tilde{H}$\_p$")
            # 2. Then merge adjacent math blocks (like "$A_p, $" followed by "$\tilde{H}_p$")

            # Step 1: Find and merge nested $ blocks
            # Pattern: $X, $Y$Z$ -> $X, YZ$ (nested $ inside a $ block)
            def merge_nested_math(match):
                outer_content = match.group(1)
                # Check if there are nested $ blocks
                if "$" in outer_content:
                    # Remove nested $ and merge
                    merged = re.sub(r"\$([^$]+)\$", r"\1", outer_content)
                    merged = re.sub(r"\\_", "_", merged)
                    return f"${merged}$"
                return match.group(0)

            # Apply nested math merge (may need multiple passes)
            for _ in range(3):  # Max 3 passes to handle deeply nested cases
                new_content = re.sub(
                    r"\$([^$]*\$[^$]+\$[^$]*)\$", merge_nested_math, algo_content
                )
                if new_content == algo_content:
                    break
                algo_content = new_content

            # Step 2: Merge adjacent math blocks
            # Pattern: $X$ $Y$ -> $X Y$ (when they're adjacent)
            # But be careful - only merge if they're truly adjacent (no text between)
            algo_content = re.sub(
                r"\$([^$]+)\$\s*\$([^$]+)\$", r"$\1 \2$", algo_content
            )

            # Step 3: Fix \_ -> _ in all remaining math blocks
            math_blocks = list(re.finditer(r"\$([^$]+)\$", algo_content))
            for block_match in reversed(math_blocks):
                block_content = block_match.group(1)
                block_start = block_match.start()
                block_end = block_match.end()
                # Fix \_ -> _
                fixed_content = re.sub(r"\\_", "_", block_content)
                algo_content = (
                    algo_content[:block_start]
                    + f"${fixed_content}$"
                    + algo_content[block_end:]
                )

            # Fix unclosed $ at the end of lines (like "\hat{y} \gets ...$")
            # Pattern: text ending with $ but no opening $ before
            algo_content = re.sub(
                r"(?<!\$)(\\hat\{[^}]+\} [^$]+)\$", r"$\1$", algo_content
            )

            algorithm_protected[i] = (placeholder, algo_content)

        # Restore algorithm environments
        for placeholder, algo_content in algorithm_protected:
            fixed = fixed.replace(placeholder, algo_content)

        # Fix _ in math mode (should not be escaped as \_)
        # But only inside $...$ blocks, and protect \cite{} inside math
        # Also need to handle nested $ blocks (like "$A\_p, $\tilde{H}$\_p$")
        def fix_underscore_in_math(match):
            math_content = match.group(1)

            # First, handle nested $ blocks - merge them
            # Pattern: $X\_Y, $Z$W$ -> $X_Y, ZW$
            # Find all $...$ blocks within this math block
            nested_math = re.findall(r"\$([^$]+)\$", math_content)
            if nested_math:
                # There are nested $ blocks - merge them
                # Replace all $...$ with just the content
                math_content = re.sub(r"\$([^$]+)\$", r"\1", math_content)

            # Protect \cite{...} first
            cite_protected = []
            cite_placeholder_base = "CITEMATH{}CITE"

            cite_matches = list(re.finditer(r"\\cite\{[^}]+\}", math_content))
            cite_matches.sort(key=lambda x: x[0], reverse=True)

            for cite_match in cite_matches:
                placeholder = cite_placeholder_base.format(len(cite_protected))
                cite_protected.append((placeholder, cite_match.group(0)))
                math_content = (
                    math_content[: cite_match.start()]
                    + placeholder
                    + math_content[cite_match.end() :]
                )

            # Replace \_ with _ in math mode
            math_content = re.sub(r"\\_", "_", math_content)

            # Restore protected \cite{}
            for placeholder, original in cite_protected:
                math_content = math_content.replace(placeholder, original)

            return f"${math_content}$"

        # Fix math blocks, but handle nested $ carefully
        # First pass: fix simple cases
        fixed = re.sub(r"\$([^$]+)\$", fix_underscore_in_math, fixed)

        # Second pass: fix nested $ patterns like "$A\_p, $\tilde{H}$\_p$"
        # Pattern: $X\_Y, $Z$W$ -> $X_Y, ZW$
        def fix_nested_math(match):
            outer_content = match.group(1)
            # Find nested $ blocks and merge them
            nested_pattern = r"\$([^$]+)\$"
            nested_matches = list(re.finditer(nested_pattern, outer_content))
            if nested_matches:
                # Replace nested $...$ with just content
                result = outer_content
                for nested_match in reversed(nested_matches):
                    nested_content = nested_match.group(1)
                    # Fix \_ in nested content
                    nested_content = re.sub(r"\\_", "_", nested_content)
                    result = (
                        result[: nested_match.start()]
                        + nested_content
                        + result[nested_match.end() :]
                    )
                # Fix \_ in the rest
                result = re.sub(r"\\_", "_", result)
                return f"${result}$"
            return match.group(0)

        # Apply nested math fix
        fixed = re.sub(r"\$([^$]*\$[^$]+\$[^$]*)\$", fix_nested_math, fixed)

        # Fix display math \[...\] - ensure _ is not escaped
        def fix_underscore_in_display_math(match):
            math_content = match.group(1)
            # Protect \cite{...} first
            cite_protected = []
            cite_placeholder_base = "CITEMATHDISP{}CITE"

            cite_matches = list(re.finditer(r"\\cite\{[^}]+\}", math_content))
            cite_matches.sort(key=lambda x: x[0], reverse=True)

            for cite_match in cite_matches:
                placeholder = cite_placeholder_base.format(len(cite_protected))
                cite_protected.append((placeholder, cite_match.group(0)))
                math_content = (
                    math_content[: cite_match.start()]
                    + placeholder
                    + math_content[cite_match.end() :]
                )

            # Replace \_ with _ (but not in commands)
            math_content = re.sub(r"\\_", "_", math_content)

            # Restore protected \cite{}
            for placeholder, original in cite_protected:
                math_content = math_content.replace(placeholder, original)

            return f"\\[{math_content}\\]"

        fixed = re.sub(r"\\\[([^\]]+)\\\]", fix_underscore_in_display_math, fixed)

        # STEP 11: Fix multiple consecutive newlines
        fixed = re.sub(r"\n{3,}", "\n\n", fixed)

        # STEP 12: Remove markdown code blocks
        fixed = re.sub(r"```latex\s*(.*?)\s*```", r"\1", fixed, flags=re.DOTALL)
        fixed = re.sub(r"```\s*(.*?)\s*```", r"\1", fixed, flags=re.DOTALL)

        # STEP 13: Remove document structure commands
        patterns_to_remove = [
            r"\\documentclass(?:\[[^\]]*\])?\{[^\}]+\}",
            r"\\begin\{document\}",
            r"\\end\{document\}",
            r"\\maketitle",
            r"\\title\{.*?\}",
        ]
        for pattern in patterns_to_remove:
            fixed = re.sub(pattern, "", fixed, flags=re.DOTALL)

        # STEP 14: Final fix for unclosed \cite{ at the end
        # Check if the file ends with an unclosed \cite{
        # Pattern: \cite{... at the end without }
        if re.search(r"\\cite\{[^}]*$", fixed):
            fixed = fixed + "}"

        # STEP 15: Remove trailing "} if present (from JSON serialization issues)
        fixed = fixed.rstrip()
        if fixed.endswith('"}'):
            fixed = fixed[:-2].rstrip()
        elif fixed.endswith("}"):
            # Check if it's part of a valid LaTeX command
            # If the last } closes a \cite{, it's valid
            # Otherwise, it might be a stray }
            # Check if there's a \cite{ before this }
            last_brace_pos = len(fixed) - 1
            # Look backwards for the nearest \cite{
            before_last_brace = fixed[:last_brace_pos]
            nearest_cite = list(re.finditer(r"\\cite\{", before_last_brace))
            if nearest_cite:
                # Check if this } closes the last \cite{
                last_cite_start = nearest_cite[-1].start()
                cite_content = fixed[last_cite_start + len("\\cite{") : last_brace_pos]
                # If there's no } in the content, this } is valid
                if "}" not in cite_content:
                    # This } is valid, don't remove it
                    pass
                else:
                    # There's already a } in the content, this might be a stray }
                    # But be careful - don't remove if it's part of \cite{Gao_2024,Chen_2020}
                    # Check if it's a multi-citation
                    if "," in cite_content and cite_content.count(
                        "}"
                    ) < cite_content.count(","):
                        # Multi-citation, might need this }
                        pass
                    else:
                        # Might be a stray }, but only remove if it's clearly not part of LaTeX
                        if not re.search(
                            r"\\[a-z]+\{.*\}$", fixed[: last_brace_pos + 1]
                        ):
                            fixed = fixed[:-1].rstrip()

        # Write fixed content back to file
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(fixed.strip())
        except Exception as e:
            return _err("WRITE_ERROR", message=f"Failed to write file: {str(e)}")

        return _ok(message=f"Fixed LaTeX format in {file_path}")

    except Exception as e:
        return _err("PROCESSING_ERROR", message=f"Failed to fix LaTeX file: {str(e)}")
