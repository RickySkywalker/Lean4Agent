import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
CODE_BLOCK_WITH_LANG_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)
SHELL_BLOCK_LANGS = {"bash", "sh", "shell", "zsh", "fish"}
PYTHON_BLOCK_LANGS = {"python", "python3", "py"}


def wrap_python_as_bash(code: str) -> str:
    """Wrap a Python code block as a bash heredoc so it can be executed via shell_run."""
    return f"python3 << '__PYEOF__'\n{code}\n__PYEOF__"


@dataclass
class InlineToolCall:
    name: str
    args: Dict[str, Any]
    raw: str


def extract_code_blocks(text: str) -> List[str]:
    if not text:
        return []
    return [m.group(2) for m in CODE_BLOCK_WITH_LANG_RE.finditer(text)]


def extract_code_blocks_with_lang(text: str) -> List[tuple[str, str]]:
    if not text:
        return []
    return [
        (m.group(1).strip(), m.group(2)) for m in CODE_BLOCK_WITH_LANG_RE.finditer(text)
    ]


def detect_malformed_code_blocks(text: str) -> str:
    if not text:
        return ""

    fence_count = text.count("```")

    if fence_count % 2 != 0:
        return (
            "Inline tool call error: malformed bash block. "
            "Reason: you are missing a closing ``` fence. "
            "No commands from your previous message were executed.\n\n"
            "Please retry your message and follow the provided format:\n\n"
            "<format_example>\n"
            "THOUGHT: Your reasoning and analysis here\n\n"
            "Example of a tool call:\n"
            "```bash\n"
            'some_tool({"arg": "value"})\n'
            "```\n"
            "</format_example>"
        )

    return ""


def truncate_to_first_code_block(text: str) -> str:
    """If text contains multiple code blocks, truncate to keep only the first one.

    Returns the original text if there are 0 or 1 code blocks.
    """
    if not text:
        return text

    matches = list(CODE_BLOCK_RE.finditer(text))
    if len(matches) <= 1:
        return text

    # Truncate right after the closing ``` of the first code block
    first_end = matches[0].end()
    return text[:first_end]


def select_executable_block(
    text: str,
    *,
    strict_bash_fence: bool,
) -> "tuple[str, str] | None":
    """Pick the ``(lang, content)`` code block to EXECUTE from an LLM response.

    Legacy (``strict_bash_fence=False``) — UNCHANGED behavior: the FIRST fenced
    block of any language (an untagged ``` fence counts as bash). Equivalent to the
    historical ``truncate_to_first_code_block`` + ``code_blocks[0]``.

    Strict (``strict_bash_fence=True``) — the engine fix (conv 7ef9d7d4): execute the
    FIRST explicitly shell-tagged fence (``bash``/``sh``/``shell``/``zsh``/``fish``);
    if there is none, the FIRST python-tagged fence (the caller wraps it as a
    heredoc); otherwise ``None``. An UNTAGGED ``` fence is NEVER executed — per the
    SWE system prompt a response with no real bash block "is treated as a signal
    that you have finished the current step", and empirically untagged fences are
    illustration/prose that only crash. This fixes BOTH halves of the bug: a quoted
    ```python / illustration no longer runs as bash, AND a real ```bash action placed
    AFTER such a quote is no longer discarded by truncate-to-first.
    """
    blocks = extract_code_blocks_with_lang(text)
    if not blocks:
        return None
    if not strict_bash_fence:
        return blocks[0]
    for lang, content in blocks:
        if (lang or "").strip().lower() in SHELL_BLOCK_LANGS:
            return (lang, content)
    for lang, content in blocks:
        if (lang or "").strip().lower() in PYTHON_BLOCK_LANGS:
            return (lang, content)
    return None


def _literal_or_source(node: ast.AST, source: str) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        segment = ast.get_source_segment(source, node)
        return segment if segment is not None else str(node)


def _call_args_from_ast(call: ast.Call, source: str) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}

    if call.keywords:
        for kw in call.keywords:
            if kw.arg is None:
                # **kwargs - keep raw
                kwargs["__kwargs__"] = _literal_or_source(kw.value, source)
            else:
                kwargs[kw.arg] = _literal_or_source(kw.value, source)

    if call.args:
        if len(call.args) == 1 and isinstance(call.args[0], ast.Dict) and not kwargs:
            val = _literal_or_source(call.args[0], source)
            if isinstance(val, dict):
                return val
        kwargs["_args"] = [_literal_or_source(arg, source) for arg in call.args]

    return kwargs


def _parse_calls_via_ast(code: str) -> List[InlineToolCall]:
    calls: List[InlineToolCall] = []
    tree = ast.parse(code, mode="exec")
    ordered_nodes: List[ast.Call] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            ordered_nodes.append(node)

    ordered_nodes.sort(
        key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))
    )

    for node in ordered_nodes:
        name = node.func.id
        args = _call_args_from_ast(node, code)
        raw = ast.get_source_segment(code, node) or f"{name}(...)"
        calls.append(InlineToolCall(name=name, args=args, raw=raw))

    return calls


CALL_LINE_RE = re.compile(r"([A-Za-z_]\w*)\s*\((.*?)\)")


def _parse_calls_via_regex(code: str) -> List[InlineToolCall]:
    calls: List[InlineToolCall] = []
    for line in code.splitlines():
        for match in CALL_LINE_RE.finditer(line):
            name = match.group(1)
            raw_args = match.group(2).strip()
            args: Dict[str, Any] = {}
            if raw_args:
                if raw_args.startswith("{") and raw_args.endswith("}"):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        try:
                            fixed = re.sub(r'\\(?!["\\\\/bfnrtu])', r"\\\\", raw_args)
                            args = json.loads(fixed)
                        except Exception:
                            args = {"_raw": raw_args}
                else:
                    args = {"_raw": raw_args}
            calls.append(InlineToolCall(name=name, args=args, raw=match.group(0)))
    return calls


def _parse_single_call_from_block(block: str) -> InlineToolCall | None:
    match = re.search(r"([A-Za-z_]\w*)\s*\(", block)
    if not match:
        return None

    name = match.group(1)
    start = match.end() - 1  # position at '('
    depth = 0
    in_string = False
    string_char = ""
    escape = False

    for i in range(start, len(block)):
        ch = block[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == string_char:
                in_string = False
        else:
            if ch in ("'", '"'):
                in_string = True
                string_char = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    arg_text = block[start + 1 : i].strip()
                    if not arg_text:
                        return InlineToolCall(
                            name=name, args={}, raw=block[match.start() : i + 1]
                        )
                    try:
                        parsed = json.loads(arg_text)
                    except Exception:
                        try:
                            parsed = ast.literal_eval(arg_text)
                        except Exception:
                            return None
                    if isinstance(parsed, dict):
                        return InlineToolCall(
                            name=name, args=parsed, raw=block[match.start() : i + 1]
                        )
                    return InlineToolCall(
                        name=name,
                        args={"_args": [parsed]},
                        raw=block[match.start() : i + 1],
                    )
    return None


def _parse_yaml_block(block: str) -> Dict[str, Any]:
    """Parse a YAML-like block into a dict, with fallback for unquoted values.

    Submodule blocks typically look like:
        query: some free-form text with special chars : @ / etc.

    yaml.safe_load chokes when the value contains unquoted YAML special
    characters (colons, braces, etc.).  When that happens, fall back to a
    simple line-based parser that treats the first `key:` on each line as
    the key and everything after it as a raw string value.
    """
    stripped = block.strip()
    if not stripped:
        return {}

    # Try standard YAML first.
    try:
        parsed = yaml.safe_load(stripped)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fallback: line-based "key: value" or "key=value" extraction.
    # Handles continuation lines (indented lines without a key) by appending
    # them to the previous key's value.
    # Accepts both YAML-style (key: value) and Python kwarg-style (key=value).
    # For key=value, strips optional surrounding quotes from the value.
    result: Dict[str, Any] = {}
    current_key: str | None = None
    current_value_lines: List[str] = []

    for line in stripped.splitlines():
        m = re.match(r"^([A-Za-z_]\w*)\s*[:=]\s?(.*)", line)
        if m:
            # Flush previous key
            if current_key is not None:
                result[current_key] = "\n".join(current_value_lines).strip()
            current_key = m.group(1)
            current_value_lines = [m.group(2)]
        elif current_key is not None:
            current_value_lines.append(line)

    if current_key is not None:
        result[current_key] = "\n".join(current_value_lines).strip()

    # Strip matched surrounding quotes from values (handles key="value" style)
    for k, v in result.items():
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            result[k] = v[1:-1]

    if result:
        return result

    # Nothing matched — return as _raw.
    return {"_raw": stripped}


def parse_inline_tool_calls(text: str) -> List[InlineToolCall]:
    calls: List[InlineToolCall] = []
    for lang, block in extract_code_blocks_with_lang(text):
        if lang and re.match(r"^[A-Za-z_]\w*$", lang) and lang not in SHELL_BLOCK_LANGS:
            args = _parse_yaml_block(block)
            calls.append(InlineToolCall(name=lang, args=args, raw=block))
            continue
        single_call = _parse_single_call_from_block(block)
        if single_call:
            calls.append(single_call)
            continue
        try:
            parsed = yaml.safe_load(block)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            tool_name = parsed.get("tool") or parsed.get("name")
            args = parsed.get("arguments")
            if tool_name and isinstance(args, dict):
                calls.append(InlineToolCall(name=tool_name, args=args, raw=block))
                continue

        block_calls: List[InlineToolCall] = []
        try:
            block_calls = _parse_calls_via_ast(block)
        except Exception:
            block_calls = _parse_calls_via_regex(block)
        if block_calls:
            calls.extend(block_calls)
    return calls
