#!/usr/bin/env python3
"""Deterministic classification of a falsified step's failure against the
failure-pattern template library.

Matches template `symptom_markers` (literal substrings or regex patterns)
against the combined evidence: digest entry detail fields plus
eval_evidence.json's summary_tail and failure_excerpts.

Outputs a JSON object:
  {
    "matched": [
      {"id": "<template_id>", "hits": <int>, "rule": "<general_rule>"},
      ...
    ],
    "evidence_snippet": "<first 400 chars of combined evidence>"
  }

Sorted by hits descending, top 3 returned. If no template has any marker
hit, matched is empty and Phase 3 falls back to a minimal single-sentence
imperative derived from the re_roll_suggestion.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def combined_evidence(digest_entry: dict, eval_evidence: dict) -> str:
    """Concatenate every field that might contain failure signal.

    Pulls from: digest entry's re_roll_suggestion + per-predicate
    tool/llm verdict details; eval_evidence's summary_tail and
    failure_excerpts; and, if available, lines from the raw
    test_output.txt that look like errors (Python exception names,
    AssertionError messages, FAILED pytest lines). The raw test output
    is the authoritative source for runtime error strings that often
    don't propagate into eval_forensics's summary_tail.
    """
    parts: list[str] = []
    parts.append(digest_entry.get("re_roll_suggestion", "") or "")
    for fp in digest_entry.get("falsified_predicate_details", []) or []:
        for kind in ("tool_verdict", "llm_verdict"):
            v = fp.get(kind, {}) or {}
            parts.append(v.get("detail", "") or "")
    for key in ("summary_tail", "failure_excerpts"):
        v = eval_evidence.get(key, [])
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str):
            parts.append(v)

    # Pull error-shaped lines from the raw test_output.txt.
    tpath = eval_evidence.get("test_output_path")
    if tpath and Path(tpath).exists():
        try:
            raw = Path(tpath).read_text(errors="replace")
        except Exception:
            raw = ""
        error_rx = re.compile(
            r"(?i)("
            r"^E\s+\w+Error[^\n]*"
            r"|^\w+Error:[^\n]*"
            r"|^FAILED[^\n]*"
            r"|^AssertionError[^\n]*"
            r"|^ImportError[^\n]*"
            r"|^NameError[^\n]*"
            r"|^AttributeError[^\n]*"
            r"|^TypeError[^\n]*"
            r"|^circular import[^\n]*"
            r"|expected output status[^\n]*"
            r")",
            re.MULTILINE,
        )
        matches = error_rx.findall(raw)
        seen = set()
        deduped: list[str] = []
        for m in matches:
            m_norm = m.strip()[:400]
            if m_norm and m_norm not in seen:
                seen.add(m_norm)
                deduped.append(m_norm)
            if len(deduped) >= 40:
                break
        parts.extend(deduped)
    return "\n".join(p for p in parts if p)


def count_marker_hits(markers: list[str], evidence: str) -> tuple[int, int]:
    """Return (total_hits, unique_markers_matched).

    A marker containing any of `.*()[]\\` is treated as regex; otherwise it
    is a literal substring. Returning both counts lets the caller penalise
    templates that match only via one generic keyword (e.g. `key` or `id`
    hitting 10 times), which was the dominant cause of the two most generic
    templates — #14 cache_key_normalization_mismatch and
    #19 type_normalization_required_for_join_or_comparison — monopolising
    all instance classifications in the Kimi-K2.5 lean_evolve run."""
    total = 0
    unique = 0
    for m in markers:
        is_regex = any(ch in m for ch in r".*()[]\\")
        if is_regex:
            try:
                n = len(re.findall(m, evidence, re.IGNORECASE))
            except re.error:
                n = evidence.lower().count(m.lower())
        else:
            n = evidence.lower().count(m.lower())
        if n > 0:
            total += n
            unique += 1
    return total, unique


def score_template(template: dict, evidence: str, min_unique_markers: int = 2
                   ) -> int:
    """Heuristic score for a template.

    - Requires at least `min_unique_markers` *distinct* markers to match (the
      single-keyword overlap case — e.g. "key" appearing 10× — now yields 0).
    - The final score is `hits * unique_markers`, so a broad match with 3
      unique markers beats a narrow repeated-keyword match. This keeps the
      classifier biased toward templates whose marker cluster, not just one
      keyword, appears in the evidence.
    - If the template declares ≤2 markers, we relax min_unique_markers to 1
      (tiny marker sets can't satisfy the default threshold)."""
    markers = template.get("symptom_markers", []) or []
    if not markers:
        return 0
    threshold = 1 if len(markers) <= 2 else min_unique_markers
    total, unique = count_marker_hits(markers, evidence)
    if unique < threshold:
        return 0
    return total * unique


def _load_frequency_ledger(path: Path) -> dict[str, int]:
    """Shared-state ledger of how many times each template has been the top
    match in the current evolve-run. Used to enforce a cross-instance cap."""
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_frequency_ledger(path: Path, ledger: dict[str, int]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--digest", required=True, type=Path)
    p.add_argument("--eval_evidence", required=True, type=Path)
    p.add_argument("--templates", required=True, type=Path)
    p.add_argument("--step_index", required=True, type=int)
    p.add_argument("--top_k", type=int, default=3)
    p.add_argument("--frequency_ledger", type=Path, default=None,
                   help="Shared JSON ledger of per-template top-match counts "
                        "across a full evolve-run. When passed, templates that "
                        "have already hit their cap are demoted.")
    p.add_argument("--frequency_cap", type=int, default=0,
                   help="Max times a template may be the #1 match in the run. "
                        "0 = no cap (default). Typical setting: "
                        "ceil(num_instances/3).")
    args = p.parse_args()

    digest = json.loads(args.digest.read_text())
    eval_ev = json.loads(args.eval_evidence.read_text())
    templates = json.loads(args.templates.read_text())

    if args.step_index < 0 or args.step_index >= len(digest):
        print(json.dumps({"error": f"step_index {args.step_index} out of range"}), file=sys.stderr)
        return 2
    entry = digest[args.step_index]

    ev_text = combined_evidence(entry, eval_ev)

    scored: list[tuple[int, dict]] = []
    for t in templates:
        s = score_template(t, ev_text)
        if s > 0:
            scored.append((s, t))
    scored.sort(key=lambda x: -x[0])

    ledger = _load_frequency_ledger(args.frequency_ledger)
    demoted: list[str] = []
    if args.frequency_cap and args.frequency_cap > 0 and scored:
        # Promote any #1 candidate that has already hit its cap behind templates
        # still under their cap. This breaks the "one generic template wins
        # every instance" monopoly observed in the Kimi-K2.5 Lean-evolve run
        # where templates #14 and #19 dominated 15/13 and 10/13 slots.
        def _is_capped(t: dict) -> bool:
            return ledger.get(t["id"], 0) >= args.frequency_cap
        front = [x for x in scored if not _is_capped(x[1])]
        back  = [x for x in scored if _is_capped(x[1])]
        demoted = [t["id"] for _, t in back]
        scored = front + back  # keep capped entries, just deprioritise them

    matched = [
        {"id": t["id"], "hits": n, "rule": t["general_rule"]}
        for n, t in scored[: args.top_k]
    ]

    # Record the #1 match (post-demotion) against the frequency ledger.
    if matched and args.frequency_ledger:
        top_id = matched[0]["id"]
        ledger[top_id] = ledger.get(top_id, 0) + 1
        _save_frequency_ledger(args.frequency_ledger, ledger)

    out = {
        "step_name": entry.get("step_name"),
        "verdict": entry.get("verdict"),
        "matched": matched,
        "evidence_snippet": ev_text[:400],
    }
    if demoted:
        out["demoted_by_cap"] = demoted
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
