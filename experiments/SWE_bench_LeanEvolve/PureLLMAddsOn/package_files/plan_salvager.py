#!/usr/bin/env python3
"""
plan_salvager.py - Best-effort recovery when plan_validator.py rejects an
evolved plan.

The validator emits a binary pass/fail; on fail we currently drop the
instance entirely, so stage_c never reruns it. This salvager turns a failed
evolution into a usable YAML so stage_c always has *something* to submit:

  - If the evolved plan is missing or unparseable, or any STRUCTURAL check
    failed (`yaml_parses`, `top_level_keys_match`, `top_level_key_unchanged`,
    `step_count_match`, `step_names_match`, `block_scalar_preserved`) — fall
    back to the ORIGINAL plan verbatim.  Mode = `full_fallback`.

  - Otherwise (only per-step content checks failed: `confirmed_step_byte_identical`,
    `templates_preserved`, `no_audit_leakage`) — start from the original plan
    and copy in the LLM's evolved instruction for every leaf step whose
    per-step checks all passed.  Steps with any per-step failure are kept at
    their original instruction.  Mode = `partial`.  `falsified_step_differs`
    failures are benign for salvage purposes (LLM left the step unchanged
    when it should have rewritten — the salvage is "leave it unchanged",
    which is what the original already says, so no special handling needed).

Call from a host-side orchestrator (see `run.py`) - this file is also copied
into `<staging_root>/package/` so it can be invoked as a CLI step inside the
AgentSPEX if a future evolve.yaml wants to salvage in-band.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

import yaml


_LEAF_KEYS = ("task", "step")
_STRUCTURAL_CHECKS = frozenset({
    "yaml_parses",
    "original_parses",
    "digest_parses",
    "top_level_keys_match",
    "top_level_key_unchanged",
    "step_count_match",
    "step_names_match",
    "block_scalar_preserved",
})
# Per-step content checks; the suffix `[i:name]` is stripped before matching.
_PER_STEP_CHECKS_REVERT = frozenset({
    "confirmed_step_byte_identical",
    "templates_preserved",
    "no_audit_leakage",
})


def _safe_load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _walk_leaves(seq, fn) -> None:
    """Recursively walk workflow, invoking fn(leaf_dict) on every task/step
    leaf in source order.  Mutations to leaf_dict are visible to the caller."""
    for item in (seq or []):
        if not isinstance(item, dict):
            continue
        for key, val in list(item.items()):
            if key in _LEAF_KEYS and isinstance(val, dict):
                fn(val)
            elif key in ("for_each", "while"):
                _walk_leaves((val or {}).get("steps") or [], fn)
            elif key == "if":
                bv = val or {}
                for br in ("steps_true", "steps_false", "steps"):
                    _walk_leaves(bv.get(br) or [], fn)
            elif key == "switch":
                sw = val or {}
                for case in (sw.get("cases") or []):
                    _walk_leaves((case or {}).get("steps") or [], fn)
                _walk_leaves(((sw.get("default") or {}).get("steps") or []), fn)
            elif key == "parallel":
                for branch in ((val or {}).get("branches") or []):
                    _walk_leaves((branch or {}).get("steps") or [], fn)
            break


def _flatten_leaf_instructions(plan: dict) -> dict:
    """Return {leaf_step_name: instruction_text} for all leaves of `plan`."""
    out: dict[str, str] = {}

    def collect(leaf: dict) -> None:
        nm = leaf.get("name") or ""
        if nm:
            out[nm] = leaf.get("instruction") or ""

    _walk_leaves(plan.get("workflow") or [], collect)
    return out


_PER_STEP_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\[\d+:([^\]]+)\]$")


def _classify_failures(checks: list[dict]) -> tuple[bool, set[str]]:
    """Inspect the validation_report's `checks` list.

    Returns (structural_failure, revert_step_names):
      * structural_failure: True if any failing check is structural (cannot
        be salvaged per-step; caller should fall back to original verbatim).
      * revert_step_names: set of leaf-step names that need their instruction
        reverted to original because at least one per-step check failed on
        them.
    """
    structural = False
    revert: set[str] = set()
    for c in checks:
        if c.get("pass"):
            continue
        name = c.get("check") or ""
        if name in _STRUCTURAL_CHECKS:
            structural = True
            continue
        m = _PER_STEP_RE.match(name)
        if not m:
            # Unknown failure type — be conservative and treat as structural.
            structural = True
            continue
        kind, step_name = m.group(1), m.group(2)
        if kind in _PER_STEP_CHECKS_REVERT:
            revert.add(step_name)
        # `falsified_step_differs` failures: LLM left a step unchanged that it
        # should have rewritten.  The evolved instruction == original, so the
        # salvaged output is identical regardless; no action needed.
    return structural, revert


def _str_block_representer(dumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _BlockDumper(yaml.SafeDumper):
    pass


_BlockDumper.add_representer(str, _str_block_representer)


def _dump_yaml(plan: dict) -> str:
    return yaml.dump(plan, Dumper=_BlockDumper, sort_keys=False,
                     allow_unicode=True, default_flow_style=False, width=10**9)


def salvage_plan(original_yaml: Path,
                 evolved_yaml: Path | None,
                 validation_report: Path | None,
                 out_yaml: Path) -> dict:
    """Build a best-effort YAML at `out_yaml` and return a summary dict.

    Args:
      original_yaml: required.  Always exists; never modified.
      evolved_yaml: may be None or unparseable, in which case we full-fallback.
      validation_report: may be None (e.g. validator never ran), in which case
        we full-fallback.
      out_yaml: target file to write the salvaged plan into.

    Returns:
      {"mode": "full_fallback"|"partial",
       "reverted_steps": [list of step names reverted to original],
       "kept_evolved_steps": [list of step names whose evolved instruction was kept],
       "reason": short string explaining why this mode was chosen}
    """
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    original_text = original_yaml.read_text(encoding="utf-8")
    summary: dict = {"mode": "full_fallback", "reverted_steps": [],
                     "kept_evolved_steps": [], "reason": ""}

    # Tier 0 - missing inputs => full fallback.
    if evolved_yaml is None or not evolved_yaml.exists():
        summary["reason"] = "evolved_plan.yaml missing"
        out_yaml.write_text(original_text, encoding="utf-8")
        return summary
    if validation_report is None or not validation_report.exists():
        summary["reason"] = "validation_report.json missing"
        out_yaml.write_text(original_text, encoding="utf-8")
        return summary

    # Tier 1 - try to read everything; any parse failure => full fallback.
    try:
        original_plan = _safe_load(original_yaml)
        evolved_plan = _safe_load(evolved_yaml)
        report = json.loads(validation_report.read_text(encoding="utf-8"))
    except Exception as e:
        summary["reason"] = f"input parse error: {type(e).__name__}: {e}"
        out_yaml.write_text(original_text, encoding="utf-8")
        return summary

    checks = report.get("checks") or []
    structural, revert_names = _classify_failures(checks)

    if structural:
        failing = [c.get("check") for c in checks
                   if not c.get("pass") and (c.get("check") or "") in _STRUCTURAL_CHECKS]
        summary["reason"] = f"structural validation failure(s): {failing}"
        out_yaml.write_text(original_text, encoding="utf-8")
        return summary

    # Tier 2 - per-step salvage.  Walk the original plan and swap in evolved
    # instructions for every step NOT in revert_names.
    evo_instr_by_name = _flatten_leaf_instructions(evolved_plan)
    salvaged = copy.deepcopy(original_plan)
    kept: list[str] = []
    reverted: list[str] = []

    def patch(leaf: dict) -> None:
        nm = leaf.get("name") or ""
        if not nm:
            return
        if nm in revert_names:
            reverted.append(nm)
            return  # keep original instruction (already in deepcopy)
        if nm in evo_instr_by_name:
            leaf["instruction"] = evo_instr_by_name[nm]
            kept.append(nm)

    _walk_leaves(salvaged.get("workflow") or [], patch)

    out_yaml.write_text(_dump_yaml(salvaged), encoding="utf-8")
    summary.update({
        "mode": "partial",
        "reverted_steps": reverted,
        "kept_evolved_steps": kept,
        "reason": (f"reverted {len(reverted)} step(s) to original; "
                   f"kept {len(kept)} evolved step(s)"),
    })
    return summary


def main() -> int:
    p = argparse.ArgumentParser(
        description=("Build a best-effort salvaged YAML when "
                     "plan_validator.py rejects an evolved plan."))
    p.add_argument("--original", required=True)
    p.add_argument("--evolved", required=False, default="",
                   help="evolved_plan.yaml; pass empty to force full fallback.")
    p.add_argument("--validation_report", required=False, default="",
                   help="validation_report.json; pass empty to force full fallback.")
    p.add_argument("--out", required=True,
                   help="Where to write the salvaged YAML.")
    p.add_argument("--summary_out", default="",
                   help="Optional: also write the salvage summary JSON here.")
    args = p.parse_args()

    summary = salvage_plan(
        Path(args.original),
        Path(args.evolved) if args.evolved else None,
        Path(args.validation_report) if args.validation_report else None,
        Path(args.out),
    )
    if args.summary_out:
        Path(args.summary_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_out).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    print(f"{summary['mode'].upper()}: {summary['reason']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
