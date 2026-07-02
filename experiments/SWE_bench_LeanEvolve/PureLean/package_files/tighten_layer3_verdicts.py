#!/usr/bin/env python3
"""Deterministic ground-truth gate for Layer-3 IR verdicts.

Runs AFTER the LLM-driven annotate_layer3.yaml and BEFORE Lean lake build.
The point: even with the conservative judge prompt + the consistency review,
we have empirically observed Layer-3 LLM judges declaring `holds=true` for
fix-side variables when the harness reports `resolved=false`. Those verdicts
make the downstream evolve pipeline a no-op (Lean says "all confirmed", so
nothing gets rewritten). This script enforces the harness as ground truth:

  if eval_evidence.resolved == False:
      for inj in llm_injections:
          if inj.var_name in {fix_implementation_evidence,
                              fix_verification_evidence,
                              patch_submission_evidence}:
              inj.holds = False
              inj.llm_explanation = (
                  "[GROUND_TRUTH_GATE] eval reports resolved=false; "
                  "FAIL_TO_PASS still failing: <list>; "
                  "this fix-side variable cannot hold by definition.")

  if eval_evidence.resolved == True:
      for inj in llm_injections:
          if inj.var_name in {fix_implementation_evidence,
                              fix_verification_evidence,
                              patch_submission_evidence}:
              if inj.holds is False:
                  # also tighten in the OTHER direction
                  inj.holds = True
                  inj.llm_explanation = "[GROUND_TRUTH_GATE] resolved=true."

Idempotent. Reads/writes the Layer-3 IR JSON.

CLI:
  python tighten_layer3_verdicts.py \\
      --layer3_ir <path/to/layer3_ir.json> \\
      --eval_evidence <path/to/eval_evidence.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FIX_SIDE_VARS = {
    "fix_implementation_evidence",
    "fix_verification_evidence",
    "patch_submission_evidence",
}


def _format_failing(f2p_fail: list, p2p_fail: list, max_each: int = 3) -> str:
    parts = []
    if f2p_fail:
        parts.append(
            "FAIL_TO_PASS still failing ({}): {}".format(
                len(f2p_fail),
                ", ".join(str(t)[:120] for t in f2p_fail[:max_each]),
            )
        )
    if p2p_fail:
        parts.append(
            "PASS_TO_PASS regressed ({}): {}".format(
                len(p2p_fail),
                ", ".join(str(t)[:120] for t in p2p_fail[:max_each]),
            )
        )
    return "; ".join(parts) if parts else "no test breakdown captured"


def _is_truthy_holds(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes"}
    return bool(v)


def tighten(layer3_ir: dict, eval_evidence: dict) -> tuple[dict, list]:
    """Return (modified_ir, change_log)."""
    changes: list[dict] = []
    resolved = eval_evidence.get("resolved")
    f2p_fail = (eval_evidence.get("tests") or {}).get("f2p_fail") or []
    p2p_fail = (eval_evidence.get("tests") or {}).get("p2p_fail") or []
    failing_str = _format_failing(f2p_fail, p2p_fail)

    injections = layer3_ir.get("llm_injections") or []

    for idx, inj in enumerate(injections):
        if not isinstance(inj, dict):
            continue
        var = str(inj.get("var_name") or "")
        if var not in FIX_SIDE_VARS:
            continue
        old_holds = _is_truthy_holds(inj.get("holds"))
        old_expl = inj.get("llm_explanation") or ""

        if resolved is False:
            new_holds = False
            new_expl = (
                f"[GROUND_TRUTH_GATE] eval reports resolved=false; {failing_str}; "
                f"fix-side variable {var} cannot hold by definition. "
                f"(Original judge said holds={old_holds}; "
                f"original explanation: {old_expl[:200]!r})"
            )
        elif resolved is True:
            # Don't override true-→-true (no-op) or true-→-false (uncommon).
            # But if judge said holds=false despite resolved=true, that's
            # also wrong: harness disagrees with judge, harness wins.
            new_holds = True
            if old_holds:
                continue  # already correct
            new_expl = (
                f"[GROUND_TRUTH_GATE] eval reports resolved=true; "
                f"fix-side variable {var} held per harness. "
                f"(Original judge said holds=false; "
                f"original explanation: {old_expl[:200]!r})"
            )
        else:
            continue  # resolved is None / unknown, leave alone

        if old_holds == new_holds and "GROUND_TRUTH_GATE" in old_expl:
            # already gated, idempotent skip
            continue

        inj["holds"] = new_holds
        inj["llm_explanation"] = new_expl
        # Bump confidence to reflect harness certainty.
        inj["confidence"] = 0.99
        changes.append({
            "index": idx,
            "var_name": var,
            "old_holds": old_holds,
            "new_holds": new_holds,
        })

    return layer3_ir, changes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--layer3_ir", required=True, type=Path)
    p.add_argument("--eval_evidence", required=True, type=Path)
    args = p.parse_args()

    if not args.layer3_ir.exists():
        print(f"ERROR: layer3_ir not found: {args.layer3_ir}", file=sys.stderr)
        return 2
    if not args.eval_evidence.exists():
        print(f"ERROR: eval_evidence not found: {args.eval_evidence}",
              file=sys.stderr)
        return 2

    layer3_ir = json.loads(args.layer3_ir.read_text(encoding="utf-8"))
    eval_evidence = json.loads(args.eval_evidence.read_text(encoding="utf-8"))

    new_ir, changes = tighten(layer3_ir, eval_evidence)

    if changes:
        args.layer3_ir.write_text(
            json.dumps(new_ir, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"OK: {len(changes)} verdict(s) tightened by ground-truth gate:")
        for c in changes:
            print(f"  [{c['index']}] {c['var_name']}: holds "
                  f"{c['old_holds']} -> {c['new_holds']}")
    else:
        print("OK: no verdict changes needed (judges already aligned with harness)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
