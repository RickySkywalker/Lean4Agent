#!/usr/bin/env python3
"""
lean_report_loader.py - ELAIP-flavored Lean Layer-3 query -> per-step digest.

Reads a `layer3_query.json` (produced by Stage A's `parse_lean_diagnosis`
in `elaip_LeanEvolve/run.py` — flat per_node_results format) and emits the
digest array consumed by `evolve_plan_elaip.yaml`'s per-step rewrite loop:

  [
    { "step_index", "step_name", "verdict",
      "failed_predicates", "re_roll_suggestion",
      "re_roll_suggestion_generic",
      "falsified_predicate_details": [
        { "var_name", "predicate_type",
          "lean_verdict": {...}, "tool_verdict": {...}, "llm_verdict": {...},
          "composite", "root_cause" }
      ] }
  ]

Per-predicate root-cause lines are spliced into `re_roll_suggestion` so the
digest carries instance-specific signal (the Lean step-name re-roll alone
is byte-identical for every (plan, qid) sharing the same step name).
Unlike SWE's loader, no `--eval_evidence` override - ELAIP has no harness.
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
    if not generic:
        generic = ""
    evidence_lines: list[str] = []
    for fd in failed_details:
        tag = fd.get("var_name") or "predicate"
        for key in ("root_cause", "tool_verdict", "lean_verdict", "llm_verdict"):
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
            evidence_lines.append(f"  - [{tag} / {label}] {detail[:600]}")
    seen, dedup = set(), []
    for line in evidence_lines:
        k = line[:200]
        if k in seen:
            continue
        seen.add(k)
        dedup.append(line)
    enriched = generic.rstrip()
    if not dedup:
        return enriched or generic
    if enriched:
        enriched += "\nInstance evidence (from Lean Layer-3 per-predicate verdicts):\n"
    else:
        enriched = "Instance evidence (from Lean Layer-3 per-predicate verdicts):\n"
    enriched += "\n".join(dedup[:6])
    return enriched


def build_digest(query: dict) -> list[dict]:
    records: list[dict] = []
    for node in query.get("per_node_results", []) or []:
        idx = node.get("step_index")
        if idx is None:
            idx = len(records)
        verdict = node.get("verdict") or "uncertain"
        failed_details = []
        for d in node.get("falsified_predicate_details") or []:
            failed_details.append({
                "var_name":       d.get("var_name") or "",
                "predicate_type": d.get("predicate_type") or "",
                "lean_verdict":   _copy_verdict(d.get("lean_verdict")),
                "tool_verdict":   _copy_verdict(d.get("tool_verdict")),
                "llm_verdict":    _copy_verdict(d.get("llm_verdict")),
                "composite":      "falsified",
                "root_cause":     d.get("root_cause") or "",
            })
        generic_reroll = node.get("re_roll_suggestion")
        enriched = _enrich_reroll(generic_reroll, failed_details)
        fp = []
        for p in node.get("failed_predicates") or []:
            if p not in fp:
                fp.append(p)
        records.append({
            "step_index":                  int(idx),
            "step_name":                   node.get("step_name") or "",
            "verdict":                     verdict,
            "failed_predicates":           fp,
            "re_roll_suggestion":          enriched,
            "re_roll_suggestion_generic":  generic_reroll,
            "falsified_predicate_details": failed_details,
        })
    records.sort(key=lambda r: r["step_index"])
    return records


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--layer3_query", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    src = Path(args.layer3_query)
    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        return 1
    try:
        query = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: {src} is not valid JSON: {e}", file=sys.stderr)
        return 1
    digest = build_digest(query)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(digest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    counts: dict[str, int] = {}
    for r in digest:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    falsified = [r["step_name"] for r in digest if r["verdict"] != "confirmed"]
    print(f"OK: wrote {out} ({len(digest)} steps; verdicts={counts}; "
          f"falsified={falsified})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
