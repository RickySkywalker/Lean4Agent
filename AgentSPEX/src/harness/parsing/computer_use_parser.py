"""Parser for Set-of-Marks computer-use action strings output by vision models.

Usage:
    action = parse_computer_use_action(llm_text, mode="set_of_marks")
    # {"key": "click", "args": {"element_number": 5}}
"""

from __future__ import annotations

import re
from typing import Optional


def parse_computer_use_action(text: str, mode: str) -> Optional[dict]:
    """Extract a computer-use action from LLM response text.

    Args:
        text: Full LLM response (may include thought text before the action line).
        mode: Must be "set_of_marks".

    Returns:
        dict with "key" and "args", or None if no action found.
    """
    if mode == "set_of_marks":
        return _parse_som(text)
    return None


# ---------------------------------------------------------------------------
# Set-of-Marks parser
# ---------------------------------------------------------------------------

_SOM_PATTERNS = [
    # Click [N]
    (
        re.compile(r"Click\s*\[(\d+)\]", re.IGNORECASE),
        lambda m: {"key": "click", "args": {"element_number": int(m.group(1))}},
    ),
    # Type [N] [text]  — text in brackets (zero or more chars)
    (
        re.compile(r"Type\s*\[(\d+)\]\s*\[([^\]]*)\]", re.IGNORECASE),
        lambda m: {
            "key": "type",
            "args": {"element_number": int(m.group(1)), "text": m.group(2).strip()},
        },
    ),
    # Type [N] text   — text without brackets (one or more non-newline chars)
    (
        re.compile(r"Type\s*\[(\d+)\]\s+([^\[\n]+)", re.IGNORECASE),
        lambda m: {
            "key": "type",
            "args": {"element_number": int(m.group(1)), "text": m.group(2).strip()},
        },
    ),
    # Hover [N]
    (
        re.compile(r"Hover\s*\[(\d+)\]", re.IGNORECASE),
        lambda m: {"key": "hover", "args": {"element_number": int(m.group(1))}},
    ),
    # Scroll [N or WINDOW] [up or down]
    (
        re.compile(r"Scroll\s*\[(\d+|WINDOW)\]\s*\[?(up|down)\]?", re.IGNORECASE),
        lambda m: {
            "key": "scroll",
            "args": {"target": m.group(1), "direction": m.group(2).lower()},
        },
    ),
    # ANSWER [content]
    (
        re.compile(r"ANSWER\s*\[([^\]]*)\]", re.IGNORECASE),
        lambda m: {"key": "answer", "args": {"content": m.group(1)}},
    ),
    # GoBack
    (re.compile(r"\bGoBack\b", re.IGNORECASE), lambda m: {"key": "goback", "args": {}}),
    # Wait
    (re.compile(r"\bWait\b", re.IGNORECASE), lambda m: {"key": "wait", "args": {}}),
]


def _parse_som(text: str) -> Optional[dict]:
    for line in _action_lines(text):
        for pattern, builder in _SOM_PATTERNS:
            m = pattern.search(line)
            if m:
                return builder(m)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Prefixes the model sometimes outputs before the action
_ACTION_PREFIX_RE = re.compile(
    r"^(Action\s*:\s*|Next\s*:\s*|I will\s*|My action\s*:\s*)", re.IGNORECASE
)


_THOUGHT_PREFIX_RE = re.compile(r"^Thought\s*:", re.IGNORECASE)


def _action_lines(text: str):
    """Yield cleaned candidate lines most likely to contain an action."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip Thought lines — they are prose and can accidentally match
        # patterns like \bWait\b or \bGoBack\b, or contain element numbers
        # that would be mistaken for action targets.
        if _THOUGHT_PREFIX_RE.match(line):
            continue
        line = _ACTION_PREFIX_RE.sub("", line).strip()
        yield line
