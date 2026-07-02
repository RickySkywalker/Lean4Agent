#!/usr/bin/env python3
"""
tighten_layer3_verdicts.py — ELAIP Layer-3 IR deterministic JSON-shape gate.

Replaces SWE's harness-based ground-truth gate. SWE flips fix-side
injections to `holds=false` whenever `report.json.resolved == false`.
ELAIP has no harness — instead, we apply **decidable JSON-shape rules**
to the agent's saved variable values: when a predicate-violating value
is in the trajectory, any LLM injection that says `holds=true` for that
variable's postcondition predicate gets mechanically flipped to
`holds=false`.

Rules (idempotent; safe to re-run):

  R1. `option_judgment.verdict` enum violation
        For any A/B/C/D entry whose `verdict` ∉
        {supported, contradicted, not_established}, every llm_injection
        with var_name == 'option_judgment' is flipped to holds=false.

  R2. Bounded evidence list
        If `evidence.evidence_snippets` parses as a list of length > 5,
        every injection with var_name == 'evidence' is flipped to false.

  R3. Verbatim-substring violation
        If any `evidence_snippets[i].text` is non-empty AND does not
        appear as a substring of `paper_content` in exec_state, the
        evidence injection is flipped to false.

  R4. JSON parseability
        If the saved value for a variable does not parse as JSON when
        the postcondition includes `isValidJson`, the injection is
        flipped to false.

  R5. Question-type enum
        `question_analysis.question_type` ∉ {Single-answer,
        Multiple-answer, SA-MCQ, MA-MCQ} → flip the question_analysis
        injection.

Output: prints `OK:` followed by a list of (step_name, var_name, rule) tuples
that were flipped (may be empty). Modifies the IR in place.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERDICT_TAGS = {"supported", "contradicted", "not_established"}
QTYPE_TAGS   = {"Single-answer", "Multiple-answer", "SA-MCQ", "MA-MCQ"}


def _try_parse(s: str):
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        import ast
        return ast.literal_eval(s)
    except Exception:
        return None


def _exec_state_get(exec_state: list, name: str) -> str | None:
    for entry in exec_state or []:
        if isinstance(entry, list) and len(entry) >= 2 and entry[0] == name:
            return entry[1] if isinstance(entry[1], str) else json.dumps(entry[1])
    return None


def _flip(injection: dict, reason: str) -> None:
    judgement = injection.get("judgement")
    if not isinstance(judgement, dict):
        injection.setdefault("judgement", {})
        judgement = injection["judgement"]
    if injection.get("holds") is True:
        injection["holds"] = False
    if isinstance(judgement, dict) and judgement.get("holds") is True:
        judgement["holds"] = False
    expl = (injection.get("llm_explanation")
            or (judgement.get("llmExplanation") if isinstance(judgement, dict) else "")
            or "")
    new_expl = f"[deterministic gate] {reason}. (was: {expl[:200]!r})"
    injection["llm_explanation"] = new_expl
    if isinstance(judgement, dict):
        judgement["llmExplanation"] = new_expl
        judgement["confidence"] = 0.99


def gate_ir(ir: dict) -> list[tuple[str, str, str]]:
    flips: list[tuple[str, str, str]] = []
    exec_state = ir.get("exec_state") or []
    paper_content = _exec_state_get(exec_state, "paper_content") or ""

    # R1 / R2 / R3 / R4 / R5 — derive violations from exec_state values.
    violations: dict[str, str] = {}  # var_name -> reason

    oj_raw = _exec_state_get(exec_state, "option_judgment")
    if oj_raw is not None:
        parsed = _try_parse(oj_raw)
        if parsed is None:
            violations["option_judgment"] = "R4 option_judgment not parseable as JSON"
        elif isinstance(parsed, dict):
            bad = []
            for k in ("A", "B", "C", "D"):
                v = parsed.get(k)
                if isinstance(v, dict):
                    verdict = v.get("verdict")
                    if verdict not in VERDICT_TAGS:
                        bad.append(f"{k}={verdict!r}")
                else:
                    bad.append(f"{k}=missing")
            if bad:
                violations["option_judgment"] = (
                    "R1 verdictEnumValid violated: " + ", ".join(bad[:6]))

    qa_raw = _exec_state_get(exec_state, "question_analysis")
    if qa_raw is not None:
        parsed = _try_parse(qa_raw)
        if parsed is None:
            violations["question_analysis"] = "R4 question_analysis not parseable as JSON"
        elif isinstance(parsed, dict):
            qt = parsed.get("question_type")
            if qt not in QTYPE_TAGS and qt is not None:
                violations["question_analysis"] = (
                    f"R5 questionTypeEnum violated: question_type={qt!r}")

    ev_raw = _exec_state_get(exec_state, "evidence")
    if ev_raw is not None:
        parsed = _try_parse(ev_raw)
        if parsed is None:
            violations["evidence"] = "R4 evidence not parseable as JSON"
        elif isinstance(parsed, dict):
            snippets = parsed.get("evidence_snippets")
            if isinstance(snippets, list):
                if len(snippets) > 5:
                    violations["evidence"] = (
                        f"R2 boundedEvidenceList violated: length={len(snippets)} > 5")
                elif paper_content:
                    bad = []
                    for i, sn in enumerate(snippets):
                        if isinstance(sn, dict):
                            text = sn.get("text") or ""
                            if isinstance(text, str) and text.strip() and \
                               text.strip() not in paper_content:
                                bad.append(f"snippet[{i}].text not verbatim")
                    if bad:
                        violations["evidence"] = "R3 verbatimSubstring violated: " + bad[0]
            elif snippets is None:
                violations["evidence"] = "R2 evidence_snippets missing"

    # Apply flips to llm_injections that disagree with derived violations.
    for inj in ir.get("llm_injections") or []:
        var_name = inj.get("var_name") or inj.get("varName") or ""
        if var_name not in violations:
            continue
        holds = inj.get("holds")
        if holds is None and isinstance(inj.get("judgement"), dict):
            holds = inj["judgement"].get("holds")
        if holds is True:
            _flip(inj, violations[var_name])
            flips.append((inj.get("step_name", ""), var_name, violations[var_name]))
    return flips


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--layer3_ir", required=True,
                   help="Path to the Layer-3 IR JSON to gate (modified in place).")
    args = p.parse_args()
    ir_path = Path(args.layer3_ir)
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    flips = gate_ir(ir)
    ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    print(f"OK: {len(flips)} injection(s) flipped by deterministic gate")
    for step, var, reason in flips:
        print(f"  [{step}/{var}] {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
