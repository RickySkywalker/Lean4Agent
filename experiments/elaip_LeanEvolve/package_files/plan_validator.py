#!/usr/bin/env python3
"""
plan_validator.py — ELAIP-Bench evolved-YAML structural validator.

Lighter than the SWE version (no audit-trail forensic checks). Enforces:

  10 no_answer_letter_leakage  — no "answer is X" / "correct option B" patterns
  11 no_eval_signal_leakage    — no is_correct / parsed_answer / etc. substrings
  12 templates_preserved       — every {{template}} from the original step's
                                 instruction is present in the rewritten one
  13 step_names_match          — workflow tree's step names byte-identical
  14 length_within_bounds      — rewritten instruction length within ±50% of original

Returns a dict per step describing pass/fail; callers run a single repair
attempt by reverting failing steps to byte-identical-with-original.

CLI:
  python plan_validator.py \\
      --working <evolved>.yaml \\
      --original <original>.yaml \\
      --report   <validation_report.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ANSWER_LETTER_RE = re.compile(
    # Trailing \b after the alternation prevents prefix matches: without it,
    # "reference" matches inside "referenced" because there's no word
    # boundary between "e" and "d", so the trailing "d" satisfies [A-D]
    # under IGNORECASE — false positive observed in
    # locate_keyword_passages, where "is clearly referenced" innocuously
    # appears in the original plan.
    r"\b(?:correct|right|true|expected|answer\s+is|reference)\b\W{0,5}(?:option\s*)?[A-D]\b",
    re.IGNORECASE,
)
EVAL_SIGNAL_FORBIDDEN = [
    "is_correct", "parsed_answer", "correct_answer", "ground truth",
    "was wrong", "previously incorrect", "Lean said", "predicate failed",
    "trajectory said", "audit trail", "originally failed",
]
TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


# Leaf step kinds recognised across the ELAIP / SWE plan grammars. Used by
# helpers like seed_digest.py that need a flat (name, instruction) list to
# seed amendments_digest.json.
_LEAF_KEYS = ("task", "step")


def _flatten_leaves(seq) -> list[tuple[str, str]]:
    """Recursively walk a workflow and return [(name, instruction), ...] for
    every instruction-bearing leaf, in source order. Handles nesting inside
    for_each / while / if / switch / parallel. Mirrors the SWE
    plan_validator helper of the same name so the shared seed_digest.py /
    apply_amendments.py utilities work unchanged."""
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
                # ELAIP uses then/else; SWE uses steps_true/steps_false;
                # also accept generic `steps`.
                for br in ("then", "else", "steps_true", "steps_false", "steps"):
                    out.extend(_flatten_leaves(bv.get(br) or []))
            elif key == "switch":
                sw = val or {}
                cases = sw.get("cases") or {}
                if isinstance(cases, dict):
                    for case_steps in cases.values():
                        out.extend(_flatten_leaves(case_steps or []))
                elif isinstance(cases, list):
                    for case in cases:
                        out.extend(_flatten_leaves((case or {}).get("steps") or []))
                default = sw.get("default")
                if isinstance(default, list):
                    out.extend(_flatten_leaves(default))
                elif isinstance(default, dict):
                    out.extend(_flatten_leaves(default.get("steps") or []))
            elif key == "parallel":
                for branch in ((val or {}).get("branches") or []):
                    out.extend(_flatten_leaves((branch or {}).get("steps") or []))
            elif key == "discover":
                if isinstance(val, dict):
                    nm = val.get("name") or ""
                    instr = val.get("instruction") or ""
                    if nm or instr:
                        out.append((nm, instr))
            break
    return out


def collect_steps(workflow_node: list[Any] | None,
                  branch_path: list[str] | None = None,
                  out: list[dict] | None = None) -> list[dict]:
    """Walk a YAML `workflow:` block and return a flat list of step dicts.
    Each entry: {name, instruction, save_as, branch_path, anchor_path}.
    `anchor_path` is a JSON-pointer-style path that EditYaml.py uses to
    rewrite the instruction in-place; we only need it for diagnostics."""
    if out is None:
        out = []
    if branch_path is None:
        branch_path = []
    if workflow_node is None:
        return out
    for entry in workflow_node:
        if not isinstance(entry, dict):
            continue
        if "step" in entry or "task" in entry:
            kind = "step" if "step" in entry else "task"
            body = entry.get(kind) or {}
            out.append({
                "name": body.get("name", "<anon>"),
                "kind": kind,
                "instruction": body.get("instruction", "") or "",
                "save_as": body.get("save_as"),
                "branch_path": list(branch_path),
            })
        elif "for_each" in entry:
            collect_steps(entry["for_each"].get("steps"),
                          branch_path + [f"for_each:{entry['for_each'].get('variable', '?')}"],
                          out)
        elif "while" in entry:
            collect_steps(entry["while"].get("steps"),
                          branch_path + ["while"],
                          out)
        elif "if" in entry:
            collect_steps(entry["if"].get("then") or [], branch_path + ["if:then"], out)
            collect_steps(entry["if"].get("else") or [], branch_path + ["if:else"], out)
        elif "switch" in entry:
            for case_name, case_steps in (entry["switch"].get("cases") or {}).items():
                collect_steps(case_steps or [], branch_path + [f"switch:{case_name}"], out)
            collect_steps(entry["switch"].get("default") or [], branch_path + ["switch:default"], out)
        elif "discover" in entry:
            body = entry["discover"]
            out.append({
                "name": body.get("name", "<anon-discover>"),
                "kind": "discover",
                "instruction": body.get("instruction", "") or "",
                "save_as": body.get("name"),
                "branch_path": list(branch_path),
            })
        elif "synthesize" in entry:
            body = entry["synthesize"]
            out.append({
                "name": body.get("name", "<anon-synth>"),
                "kind": "synthesize",
                "instruction": body.get("instruction", "") or "",
                "save_as": body.get("save_as"),
                "branch_path": list(branch_path),
            })
        # set_variable / increment have no instruction — skip
    return out


def step_key(step: dict) -> str:
    """Stable key combining name + branch_path. Two steps with the same
    name in different branches are treated separately."""
    return step["name"] + "::" + "/".join(step.get("branch_path") or [])


def validate_step(orig: dict, evol: dict) -> dict:
    """Return a dict of {check_name: (passed, detail)} for one step."""
    checks: dict[str, tuple[bool, str]] = {}

    if orig.get("name") != evol.get("name"):
        checks["step_names_match"] = (False, f"name changed: {orig.get('name')} -> {evol.get('name')}")
    else:
        checks["step_names_match"] = (True, "")

    orig_instr = orig.get("instruction", "") or ""
    evol_instr = evol.get("instruction", "") or ""

    # length_within_bounds: ±50% (looser than SWE's ±30%)
    olen = max(1, len(orig_instr))
    elen = len(evol_instr)
    ratio = elen / olen
    if 0.5 <= ratio <= 1.5:
        checks["length_within_bounds"] = (True, f"ratio={ratio:.2f}")
    else:
        checks["length_within_bounds"] = (False, f"length ratio {ratio:.2f} out of ±50%")

    # templates_preserved: every {{template}} from original must appear in evolved
    orig_templates = TEMPLATE_RE.findall(orig_instr)
    missing = [t for t in orig_templates if "{{" + t.strip() + "}}" not in evol_instr
               and "{{ " + t.strip() + " }}" not in evol_instr]
    if missing:
        checks["templates_preserved"] = (False, f"missing templates: {missing}")
    else:
        checks["templates_preserved"] = (True, f"{len(orig_templates)} templates preserved")

    # no_answer_letter_leakage
    m = ANSWER_LETTER_RE.search(evol_instr)
    if m:
        checks["no_answer_letter_leakage"] = (False, f"matched: {m.group(0)!r}")
    else:
        checks["no_answer_letter_leakage"] = (True, "")

    # no_eval_signal_leakage
    leaked = [s for s in EVAL_SIGNAL_FORBIDDEN if s.lower() in evol_instr.lower()]
    if leaked:
        checks["no_eval_signal_leakage"] = (False, f"leaked tokens: {leaked}")
    else:
        checks["no_eval_signal_leakage"] = (True, "")

    return checks


# Checks 11 and 12 are content checks that should trigger reversion.
# Length (14) is informational only.
HARD_CHECKS = {
    "step_names_match",
    "templates_preserved",
    "no_answer_letter_leakage",
    "no_eval_signal_leakage",
}


def _digest_alignment_checks(digest: list[dict],
                              orig_steps: list[dict],
                              evol_steps: list[dict]) -> tuple[list[dict], int, int]:
    """For each digest entry, produce a SWE-style alignment check:
      - confirmed steps MUST be byte-identical in evolved YAML
      - falsified steps SHOULD differ from the original
    Returns (per_check_results, n_falsified_rewritten, n_confirmed_preserved)."""
    results: list[dict] = []
    orig_by_name = {s["name"]: s for s in orig_steps}
    evol_by_name = {s["name"]: s for s in evol_steps}
    n_falsified_rewritten = 0
    n_confirmed_preserved = 0
    for d in digest:
        name = d.get("step_name")
        verdict = d.get("verdict") or "uncertain"
        idx = d.get("step_index")
        o = orig_by_name.get(name)
        e = evol_by_name.get(name)
        if not o or not e:
            results.append({
                "check": f"step_present[{idx}:{name}]",
                "pass": False,
                "detail": "step missing in original or evolved YAML",
            })
            continue
        same = (o.get("instruction", "") == e.get("instruction", ""))
        if verdict == "confirmed":
            ck = {
                "check": f"confirmed_unchanged[{idx}:{name}]",
                "pass": same,
                "detail": "" if same else "confirmed step's instruction was modified",
            }
            results.append(ck)
            if same:
                n_confirmed_preserved += 1
        else:
            ck = {
                "check": f"falsified_step_differs[{idx}:{name}]",
                "pass": not same,
                "detail": "" if not same else "falsified step's instruction was not rewritten",
            }
            results.append(ck)
            if not same:
                n_falsified_rewritten += 1
    return results, n_falsified_rewritten, n_confirmed_preserved


def validate_plan(working_yaml: Path, original_yaml: Path,
                  digest_path: Path | None = None) -> dict:
    orig = yaml.safe_load(original_yaml.read_text(encoding="utf-8")) or {}
    evol = yaml.safe_load(working_yaml.read_text(encoding="utf-8")) or {}
    orig_steps = collect_steps(orig.get("workflow"))
    evol_steps = collect_steps(evol.get("workflow"))

    # Match by step_key.
    orig_by_key = {step_key(s): s for s in orig_steps}
    evol_by_key = {step_key(s): s for s in evol_steps}

    per_step: list[dict] = []
    overall_pass = True
    hard_failures: list[str] = []
    for k in orig_by_key.keys():
        if k not in evol_by_key:
            per_step.append({
                "step_key": k,
                "checks": {"step_names_match": [False, "step missing in evolved YAML"]},
                "passed": False,
            })
            overall_pass = False
            hard_failures.append(k)
            continue
        cks = validate_step(orig_by_key[k], evol_by_key[k])
        flat = {n: [v[0], v[1]] for n, v in cks.items()}
        passed = all(v[0] for n, v in cks.items() if n in HARD_CHECKS)
        per_step.append({
            "step_key": k,
            "name": orig_by_key[k]["name"],
            "branch_path": orig_by_key[k].get("branch_path"),
            "checks": flat,
            "passed": passed,
        })
        if not passed:
            overall_pass = False
            hard_failures.append(k)

    # Top-level keys byte-identical?
    structural = {}
    for top_key in ("name", "goal", "system_prompt", "config", "parameters"):
        if json.dumps(orig.get(top_key), sort_keys=True) != json.dumps(evol.get(top_key), sort_keys=True):
            structural[top_key] = "differs from original"
            overall_pass = False

    # SWE-style flat checks list (so the recovery protocol R1 can grep for
    # `falsified_step_differs[`, `templates_preserved[`, etc.).
    flat_checks: list[dict] = []
    for s in per_step:
        idx_raw = s.get("step_key", "").split("::")[0]
        for check_name, info in (s.get("checks") or {}).items():
            ok = bool(info[0]) if isinstance(info, (list, tuple)) and len(info) >= 1 else False
            detail = info[1] if isinstance(info, (list, tuple)) and len(info) >= 2 else ""
            flat_checks.append({
                "check": f"{check_name}[{s.get('step_key', '?')}]",
                "pass": ok,
                "detail": detail,
            })

    n_falsified_rewritten = 0
    n_confirmed_preserved = 0
    if digest_path and digest_path.exists():
        try:
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            align, n_falsified_rewritten, n_confirmed_preserved = (
                _digest_alignment_checks(digest, orig_steps, evol_steps))
            flat_checks.extend(align)
            if any(not c.get("pass") for c in align):
                overall_pass = False
        except Exception as e:
            flat_checks.append({"check": "digest_load",
                                 "pass": False, "detail": f"load error: {e}"})
            overall_pass = False

    failing_checks = [c["check"] for c in flat_checks if not c.get("pass")]
    return {
        "summary": {
            "pass": overall_pass,
            "hard_failures": hard_failures,
            "structural_differences": structural,
            "falsified_rewritten": n_falsified_rewritten,
            "confirmed_preserved": n_confirmed_preserved,
            "failing_checks": failing_checks,
        },
        "checks": flat_checks,
        "per_step": per_step,
    }


def repair_failing_steps(report: dict, working_yaml: Path,
                         original_yaml: Path) -> int:
    """Revert any step whose `passed=False` to byte-identical-with-original.
    Returns the number of steps reverted."""
    orig = yaml.safe_load(original_yaml.read_text(encoding="utf-8")) or {}
    evol = yaml.safe_load(working_yaml.read_text(encoding="utf-8")) or {}
    orig_steps = {step_key(s): s for s in collect_steps(orig.get("workflow"))}
    evol_steps = {step_key(s): s for s in collect_steps(evol.get("workflow"))}

    failing = [s["step_key"] for s in report.get("per_step", []) if not s.get("passed")]
    if not failing:
        return 0

    # Walk the evolved YAML and overwrite matching steps' instruction with the original's.
    n = 0
    def walk(node):
        nonlocal n
        if isinstance(node, list):
            for entry in node:
                walk(entry)
        elif isinstance(node, dict):
            for _, v in node.items():
                walk(v)
            if ("step" in node) or ("task" in node):
                kind = "step" if "step" in node else "task"
                body = node.get(kind) or {}
                # We need the branch path; this simple traversal doesn't track it.
                # Instead, match purely by name (good enough for ELAIP plans where
                # step names are unique except for `recheck_options` inside while).
                name = body.get("name")
                for k in failing:
                    o = orig_steps.get(k)
                    e = evol_steps.get(k)
                    if o and e and o.get("name") == name and body.get("instruction") == e.get("instruction"):
                        body["instruction"] = o.get("instruction", "")
                        n += 1
                        break
    walk(evol.get("workflow"))
    working_yaml.write_text(yaml.safe_dump(evol, sort_keys=False, allow_unicode=True),
                            encoding="utf-8")
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    # Both `--working`/`--original`/`--report` (Python-driver style) AND
    # `--evolved`/`--original`/`--digest`/`--report` (YAML-agent style) are
    # accepted so the same script serves both Stage-B drivers.
    p.add_argument("--working", default="", help="Evolved YAML to validate")
    p.add_argument("--evolved", default="",
                   help="Synonym for --working (SWE-style flag from the YAML agent).")
    p.add_argument("--original", required=True, help="Original YAML to compare against")
    p.add_argument("--digest", default="",
                   help="Optional path to plan_evolve_digest.json. When present, "
                        "checks that every digest entry's verdict aligns with the "
                        "evolved YAML (confirmed steps must remain byte-identical, "
                        "falsified steps should differ). Mirrors SWE behaviour.")
    p.add_argument("--report", required=True, help="Output report JSON path")
    p.add_argument("--repair", action="store_true",
                   help="If validation fails, revert failing steps to byte-identical-with-original")
    args = p.parse_args()

    if not args.working and args.evolved:
        args.working = args.evolved
    elif not args.working:
        p.error("either --working or --evolved must be supplied")

    working = Path(args.working).resolve()
    original = Path(args.original).resolve()
    report_path = Path(args.report).resolve()
    digest_path = Path(args.digest).resolve() if args.digest else None

    report = validate_plan(working, original, digest_path=digest_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    summary = report["summary"]
    label = "OK" if summary["pass"] else "FAIL"
    print(f"{label}: validation -> {report_path}  pass={summary['pass']}  "
          f"hard_failures={len(summary.get('hard_failures', []))}  "
          f"falsified_rewritten={summary.get('falsified_rewritten', 0)}  "
          f"confirmed_preserved={summary.get('confirmed_preserved', 0)}")
    if not summary["pass"]:
        for c in summary.get("failing_checks", [])[:10]:
            print(f"  - failing: {c}")

    if args.repair and not summary["pass"]:
        n = repair_failing_steps(report, working, original)
        print(f"REPAIR: reverted {n} step(s) to byte-identical-with-original")
        report2 = validate_plan(working, original, digest_path=digest_path)
        report_path.write_text(json.dumps(report2, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        s2 = report2["summary"]
        print(f"OK: post-repair pass={s2['pass']}")
        sys.exit(0 if s2["pass"] else 1)
    sys.exit(0 if summary["pass"] else 1)


if __name__ == "__main__":
    main()
