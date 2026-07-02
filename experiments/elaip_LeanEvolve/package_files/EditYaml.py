#!/usr/bin/env python3
"""
EditYaml.py - Surgical YAML instruction-block editor.

Supports reading and replacing an `instruction:` block anywhere in a task plan
YAML tree, including leaves nested inside control-flow nodes:
  task / step (leaves with name + instruction)
  for_each.steps[] / while.steps[] / if.steps_true[] / if.steps_false[] /
  switch.cases[].steps[] / switch.default.steps[] / parallel.branches[].steps[]

Instruction-bearing leaves are located by their `name:` field, which must be
unique within the workflow. Edits are byte-surgical on the block-scalar lines
so every unchanged region of the file round-trips identically.

CLI:

  # Read step "fix_issue"'s instruction (raw text, no YAML quoting)
  python EditYaml.py --yaml_path plan.yaml --get-by-name fix_issue

  # Replace it (VALUE is a JSON-encoded string)
  python EditYaml.py --yaml_path plan.yaml --set-by-name fix_issue \
      '"New instruction\nwith templates {{regression_test_cmd}}\n"'

  # Legacy path-based API (top-level task/step only, kept for back-compat)
  python EditYaml.py --yaml_path plan.yaml \
      --path '["workflow", 2, "task", "instruction"]' --get
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Optional


# Leaf step types that carry `name:` + `instruction:`.
_LEAF_KEYS = ("task", "step")

# Control-flow node keys and how to recurse into their children.
#   key -> list of (child_attr, is_required).
# If a control-flow key isn't listed here, the walker leaves it alone (no
# recursion, no edit).
_CONTROL_FLOW_CHILDREN: dict[str, list[str]] = {
    "for_each":  ["steps"],
    "while":     ["steps"],
    "if":        ["steps_true", "steps_false", "steps"],
    "switch":    [],   # handled specially below (cases + default)
    "parallel":  [],   # handled specially below (branches)
}


def _iter_steps(seq: Iterable) -> Iterable[dict]:
    """Yield every dict in a list, ignoring non-dict entries."""
    for s in (seq or []):
        if isinstance(s, dict):
            yield s


def _walk_for_name(seq: Iterable, target_name: str,
                   ancestor_types: tuple[str, ...] = ()) -> Optional[dict]:
    """Recursively find the leaf step (task/step) with `name == target_name`
    anywhere in the workflow tree. Returns the leaf-inner mapping (the dict
    under the `task:` / `step:` key) — NOT the outer wrapper. Returns None if
    not found."""
    for item in _iter_steps(seq):
        # Workflow items are single-key dicts, e.g. {"task": {...}}.
        for key, val in item.items():
            if key in _LEAF_KEYS:
                if isinstance(val, dict) and val.get("name") == target_name:
                    return val
            elif key in ("for_each", "while"):
                res = _walk_for_name(
                    (val or {}).get("steps") or [], target_name,
                    ancestor_types + (key,))
                if res is not None:
                    return res
            elif key == "if":
                branch_val = val or {}
                for br in ("steps_true", "steps_false", "steps"):
                    res = _walk_for_name(branch_val.get(br) or [], target_name,
                                          ancestor_types + (key,))
                    if res is not None:
                        return res
            elif key == "switch":
                sw = val or {}
                for case in (sw.get("cases") or []):
                    res = _walk_for_name(
                        (case or {}).get("steps") or [], target_name,
                        ancestor_types + (key,))
                    if res is not None:
                        return res
                default = sw.get("default") or {}
                res = _walk_for_name(default.get("steps") or [], target_name,
                                      ancestor_types + (key,))
                if res is not None:
                    return res
            elif key == "parallel":
                for branch in ((val or {}).get("branches") or []):
                    res = _walk_for_name(
                        (branch or {}).get("steps") or [], target_name,
                        ancestor_types + (key,))
                    if res is not None:
                        return res
            break  # only one key per workflow-item wrapper
    return None


def _collect_leaf_names(seq: Iterable) -> list[str]:
    """Flatten the workflow tree into the list of leaf names, in source order."""
    out: list[str] = []
    for item in _iter_steps(seq):
        for key, val in item.items():
            if key in _LEAF_KEYS:
                if isinstance(val, dict) and val.get("name"):
                    out.append(val["name"])
            elif key in ("for_each", "while"):
                out.extend(_collect_leaf_names((val or {}).get("steps") or []))
            elif key == "if":
                bv = val or {}
                for br in ("steps_true", "steps_false", "steps"):
                    out.extend(_collect_leaf_names(bv.get(br) or []))
            elif key == "switch":
                sw = val or {}
                for case in (sw.get("cases") or []):
                    out.extend(_collect_leaf_names((case or {}).get("steps") or []))
                out.extend(_collect_leaf_names(
                    (sw.get("default") or {}).get("steps") or []))
            elif key == "parallel":
                for branch in ((val or {}).get("branches") or []):
                    out.extend(_collect_leaf_names((branch or {}).get("steps") or []))
            break
    return out


# --------------------------------------------------------------------------
# Text-level locators: given a named leaf, find its block-scalar range in the
# raw file text so we can do a surgical replace without triggering ruamel's
# global reflow of untouched regions.
# --------------------------------------------------------------------------

def _find_name_line(lines: list[str], target_name: str) -> int:
    """Return the 0-based index of the `name: <target_name>` line in the
    workflow section. The `name:` key can appear at any nesting level — we
    match on the VALUE, trusting that leaf node names are unique within a
    plan (which is required by Layer 2 anyway)."""
    # Match both quoted and unquoted forms.
    q = re.escape(target_name)
    pat = re.compile(rf"^(\s+)name:\s*(?:\"{q}\"|'{q}'|{q})\s*$")
    in_workflow = False
    for i, line in enumerate(lines):
        if not in_workflow:
            if re.match(r"^workflow:\s*$", line):
                in_workflow = True
            continue
        if line and not line[0].isspace() and line.strip():
            break  # left workflow scope
        if pat.match(line):
            return i
    raise KeyError(f"node named {target_name!r} not found in workflow")


def _find_sibling_instruction_line(lines: list[str], name_line: int) -> int:
    """After a `name:` line at a given indent, find the sibling `instruction:`
    line at the SAME indent within the same mapping. The leaf mapping ends
    when we hit a line at shallower indent (typically the next `- task:` /
    `- step:` marker or end-of-workflow)."""
    m = re.match(r"^(\s+)name:", lines[name_line])
    if m is None:
        raise ValueError(f"line {name_line+1} is not a name: line")
    indent = len(m.group(1))
    key_re = re.compile(rf"^\s{{{indent}}}instruction:\s*(\|[-+]?|>[-+]?)?\s*$")
    # Scan forward; stop at shallower-indent non-blank line.
    for j in range(name_line + 1, len(lines)):
        raw = lines[j].rstrip("\n").rstrip("\r")
        stripped = raw.lstrip(" ")
        if stripped == "":
            continue
        leading = len(raw) - len(stripped)
        if leading < indent:
            break
        if key_re.match(lines[j]):
            return j
    # Also check lines BEFORE name (rare — instruction above name).
    for j in range(name_line - 1, -1, -1):
        raw = lines[j].rstrip("\n").rstrip("\r")
        stripped = raw.lstrip(" ")
        if stripped == "":
            continue
        leading = len(raw) - len(stripped)
        if leading < indent:
            break
        if key_re.match(lines[j]):
            return j
    raise KeyError(
        f"sibling `instruction:` not found for name: on line {name_line+1}")


def _block_scalar_range(lines: list[str], instr_line: int
                        ) -> tuple[int, int, int, int]:
    """For `instruction: |` at lines[instr_line], return
      (key_indent, block_content_indent, content_start_line, content_end_line_exclusive)."""
    m = re.match(r"^(\s*)instruction:\s*(\|[-+]?|>[-+]?)\s*$", lines[instr_line])
    if not m:
        raise ValueError(f"line {instr_line + 1} is not an `instruction: |` line")
    key_indent = len(m.group(1))

    content_start = instr_line + 1
    last_non_blank_end = content_start
    content_indent: int | None = None

    i = content_start
    while i < len(lines):
        raw = lines[i].rstrip("\n").rstrip("\r")
        stripped = raw.lstrip(" ")
        leading = len(raw) - len(stripped)
        is_blank = stripped == ""
        if is_blank:
            i += 1
            continue
        if leading > key_indent:
            if content_indent is None:
                content_indent = leading
            i += 1
            last_non_blank_end = i
        else:
            break
    content_end = last_non_blank_end
    if content_indent is None:
        content_indent = key_indent + 4
    return key_indent, content_indent, content_start, content_end


def _render_block(new_content: str, content_indent: int) -> list[str]:
    """Render a multi-line string as block-scalar content lines at the target
    column indent. Blank lines stay blank. The result ends with the customary
    trailing newline."""
    pad = " " * content_indent
    parts = new_content.split("\n")
    out: list[str] = []
    for seg in parts:
        if seg == "":
            out.append("\n")
        else:
            out.append(pad + seg + "\n")
    # Drop accidental doubled blank line produced by a trailing '\n'.
    while len(out) > 1 and out[-1] == "\n" and out[-2] == "\n":
        out.pop()
    return out


def surgical_get_by_name(yaml_path: Path, node_name: str) -> str:
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    name_line = _find_name_line(lines, node_name)
    instr_line = _find_sibling_instruction_line(lines, name_line)
    _, content_indent, cstart, cend = _block_scalar_range(lines, instr_line)
    out_lines: list[str] = []
    pad = " " * content_indent
    for raw in lines[cstart:cend]:
        s = raw.rstrip("\n").rstrip("\r")
        if s == "":
            out_lines.append("")
        elif s.startswith(pad):
            out_lines.append(s[content_indent:])
        else:
            out_lines.append(s.lstrip(" "))
    return "\n".join(out_lines) + "\n"


def surgical_set_by_name(yaml_path: Path, node_name: str,
                         new_content: str) -> None:
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    name_line = _find_name_line(lines, node_name)
    instr_line = _find_sibling_instruction_line(lines, name_line)
    _, content_indent, cstart, cend = _block_scalar_range(lines, instr_line)
    rendered = _render_block(new_content, content_indent)
    new_lines = lines[:cstart] + rendered + lines[cend:]
    yaml_path.write_text("".join(new_lines), encoding="utf-8")


def leaf_names(yaml_path: Path) -> list[str]:
    """Public helper: flatten every instruction-bearing leaf in the workflow
    tree, in source order. Used by plan_validator.py."""
    from ruamel.yaml import YAML
    y = YAML(typ="rt")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = y.load(f)
    return _collect_leaf_names((data or {}).get("workflow") or [])


# --------------------------------------------------------------------------
# Legacy path-based API (top-level task/step, back-compat for earlier callers)
# --------------------------------------------------------------------------
_TASK_LINE_RE = re.compile(r"^(\s+)- (?:task|step):\s*$")


def _find_task_block_start(lines: list[str], step_index: int) -> int:
    seen = 0
    in_workflow = False
    first_indent: int | None = None
    for i, line in enumerate(lines):
        if not in_workflow:
            if re.match(r"^workflow:\s*$", line):
                in_workflow = True
            continue
        if line.strip() and not line.startswith(" "):
            raise IndexError(
                f"step {step_index} not found: only {seen} workflow items before end of workflow block")
        m = _TASK_LINE_RE.match(line)
        if not m:
            continue
        ind = len(m.group(1))
        if first_indent is None:
            first_indent = ind
        if ind != first_indent:
            continue
        if seen == step_index:
            return i
        seen += 1
    raise IndexError(
        f"step {step_index} not found: only {seen} top-level task items")


def _find_field_line_in_task(lines: list[str], task_start: int, field: str,
                             task_item_indent: int) -> int:
    key_re = re.compile(rf"^(\s+){re.escape(field)}:\s*")
    for i in range(task_start + 1, len(lines)):
        m = _TASK_LINE_RE.match(lines[i])
        if m and len(m.group(1)) <= task_item_indent:
            break
        if lines[i] and not lines[i][0].isspace() and lines[i].strip():
            break
        km = key_re.match(lines[i])
        if km and len(km.group(1)) > task_item_indent:
            return i
    raise KeyError(f"{field!r} not found in task starting at line {task_start+1}")


def _extract_name_line_value(line: str) -> str:
    m = re.match(r"^\s+name:\s*(.*?)\s*$", line)
    if not m:
        return line.strip()
    val = m.group(1)
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return val


def surgical_set_instruction(yaml_path: Path, step_index: int,
                             new_content: str) -> None:
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    ts = _find_task_block_start(lines, step_index)
    m = _TASK_LINE_RE.match(lines[ts])
    ti = len(m.group(1))
    instr = _find_field_line_in_task(lines, ts, "instruction", ti)
    _, cind, cs, ce = _block_scalar_range(lines, instr)
    rendered = _render_block(new_content, cind)
    yaml_path.write_text("".join(lines[:cs] + rendered + lines[ce:]),
                         encoding="utf-8")


def surgical_get_instruction(yaml_path: Path, step_index: int) -> str:
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    ts = _find_task_block_start(lines, step_index)
    m = _TASK_LINE_RE.match(lines[ts])
    ti = len(m.group(1))
    instr = _find_field_line_in_task(lines, ts, "instruction", ti)
    _, cind, cs, ce = _block_scalar_range(lines, instr)
    pad = " " * cind
    out: list[str] = []
    for raw in lines[cs:ce]:
        s = raw.rstrip("\n").rstrip("\r")
        if s == "":
            out.append("")
        elif s.startswith(pad):
            out.append(s[cind:])
        else:
            out.append(s.lstrip(" "))
    return "\n".join(out) + "\n"


def surgical_get_name(yaml_path: Path, step_index: int) -> str:
    text = yaml_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    ts = _find_task_block_start(lines, step_index)
    m = _TASK_LINE_RE.match(lines[ts])
    ti = len(m.group(1))
    name_line = _find_field_line_in_task(lines, ts, "name", ti)
    return _extract_name_line_value(lines[name_line])


def _parse_legacy_instruction_path(keys: list) -> int | None:
    if (len(keys) == 4 and keys[0] == "workflow" and isinstance(keys[1], int)
            and keys[2] in _LEAF_KEYS and keys[3] == "instruction"):
        return keys[1]
    return None


def _parse_legacy_name_path(keys: list) -> int | None:
    if (len(keys) == 4 and keys[0] == "workflow" and isinstance(keys[1], int)
            and keys[2] in _LEAF_KEYS and keys[3] == "name"):
        return keys[1]
    return None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(
        description="Surgically read or replace an `instruction:` block in a plan YAML.")
    p.add_argument("--yaml_path", required=True, help="Path to the YAML file")

    # Either name-based (recommended) or legacy path-based lookup.
    p.add_argument("--path", default="",
                   help="(Legacy) JSON array of keys, e.g. "
                        "'[\"workflow\", 2, \"task\", \"instruction\"]'. "
                        "Top-level task/step only.")
    p.add_argument("--by-name", default="",
                   help="Leaf step's `name:` to address (works for tasks "
                        "nested inside for_each/while/if/switch/parallel).")

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--get", action="store_true",
                   help="Print the instruction text (with --path or --by-name).")
    g.add_argument("--set", metavar="VALUE",
                   help="Replace the instruction (VALUE is a JSON-encoded string).")
    g.add_argument("--get-by-name", metavar="NAME",
                   help="Shortcut: print the instruction for leaf NAME.")
    g.add_argument("--set-by-name", nargs=2, metavar=("NAME", "VALUE"),
                   help="Shortcut: replace the instruction for leaf NAME. "
                        "VALUE is a JSON-encoded string.")
    g.add_argument("--list-leaf-names", action="store_true",
                   help="Print every instruction-bearing leaf name (one per line).")
    args = p.parse_args()

    yp = Path(args.yaml_path)
    if not yp.exists():
        print(f"Error: {yp} not found", file=sys.stderr)
        return 1

    try:
        if args.list_leaf_names:
            for n in leaf_names(yp):
                print(n)
            return 0

        if args.get_by_name:
            sys.stdout.write(surgical_get_by_name(yp, args.get_by_name))
            return 0

        if args.set_by_name:
            name, raw = args.set_by_name
            # Try the canonical path first: VALUE is a JSON-encoded string.
            # Fall back to treating VALUE as a plain string with literal `\n`
            # / `\"` escapes — Qwen / Gemma routinely emit double-quoted-but-
            # not-JSON-encoded args (`"line1\nline2"` in shell strips the
            # outer quotes before json.loads sees it, leaving an unparseable
            # bare string). The fallback unescapes manually so the rewrite
            # still lands instead of burning N retry round-trips.
            new_val = None
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, str):
                    new_val = decoded
            except json.JSONDecodeError:
                pass
            if new_val is None:
                # Plain-string fallback: unescape the common backslash forms.
                # Order matters: `\\` first so we don't double-process.
                new_val = (raw
                           .replace('\\\\', '\x00')
                           .replace('\\n', '\n')
                           .replace('\\t', '\t')
                           .replace('\\"', '"')
                           .replace("\\'", "'")
                           .replace('\x00', '\\'))
                print(f"Warning: --set-by-name VALUE was not JSON-encoded; "
                      f"interpreted as plain string with backslash unescapes.",
                      file=sys.stderr)
            surgical_set_by_name(yp, name, new_val)
            print(f"OK: {yp} updated (instruction for {name!r}).")
            return 0

        # --path-based flow (legacy, top-level only)
        if not args.path:
            print("Error: pass either --by-name/--get-by-name/--set-by-name or --path",
                  file=sys.stderr)
            return 1
        try:
            keys = json.loads(args.path)
        except json.JSONDecodeError as e:
            print(f"Error: --path must be valid JSON: {e}", file=sys.stderr)
            return 1
        if not isinstance(keys, list):
            print("Error: --path must be a JSON array", file=sys.stderr)
            return 1

        if args.get:
            if args.by_name:
                sys.stdout.write(surgical_get_by_name(yp, args.by_name))
                return 0
            idx = _parse_legacy_instruction_path(keys)
            if idx is not None:
                sys.stdout.write(surgical_get_instruction(yp, idx))
                return 0
            idx = _parse_legacy_name_path(keys)
            if idx is not None:
                print(surgical_get_name(yp, idx))
                return 0
            print(f"Error: unsupported --path {keys}", file=sys.stderr)
            return 1

        if args.set is not None:
            try:
                new_val = json.loads(args.set)
            except json.JSONDecodeError as e:
                print(f"Error: --set VALUE must be valid JSON: {e}", file=sys.stderr)
                return 1
            if not isinstance(new_val, str):
                print("Error: VALUE must decode to a JSON string.", file=sys.stderr)
                return 1
            if args.by_name:
                surgical_set_by_name(yp, args.by_name, new_val)
                print(f"OK: {yp} updated (instruction for {args.by_name!r}).")
                return 0
            idx = _parse_legacy_instruction_path(keys)
            if idx is not None:
                surgical_set_instruction(yp, idx, new_val)
                print(f"OK: {yp} updated (instruction[{idx}]).")
                return 0
            print("Error: --set supports --by-name or --path targeting an "
                  "instruction block.", file=sys.stderr)
            return 1

    except (KeyError, IndexError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
