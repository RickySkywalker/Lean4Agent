#!/usr/bin/env python3
"""
lean_report_loader.py - Compact per-step digest builder.

Reads step 2's Layer-3 Lean query output (`layer3_query.json`) and emits a
flat JSON array, one record per workflow node, that step 3's YAML plan can
consume incrementally via `EditJson.py --path '[<i>]' --get`.

Output schema (array, ordered by node_id):

    [
      {
        "step_index":         int,
        "step_name":          str,
        "verdict":            "confirmed" | "falsified" | "uncertain",
        "failed_predicates":  list[str],
        "re_roll_suggestion": str | null,
        "falsified_predicate_details": [
          {
            "var_name":       str,
            "predicate_type": str,
            "llm_verdict":    {"passed": bool|null, "detail": str,
                               "confidence": float|null},
            "tool_verdict":   {"passed": bool|null, "detail": str,
                               "confidence": float|null},
            "lean_verdict":   {"passed": bool|null, "detail": str,
                               "confidence": float|null}
          }
        ]
      },
      ...
    ]

Only non-sentinel predicates with composite != "confirmed" populate
`falsified_predicate_details`. Sentinel predicates (step_tag, graph_contrib,
node_cap) are skipped — they are graph-level bookkeeping, not step evidence.

CLI:

    python lean_report_loader.py \\
        --layer3_query <path/to/layer3_query.json> \\
        --out <path/to/plan_evolve_digest.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _copy_verdict(raw: dict | None) -> dict:
    if not isinstance(raw, dict):
        return {"passed": None, "detail": "", "confidence": None}
    return {
        "passed":     raw.get("passed"),
        "detail":     raw.get("detail") or "",
        "confidence": raw.get("confidence"),
    }


def _enrich_reroll(generic: str | None, failed_details: list[dict]) -> str | None:
    """Splice per-instance root-cause signal into Lean's step-name-keyed re-roll.

    Lean's `reRollForStep` only keys off step name, so every instance in a run
    gets byte-identical re-roll text for the same falsified step. That kills
    per-instance signal before it reaches Stage B. Each falsified non-sentinel
    predicate's `root_cause` / `llm_verdict.detail` / `tool_verdict.detail` is
    instance-specific (names the failing file, error type, regression count),
    so append those as a concrete "Instance evidence:" block."""
    if not generic:
        generic = ""
    evidence_lines: list[str] = []
    for fd in failed_details:
        tag = fd.get("var_name") or "predicate"
        for key in ("root_cause", "tool_verdict", "llm_verdict"):
            raw = fd.get(key)
            if isinstance(raw, dict):
                detail = (raw.get("detail") or "").strip()
            elif isinstance(raw, str):
                detail = raw.strip()
            else:
                detail = ""
            if not detail or detail.upper() in {"N/A", "NONE"}:
                continue
            label = key.replace("_verdict", "")
            # Cap each line so the combined re-roll stays under ~2 KB.
            evidence_lines.append(f"  - [{tag} / {label}] {detail[:600]}")
    if not evidence_lines:
        return generic or None
    seen: set[str] = set()
    dedup: list[str] = []
    for line in evidence_lines:
        key = line[line.find("]") + 2:][:200]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(line)
    enriched = generic.rstrip()
    if enriched:
        enriched += "\nInstance evidence (from Lean per-predicate verdicts):\n"
    else:
        enriched = "Instance evidence (from Lean per-predicate verdicts):\n"
    enriched += "\n".join(dedup[:6])
    return enriched


def _maybe_apply_lean_disagreement_override(records: list[dict],
                                            eval_evidence: dict | None
                                            ) -> list[dict]:
    """When Lean's per-step analysis says all steps confirmed but the eval
    harness reports the instance as unresolved, Lean disagrees with reality
    — typically because the per-step LLM judge was too lenient. Force the
    canonical "fix" / "verify" steps to falsified so Stage B has something
    to rewrite. Without this override we observed django__django-15098
    falsified_rewritten=0 even though resolved=false."""
    if not eval_evidence:
        return records
    if eval_evidence.get("resolved") is not False:
        return records
    has_falsified = any(r.get("verdict") == "falsified" for r in records)
    if has_falsified:
        return records  # Lean already flagged something; trust it.
    f2p_fail = (eval_evidence.get("tests") or {}).get("f2p_fail") or []
    fail_excerpts = eval_evidence.get("failure_excerpts") or []
    summary_tail = eval_evidence.get("summary_tail") or []
    fail_evidence = "\n".join([
        f"FAIL_TO_PASS still failing ({len(f2p_fail)} test(s)): "
        + ", ".join(str(t)[:200] for t in f2p_fail[:5]),
        *(f"summary: {str(t)[:200]}" for t in summary_tail[:4]),
        *(f"excerpt: {str(t)[:300]}" for t in fail_excerpts[:2]),
    ])
    forced_steps = {"fix_issue", "verify_fix"}
    for r in records:
        if r.get("step_name") in forced_steps:
            r["verdict"] = "falsified"
            r["failed_predicates"] = list(
                set((r.get("failed_predicates") or [])
                    + ["lean_disagreement_override"]))
            synthetic_detail = {
                "var_name": "lean_disagreement_override",
                "predicate_type": "ext(eval_disagreement)",
                "llm_verdict": {
                    "passed": False,
                    "detail": (f"Eval harness reports resolved=false yet "
                               f"Lean Layer-3 marked this step confirmed. "
                               f"Treat as failed: {fail_evidence}"),
                    "confidence": 1.0,
                },
                "tool_verdict": {"passed": False, "detail": fail_evidence,
                                 "confidence": 1.0},
                "lean_verdict": {"passed": None, "detail": "(overridden)",
                                 "confidence": None},
                "composite": "falsified",
                "root_cause": fail_evidence,
            }
            r["falsified_predicate_details"] = [
                synthetic_detail,
                *r.get("falsified_predicate_details", []),
            ]
            r["re_roll_suggestion"] = _enrich_reroll(
                r.get("re_roll_suggestion_generic")
                or r.get("re_roll_suggestion"),
                r["falsified_predicate_details"])
    return records


def build_digest(query: dict, eval_evidence: dict | None = None) -> list[dict]:
    """Transform a Lean `layer3_query.json` dict into the per-step digest.

    If `eval_evidence` is supplied and shows `resolved=false` while Lean's
    per-step analysis flagged nothing falsified, override fix_issue +
    verify_fix to falsified so Stage B can still rewrite them."""
    records: list[dict] = []
    for node in query.get("per_node_results", []) or []:
        layer3 = node.get("layer3") or {}
        composite = layer3.get("step_composite") or {}
        verdict = composite.get("verdict") or "uncertain"
        step_name = (layer3.get("step_name")
                     or node.get("node_name") or "")
        step_index = node.get("node_id")
        if step_index is None:
            step_index = layer3.get("step_id", len(records))

        failed_details: list[dict] = []
        for pv in layer3.get("postcondition_verdicts", []) or []:
            if pv.get("is_sentinel"):
                continue
            composite_v = pv.get("composite")
            if composite_v == "confirmed":
                continue
            failed_details.append({
                "var_name":       pv.get("var_name") or "",
                "predicate_type": pv.get("predicate_type") or "",
                "llm_verdict":    _copy_verdict(pv.get("llm_verdict")),
                "tool_verdict":   _copy_verdict(pv.get("tool_verdict")),
                "lean_verdict":   _copy_verdict(pv.get("lean_verdict")),
                "composite":      composite_v or "uncertain",
                "root_cause":     pv.get("root_cause") or "",
            })

        generic_reroll = composite.get("re_roll_suggestion")
        enriched_reroll = _enrich_reroll(generic_reroll, failed_details)

        records.append({
            "step_index":                  step_index,
            "step_name":                   step_name,
            "verdict":                     verdict,
            "failed_predicates":           list(composite.get("failed_predicates") or []),
            "re_roll_suggestion":          enriched_reroll,
            "re_roll_suggestion_generic":  generic_reroll,
            "falsified_predicate_details": failed_details,
        })
    # Sort by step_index to guarantee YAML loop ordering.
    records.sort(key=lambda r: r["step_index"])
    records = _maybe_apply_lean_disagreement_override(records, eval_evidence)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--layer3_query", required=True,
                        help="Path to step 2's layer3_query.json")
    parser.add_argument("--eval_evidence", default="",
                        help="Optional path to eval_evidence.json. When the "
                        "instance is resolved=false but Lean flagged nothing "
                        "falsified, fix_issue + verify_fix are forced to "
                        "falsified with synthetic evidence.")
    parser.add_argument("--out", required=True,
                        help="Path to write plan_evolve_digest.json")
    args = parser.parse_args()

    src = Path(args.layer3_query)
    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        return 1
    try:
        query = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: {src} is not valid JSON: {e}", file=sys.stderr)
        return 1

    eval_evidence = None
    if args.eval_evidence:
        ev_path = Path(args.eval_evidence)
        if ev_path.exists():
            try:
                eval_evidence = json.loads(ev_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                print(f"Warning: eval_evidence not valid JSON, ignoring: {e}",
                      file=sys.stderr)
    digest = build_digest(query, eval_evidence=eval_evidence)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(digest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    counts: dict[str, int] = {}
    for r in digest:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    falsified_names = [r["step_name"] for r in digest if r["verdict"] != "confirmed"]
    print(f"OK: wrote {out} ({len(digest)} steps; verdicts={counts}; "
          f"falsified={falsified_names})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
