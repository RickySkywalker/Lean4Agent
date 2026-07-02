"""Parse LLM responses and extract tool calls.

This module provides utilities for parsing LLM responses to extract:
- Standard OpenAI-format tool calls
- Inline tool calls embedded in code blocks
- Raw bash/shell commands for direct execution
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, FrozenSet, List, Optional, Set, Tuple

from ..parsing.inline_tools import (PYTHON_BLOCK_LANGS,
                                    detect_malformed_code_blocks,
                                    extract_code_blocks_with_lang,
                                    parse_inline_tool_calls,
                                    select_executable_block,
                                    truncate_to_first_code_block,
                                    wrap_python_as_bash)

# Shell-like languages that can contain raw bash commands
SHELL_BLOCK_LANGS: FrozenSet[str] = frozenset(
    {"bash", "sh", "shell", "zsh", "fish", ""}
)


@dataclass
class ParsedResponse:
    """Parsed LLM response with extracted tool calls.

    Attributes:
        content: The text content of the LLM response.
        tool_calls: List of OpenAI-format tool call objects.
        inline_calls: List of parsed inline tool calls from code blocks.
        raw_bash_block: Raw shell command if a bash block was detected.
        parse_error: Error message if parsing failed (e.g., malformed code block).
    """

    content: str
    tool_calls: List[Any] = field(default_factory=list)
    inline_calls: List[Any] = field(default_factory=list)
    raw_bash_block: Optional[str] = None
    parse_error: Optional[str] = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if any tool calls were extracted."""
        return bool(self.tool_calls or self.inline_calls or self.raw_bash_block)

    @property
    def has_error(self) -> bool:
        """Check if parsing encountered an error."""
        return self.parse_error is not None


class ResponseParser:
    """Parses LLM responses to extract different types of tool calls.

    This parser handles three types of tool invocations:
    1. Standard OpenAI tool_calls in the response
    2. Inline tool calls written as function-call syntax in code blocks
    3. Raw bash commands in shell code blocks

    Example:
        parser = ResponseParser(
            enable_inline=True,
            allowed_tool_names={"shell_run", "fs_write"},
            submodule_names={"analyze_code"},
        )
        result = parser.parse(llm_message)
        if result.has_error:
            handle_error(result.parse_error)
        elif result.tool_calls:
            execute_tool_calls(result.tool_calls)
    """

    def __init__(
        self,
        enable_inline: bool = False,
        allowed_tool_names: Optional[Set[str]] = None,
        submodule_names: Optional[Set[str]] = None,
        strict_bash_fence: bool = False,
    ):
        """Initialize the response parser.

        Args:
            enable_inline: Whether to parse inline tool calls from code blocks.
            allowed_tool_names: Set of valid tool names for inline call detection.
            submodule_names: Set of submodule function names for inline call detection.
            strict_bash_fence: Only execute explicitly shell-tagged ```bash fences
                (engine fix, conv 7ef9d7d4); kept in sync with llm_executor. Default
                False preserves the legacy first-any-fence behavior.
        """
        self.enable_inline = enable_inline
        self.allowed_tool_names: Set[str] = allowed_tool_names or set()
        self.submodule_names: Set[str] = submodule_names or set()
        self.strict_bash_fence = strict_bash_fence

    def parse(self, message: Any) -> ParsedResponse:
        """Parse an LLM message and extract all tool calls.

        Args:
            message: The message object from LLM response.
                     Expected to have .content (str) and .tool_calls (list) attributes.

        Returns:
            ParsedResponse containing all extracted tool calls and any parse errors.
        """
        content = message.content or ""
        tool_calls = list(message.tool_calls or [])

        # Truncate to first code block if multiple are present (legacy only — strict
        # mode keeps the full content so a real ```bash after a quoted fence survives)
        if self.enable_inline and not self.strict_bash_fence:
            content = truncate_to_first_code_block(content)

        # Check for malformed inline tools when inline parsing is enabled
        if self.enable_inline:
            error = detect_malformed_code_blocks(content)
            if error:
                return ParsedResponse(
                    content=content,
                    tool_calls=tool_calls,
                    inline_calls=[],
                    raw_bash_block=None,
                    parse_error=error,
                )

        # Extract inline calls and raw bash blocks
        inline_calls: List[Any] = []
        raw_bash: Optional[str] = None

        if self.enable_inline:
            raw_bash, inline_calls = self._extract_inline_calls(content)

        return ParsedResponse(
            content=content,
            tool_calls=tool_calls,
            inline_calls=inline_calls,
            raw_bash_block=raw_bash,
            parse_error=None,
        )

    def _extract_inline_calls(self, content: str) -> Tuple[Optional[str], List[Any]]:
        """Extract inline tool calls and raw bash from content.

        Analyzes code blocks in the content to determine if they contain:
        - Raw bash commands (for shell-like language blocks)
        - Structured inline tool calls (function-call syntax)

        Args:
            content: The text content to parse.

        Returns:
            Tuple of (raw_bash_block, inline_calls) where:
            - raw_bash_block is the shell command if detected, None otherwise
            - inline_calls is a list of parsed inline tool calls
        """
        selected_block = select_executable_block(
            content, strict_bash_fence=self.strict_bash_fence)
        raw_bash_block: Optional[str] = None

        if selected_block is not None:
            lang, block_content = selected_block
            candidate_block = block_content.strip()

            # Check if this is a shell-like block that could be raw bash
            if candidate_block and self._is_shell_block(lang):
                # Check if it looks like a known function call
                if not self._looks_like_tool_call(candidate_block):
                    raw_bash_block = candidate_block
            elif (
                candidate_block and lang and lang.strip().lower() in PYTHON_BLOCK_LANGS
            ):
                raw_bash_block = wrap_python_as_bash(candidate_block)

        # Parse structured inline tool calls only if not a raw bash block
        inline_calls = [] if raw_bash_block else parse_inline_tool_calls(content)

        return raw_bash_block, inline_calls

    def _is_shell_block(self, lang: Optional[str]) -> bool:
        """Check if a code block language indicates shell/bash content.

        Args:
            lang: The language specifier from the code block (e.g., "bash", "sh").

        Returns:
            True if the language is a shell-like language or unspecified.
        """
        return not lang or lang.strip().lower() in SHELL_BLOCK_LANGS

    def _looks_like_tool_call(self, content: str) -> bool:
        """Check if content looks like a function/tool call.

        Args:
            content: The code block content to check.

        Returns:
            True if the content appears to be a tool or submodule call.
        """
        match = re.match(r"^\s*([A-Za-z_]\w*)\s*\(", content)
        if not match:
            return False

        function_name = match.group(1)
        all_known_names = self.allowed_tool_names | self.submodule_names
        return function_name in all_known_names
