#!/usr/bin/env python3
"""
plan_validator.py - Structural validator for step-3 evolved YAML plans.

Given an original plan, an evolved plan, and the per-step digest (from
lean_report_loader.py), run 9 structural checks and emit a
`validation_report.json`. Exits 0 if all checks pass, 1 otherwise.

Checks:
  1. YAML parses (safe_load).
  2. Top-level-keys-identical  — all keys other than `workflow` byte-identical
     to the original, preserving config / parameters / submodules intact.
  3. Step-count match.
  4. Ordered step-names match.
  5. Confirmed steps byte-identical — if a digest entry has
     verdict == "confirmed", the evolved step's `instruction` is identical to
     the original's `instruction` (string equality).
  6. Falsified steps differ — if verdict != "confirmed", the evolved
     instruction is NOT byte-identical (a no-op rewrite counts as a bug).
  7. Templates preserved — every `{{var}}` substring in the original
     instruction is present in the evolved instruction (falsified steps).
  8. No audit-trail leakage — no instruction contains any forbidden
     substring (case-insensitive).
  9. Block-scalar style preserved — the line `instruction: |` (with the
     `|` indicator) remains for every step; the evolved file doesn't flip a
     `|` block into a folded `>` or a flow string.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


AUDIT_LEAKAGE_SUBSTRINGS = [
    "plan evolution",
    "re-roll",
    "layer 3",
    "layer3",
    "previously failed",
    "falsified",
    "concrete evidence from",
    "based on layer 3 analysis",
    "lean verdict",
    "tool verdict",
    "llm verdict",
]


def _safe_load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_LEAF_KEYS = ("task", "step")


def _step_key(plan: dict) -> list[dict]:
    return plan.get("workflow") or []


def _flatten_leaves(seq) -> list[tuple[str, str]]:
    """Recursively walk workflow and return [(name, instruction), ...] for every
    instruction-bearing leaf, in source order. Handles nesting inside
    for_each / while / if / switch / parallel."""
    out: list[tuple[str, str]] = []
    for item in (seq or []):
        if not isinstance(item, dict):
            continue
        for key, val in item.items():
            if key in _LEAF_KEYS:
                if isinstance(val, dict):
                    nm = val.get("name") or ""
                    instr = val.get("instruction") or ""
                    out.append((nm, instr))
            elif key in ("for_each", "while"):
                out.extend(_flatten_leaves((val or {}).get("steps") or []))
            elif key == "if":
                bv = val or {}
                for br in ("steps_true", "steps_false", "steps"):
                    out.extend(_flatten_leaves(bv.get(br) or []))
            elif key == "switch":
                sw = val or {}
                for case in (sw.get("cases") or []):
                    out.extend(_flatten_leaves((case or {}).get("steps") or []))
                out.extend(_flatten_leaves(
                    (sw.get("default") or {}).get("steps") or []))
            elif key == "parallel":
                for branch in ((val or {}).get("branches") or []):
                    out.extend(_flatten_leaves((branch or {}).get("steps") or []))
            break
    return out


def _extract_templates(text: str) -> list[str]:
    return re.findall(r"\{\{[^}]+\}\}", text)


def _find_instruction_lines(yaml_text: str) -> list[str]:
    """Return the `instruction: ...` line for each workflow step, in order."""
    out: list[str] = []
    in_workflow = False
    for line in yaml_text.splitlines():
        if not in_workflow:
            if re.match(r"^workflow:\s*$", line):
                in_workflow = True
            continue
        if line and not line[0].isspace() and line.strip():
            break  # left workflow: scope
        m = re.match(r"^\s+instruction:\s*(.*?)\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def validate(original: Path, evolved: Path, digest: Path, report: Path) -> bool:
    checks: list[dict] = []

    def _record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": ok, "detail": detail})

    # Check 1: YAML parses.
    try:
        evolved_plan = _safe_load(evolved)
        _record("yaml_parses", True, "")
    except Exception as e:
        _record("yaml_parses", False, f"{type(e).__name__}: {e}")
        _emit(report, checks, 0, 0)
        return False

    try:
        original_plan = _safe_load(original)
    except Exception as e:
        _record("original_parses", False, f"{type(e).__name__}: {e}")
        _emit(report, checks, 0, 0)
        return False

    try:
        digest_list = json.loads(digest.read_text(encoding="utf-8"))
    except Exception as e:
        _record("digest_parses", False, f"{type(e).__name__}: {e}")
        _emit(report, checks, 0, 0)
        return False

    # Check 2: top-level keys (other than workflow) byte-identical.
    top_keys_match_all = True
    skipped = {"workflow"}
    orig_keys = set(original_plan.keys()) - skipped
    evo_keys = set(evolved_plan.keys()) - skipped
    if orig_keys != evo_keys:
        top_keys_match_all = False
        _record("top_level_keys_match", False,
                f"keys differ: only_in_original={orig_keys - evo_keys}, "
                f"only_in_evolved={evo_keys - orig_keys}")
    else:
        for k in orig_keys:
            if original_plan[k] != evolved_plan[k]:
                top_keys_match_all = False
                _record("top_level_key_unchanged", False,
                        f"top-level key {k!r} modified")
        if top_keys_match_all:
            _record("top_level_keys_match", True, "")

    # Flatten both plans to [(name, instruction), ...] in source order.
    # Handles nesting inside for_each/while/if/switch/parallel.
    orig_leaves = _flatten_leaves(_step_key(original_plan))
    evo_leaves = _flatten_leaves(_step_key(evolved_plan))

    # Check 3: leaf count match.
    if len(orig_leaves) != len(evo_leaves):
        _record("step_count_match", False,
                f"original={len(orig_leaves)} evolved={len(evo_leaves)}")
        _emit(report, checks, 0, 0)
        return False
    _record("step_count_match", True, f"{len(orig_leaves)} leaf step(s)")

    # Check 4: ordered leaf names match.
    orig_names = [n for n, _ in orig_leaves]
    evo_names = [n for n, _ in evo_leaves]
    if orig_names != evo_names:
        _record("step_names_match", False,
                f"original={orig_names} evolved={evo_names}")
    else:
        _record("step_names_match", True, ",".join(orig_names))

    orig_instr_by_name = dict(orig_leaves)
    evo_instr_by_name = dict(evo_leaves)

    # Digest lookup by name (fall back to step_index -> orig_names[i]).
    by_name: dict[str, dict] = {}
    for rec in digest_list:
        nm = rec.get("step_name")
        if nm:
            by_name[nm] = rec
        idx = rec.get("step_index")
        if nm is None and isinstance(idx, int) and 0 <= idx < len(orig_names):
            by_name[orig_names[idx]] = rec

    falsified_rewritten = 0
    confirmed_preserved = 0

    # Check 5 & 6: per-leaf content rules (confirmed byte-identical; falsified differs).
    for i, name in enumerate(orig_names):
        rec = by_name.get(name) or {}
        verdict = rec.get("verdict") or "uncertain"
        orig_instr = orig_instr_by_name.get(name, "")
        evo_instr = evo_instr_by_name.get(name, "")
        if verdict == "confirmed":
            if orig_instr == evo_instr:
                confirmed_preserved += 1
                _record(f"confirmed_step_byte_identical[{i}:{name}]", True, "")
            else:
                _record(f"confirmed_step_byte_identical[{i}:{name}]", False,
                        f"confirmed step modified (orig_len={len(orig_instr)} "
                        f"evo_len={len(evo_instr)})")
        else:
            if orig_instr == evo_instr:
                _record(f"falsified_step_differs[{i}:{name}]", False,
                        "step marked falsified/uncertain but instruction unchanged")
            else:
                falsified_rewritten += 1
                _record(f"falsified_step_differs[{i}:{name}]", True,
                        f"rewrote (orig_len={len(orig_instr)} evo_len={len(evo_instr)})")

    # Check 7: template preservation on modified leaves.
    for i, name in enumerate(orig_names):
        rec = by_name.get(name) or {}
        if (rec.get("verdict") or "uncertain") == "confirmed":
            continue
        orig_instr = orig_instr_by_name.get(name, "")
        evo_instr = evo_instr_by_name.get(name, "")
        orig_templates = _extract_templates(orig_instr)
        missing = [t for t in orig_templates if t not in evo_instr]
        if missing:
            _record(f"templates_preserved[{i}:{name}]", False,
                    f"missing templates: {missing}")
        else:
            _record(f"templates_preserved[{i}:{name}]", True,
                    f"{len(orig_templates)} template(s) preserved")

    # Check 8: no audit-trail leakage (all leaves).
    for i, name in enumerate(orig_names):
        evo_instr = evo_instr_by_name.get(name, "").lower()
        orig_instr = orig_instr_by_name.get(name, "").lower()
        hits = [s for s in AUDIT_LEAKAGE_SUBSTRINGS if s in evo_instr]
        new_hits = [s for s in hits if s not in orig_instr]
        if new_hits:
            _record(f"no_audit_leakage[{i}:{name}]", False,
                    f"new forbidden substrings: {new_hits}")
        else:
            _record(f"no_audit_leakage[{i}:{name}]", True, "")

    # Check 9: block-scalar style preserved (instruction: | on every step).
    evolved_text = evolved.read_text(encoding="utf-8")
    instr_indicators = _find_instruction_lines(evolved_text)
    bad = [ind for ind in instr_indicators if not ind.startswith("|")]
    if bad:
        _record("block_scalar_preserved", False,
                f"non-block indicators on instruction: {bad}")
    else:
        _record("block_scalar_preserved", True,
                f"{len(instr_indicators)} instruction blocks keep `|`")

    passed_all = all(c["pass"] for c in checks)
    _emit(report, checks, falsified_rewritten, confirmed_preserved,
          passed_all=passed_all)
    return passed_all


def _emit(report_path: Path, checks: list[dict],
          falsified_rewritten: int, confirmed_preserved: int,
          passed_all: bool | None = None) -> None:
    if passed_all is None:
        passed_all = all(c["pass"] for c in checks)
    payload = {
        "checks": checks,
        "summary": {
            "pass": passed_all,
            "falsified_rewritten": falsified_rewritten,
            "confirmed_preserved": confirmed_preserved,
            "total_checks": len(checks),
            "failing_checks": sum(1 for c in checks if not c["pass"]),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an evolved YAML plan against the original.")
    parser.add_argument("--original", required=True)
    parser.add_argument("--evolved", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    ok = validate(Path(args.original), Path(args.evolved),
                  Path(args.digest), Path(args.report))
    print(f"{'OK' if ok else 'FAIL'}: validation_report -> {args.report}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
