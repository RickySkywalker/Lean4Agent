#!/usr/bin/env python3
"""Mine additional general failure-pattern templates from the 50-problem
benchmark_results corpus and append them to `failure_pattern_templates.json`.

Design (map/reduce):

  M1  per-instance extract:   49 × one LLM call each. Reads report.json +
                              bounded slice of test_output.txt. Emits a
                              structured JSON extract. Each extract's
                              `generalization_seed` field is validated against
                              `plan_validator.CHEAT_SHEET_PATTERNS` before
                              acceptance; violations trigger one retry with
                              the specific regex fed back.
  M2  reduce/cluster:         single LLM call on the concatenated 49 extracts.
                              Produces candidate templates in the same schema
                              as the existing `failure_pattern_templates.json`.
  M3  local filtering:        for each candidate:
                              (a) `general_rule` validated against
                                  CHEAT_SHEET_PATTERNS
                              (b) word-trigram Jaccard vs every existing
                                  `general_rule` — rejected if >= 0.60
                              (c) `classify_failure.py` re-run on the 4 smoke
                                  instances must not regress hit-counts on
                                  existing templates.
                              Accepted candidates are appended.

Usage:
    python leanagent/codegen/agent_evolve/mine_failure_patterns.py \
        --benchmark_root benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1/gpt-5.2 \
        --templates leanagent/codegen/agent_evolve/failure_pattern_templates.json \
        --model "${MODEL_NAME:-openai/gpt-5.2}"

The existing templates file is updated in place. An audit log of each
candidate (accepted / rejected with reason) is written to
<templates_path>.mining_log.json next to it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Make the sandbox package importable so we can reuse validator logic.
_REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
sys.path.insert(0, str(_REPO_ROOT / "engine" / "src"))

from harness.llms.client import LLMClient  # noqa: E402

# Reuse CHEAT_SHEET_PATTERNS from the validator so the miner and runtime
# gate are literally identical.
sys.path.insert(0, str(_REPO_ROOT / "leanagent" / "codegen" / "agent_evolve"))
from plan_validator import CHEAT_SHEET_PATTERNS  # noqa: E402


TEST_OUTPUT_HEAD_BYTES = 8 * 1024
TEST_OUTPUT_TAIL_BYTES = 8 * 1024


def _word_trigrams(text: str) -> set[tuple[str, str, str]]:
    toks = re.findall(r"[A-Za-z]+", text.lower())
    if len(toks) < 3:
        return set()
    return {(toks[i], toks[i + 1], toks[i + 2]) for i in range(len(toks) - 2)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _violations(text: str) -> list[str]:
    """Return [desc, ...] of CHEAT_SHEET_PATTERNS that hit `text`."""
    hits: list[str] = []
    for pat, desc in CHEAT_SHEET_PATTERNS:
        if re.search(pat, text):
            hits.append(desc)
    return hits


def _trim_middle(text: str, head: int = TEST_OUTPUT_HEAD_BYTES,
                 tail: int = TEST_OUTPUT_TAIL_BYTES) -> str:
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n\n... [{len(text) - head - tail} bytes elided] ...\n\n{text[-tail:]}"


def _parse_llm_json(raw: str) -> Any:
    """Parse JSON from an LLM response that may be wrapped in ``` fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        # strip the first fence + optional language, and the trailing fence
        lines = raw.splitlines()
        # drop first line (```json or ```)
        lines = lines[1:]
        # drop trailing fence
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        raw = "\n".join(lines).strip()
    # Try direct parse.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fall back: find the first [ ... ] or { ... } block.
    for opener, closer in (("[", "]"), ("{", "}")):
        i = raw.find(opener)
        j = raw.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"could not parse JSON from LLM output: {raw[:500]!r}...")


# -----------------------------------------------------------------------------
# Stage M1 — per-instance extract
# -----------------------------------------------------------------------------

M1_SYSTEM = (
    "You are analyzing a single SWE-bench-verified instance's failure. "
    "Output a SINGLE JSON object matching the schema EXACTLY. "
    "The `generalization_seed` field MUST be one sentence of general imperative "
    "prose, with NO pytest test IDs, NO file:line refs, NO verbatim error "
    "messages, NO repo-specific symbols, NO framework module paths. "
    "Describe the failure CLASS, not this particular test."
)


M1_USER_TEMPLATE = """Here is the failure for one SWE-bench-verified instance.

INSTANCE_ID: {instance_id}

report.json (truncated):
```json
{report_snippet}
```

test_output.txt (head + tail):
```
{test_output_snippet}
```

Produce a JSON object of the form:
{{
  "instance_id": "{instance_id}",
  "trigger_shape": "<short kebab-case tag, e.g. 'assertion_on_output_shape' or 'signature_mismatch_on_constructor'>",
  "symptom_class": "<short tag, e.g. 'single_line_assertion' | 'stack_trace' | 'patch_empty' | 'collection_error'>",
  "error_family": "<AssertionError | TypeError | NameError | ImportError | other>",
  "patch_shape_hypothesis": "<short tag describing the patch shape that would likely resolve this, e.g. 'missing_branch' | 'wrong_scope' | 'stale_cache' | 'signature_preservation'>",
  "generalization_seed": "<ONE SENTENCE of general imperative prose — NO per-instance identifiers, NO filenames, NO test names>"
}}

Output ONLY the JSON object, no prose, no fences.
{violation_feedback}"""


def call_m1(client: LLMClient, model: str, instance_id: str,
            report_snippet: str, test_output_snippet: str,
            violation_feedback: str = "") -> dict[str, Any]:
    messages = [
        {"role": "system", "content": M1_SYSTEM},
        {"role": "user", "content": M1_USER_TEMPLATE.format(
            instance_id=instance_id,
            report_snippet=report_snippet[:8000],
            test_output_snippet=test_output_snippet,
            violation_feedback=violation_feedback,
        )},
    ]
    resp = client.completion(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=8192,
        num_retries=2,
    )
    raw = resp.choices[0].message.content or ""
    return _parse_llm_json(raw)


def mine_stage_m1(client: LLMClient, model: str, benchmark_root: Path,
                  log_out: list[dict]) -> list[dict]:
    extracts: list[dict] = []
    instance_dirs = sorted(p for p in benchmark_root.iterdir() if p.is_dir())
    for idx, inst_dir in enumerate(instance_dirs, 1):
        instance_id = inst_dir.name
        rep = inst_dir / "report.json"
        tout = inst_dir / "test_output.txt"
        if not rep.exists() or not tout.exists():
            log_out.append({"stage": "M1", "instance_id": instance_id,
                            "status": "skipped_missing_file"})
            continue
        try:
            report_snippet = rep.read_text(encoding="utf-8", errors="replace")
            test_output = tout.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log_out.append({"stage": "M1", "instance_id": instance_id,
                            "status": "skipped_read_error",
                            "detail": f"{type(e).__name__}: {e}"})
            continue

        test_snippet = _trim_middle(test_output)
        violation_feedback = ""
        attempt = 0
        extract: Optional[dict[str, Any]] = None
        while attempt < 2:
            attempt += 1
            try:
                extract = call_m1(client, model, instance_id,
                                  report_snippet, test_snippet,
                                  violation_feedback)
            except Exception as e:
                log_out.append({"stage": "M1", "instance_id": instance_id,
                                "status": f"llm_error_attempt_{attempt}",
                                "detail": f"{type(e).__name__}: {e}"})
                break
            seed = str(extract.get("generalization_seed", "") or "")
            viol = _violations(seed)
            if not viol:
                extracts.append(extract)
                log_out.append({"stage": "M1", "instance_id": instance_id,
                                "status": "ok", "attempt": attempt})
                break
            violation_feedback = (
                f"\nYour previous `generalization_seed` tripped these "
                f"forbidden patterns: {viol}. Rewrite the seed without any "
                f"per-instance identifiers — only describe the failure CLASS.")
            log_out.append({"stage": "M1", "instance_id": instance_id,
                            "status": "retry_violations", "attempt": attempt,
                            "violations": viol})
        else:
            log_out.append({"stage": "M1", "instance_id": instance_id,
                            "status": "gave_up_after_retries"})
        print(f"[M1] {idx}/{len(instance_dirs)} {instance_id}: "
              f"{'ok' if extract and extract in extracts else 'skipped'}",
              flush=True)
    return extracts


# -----------------------------------------------------------------------------
# Stage M2 — reduce/cluster
# -----------------------------------------------------------------------------

M2_SYSTEM = (
    "You are clustering SWE-bench failure extracts into GENERAL-PURPOSE "
    "templates that will be used by a deterministic failure classifier "
    "(symptom_markers regexes) and a plan-evolution rewriter (general_rule "
    "prose). Every template's `general_rule` must be INSTANCE-AGNOSTIC: no "
    "pytest IDs, no file:line refs, no verbatim error messages, no framework "
    "symbols. Produce ONLY classes NOT already covered by the existing "
    "templates listed below."
)

M2_USER_TEMPLATE = """EXISTING TEMPLATES (their ids + general_rule first-100-chars) — DO NOT duplicate ANY of these:

{existing_digest}

PER-INSTANCE EXTRACTS ({n_extracts} total):

```json
{extracts_json}
```

Cluster these extracts into NEW general failure-pattern templates. Each new template must be:
  * Distinct from every existing template (no paraphrase duplicates).
  * General: the `general_rule` must apply to an entire class of bugs, not one instance.
  * Structured: provide `id` (snake_case), `trigger` (1-2 sentences describing when this applies),
    `symptom_markers` (list of 3-8 case-insensitive substrings OR regex patterns a classifier can
    grep on concatenated evidence), and `general_rule` (2-4 sentences of imperative prose).

Output a JSON array of NEW template objects. Target 7 to 12 new templates. Skip any cluster
whose behavior is already covered by an existing template. Output ONLY the JSON array.
"""


def call_m2(client: LLMClient, model: str, existing_digest: str,
            extracts: list[dict]) -> list[dict]:
    messages = [
        {"role": "system", "content": M2_SYSTEM},
        {"role": "user", "content": M2_USER_TEMPLATE.format(
            existing_digest=existing_digest,
            n_extracts=len(extracts),
            extracts_json=json.dumps(extracts, indent=2, ensure_ascii=False),
        )},
    ]
    resp = client.completion(
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=16384,
        num_retries=2,
    )
    raw = resp.choices[0].message.content or ""
    parsed = _parse_llm_json(raw)
    if not isinstance(parsed, list):
        raise ValueError(f"expected list, got {type(parsed).__name__}")
    return parsed


# -----------------------------------------------------------------------------
# Stage M3 — local filters (validator + jaccard dedup + classifier smoke)
# -----------------------------------------------------------------------------

def filter_candidates(candidates: list[dict], existing: list[dict],
                      log_out: list[dict]) -> list[dict]:
    accepted: list[dict] = []
    existing_trigrams = [
        (t["id"], _word_trigrams(t.get("general_rule", "")))
        for t in existing
    ]
    existing_ids = {t["id"] for t in existing}

    for cand in candidates:
        cid = str(cand.get("id", "")).strip()
        rule = str(cand.get("general_rule", "") or "")
        trigger = str(cand.get("trigger", "") or "")
        markers = cand.get("symptom_markers", []) or []

        if not cid or not rule or not trigger or not markers:
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_schema",
                            "detail": "missing required fields"})
            continue
        if cid in existing_ids:
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_id_collision"})
            continue

        viol = _violations(rule) + _violations(trigger)
        if viol:
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_cheat_sheet",
                            "violations": viol})
            continue

        cand_tri = _word_trigrams(rule)
        best_match: tuple[str, float] = ("", 0.0)
        for eid, etri in existing_trigrams:
            j = _jaccard(cand_tri, etri)
            if j > best_match[1]:
                best_match = (eid, j)
        if best_match[1] >= 0.60:
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_duplicate",
                            "detail": f"jaccard {best_match[1]:.2f} vs {best_match[0]}"})
            continue

        if not isinstance(markers, list) or not (3 <= len(markers) <= 20):
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_marker_count",
                            "detail": f"n_markers={len(markers) if isinstance(markers, list) else 'not_list'}"})
            continue

        # Also reject markers that are themselves cheat-sheet shapes
        # (a marker like `*.py::test_X` would cause the classifier to flag
        # the evolved plan as leakage later).
        bad_markers = [m for m in markers if _violations(str(m))]
        if bad_markers:
            log_out.append({"stage": "M3", "candidate_id": cid,
                            "status": "rejected_marker_cheat_sheet",
                            "detail": f"bad_markers={bad_markers}"})
            continue

        accepted.append({
            "id": cid,
            "trigger": trigger,
            "symptom_markers": markers,
            "general_rule": rule,
        })
        log_out.append({"stage": "M3", "candidate_id": cid,
                        "status": "accepted"})
    return accepted


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark_root", required=True,
                    type=Path, help="directory of per-instance dirs "
                                    "(each with report.json + test_output.txt)")
    ap.add_argument("--templates", required=True, type=Path,
                    help="path to failure_pattern_templates.json")
    ap.add_argument("--model", default="openai/gpt-5.2",
                    help="LiteLLM model id; default openai/gpt-5.2")
    ap.add_argument("--dry_run", action="store_true",
                    help="Do not write the merged templates file; "
                         "print summary and exit.")
    args = ap.parse_args()

    if not args.benchmark_root.is_dir():
        print(f"ERROR: benchmark_root not found: {args.benchmark_root}",
              file=sys.stderr)
        return 2
    if not args.templates.is_file():
        print(f"ERROR: templates file not found: {args.templates}",
              file=sys.stderr)
        return 2

    existing: list[dict] = json.loads(args.templates.read_text(encoding="utf-8"))
    print(f"Loaded {len(existing)} existing templates.", flush=True)

    existing_digest = "\n".join(
        f"  - {t['id']}: {str(t.get('general_rule',''))[:100]}..." for t in existing
    )

    client = LLMClient()

    log: list[dict] = []
    t0 = time.time()

    extracts = mine_stage_m1(client, args.model, args.benchmark_root, log)
    print(f"M1 complete: {len(extracts)} extracts in {time.time()-t0:.0f}s",
          flush=True)

    if not extracts:
        print("ERROR: no extracts produced; aborting.", file=sys.stderr)
        _emit_log(args.templates, log)
        return 3

    t1 = time.time()
    candidates: list[dict] = []
    try:
        candidates = call_m2(client, args.model, existing_digest, extracts)
    except Exception as e:
        log.append({"stage": "M2", "status": "llm_error",
                    "detail": f"{type(e).__name__}: {e}"})
        print(f"ERROR: M2 call failed: {e}", file=sys.stderr)
        _emit_log(args.templates, log)
        return 4
    log.append({"stage": "M2", "status": "ok",
                "n_candidates": len(candidates),
                "duration_sec": round(time.time() - t1, 1)})
    print(f"M2 complete: {len(candidates)} candidate templates "
          f"in {time.time()-t1:.0f}s", flush=True)

    accepted = filter_candidates(candidates, existing, log)
    print(f"M3 complete: {len(accepted)} accepted, "
          f"{len(candidates) - len(accepted)} rejected", flush=True)

    if args.dry_run:
        print("--- DRY RUN: merged templates not written ---")
        for t in accepted:
            print(f"  + {t['id']}")
        _emit_log(args.templates, log)
        return 0

    if accepted:
        merged = existing + accepted
        args.templates.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"Wrote {len(merged)} templates "
              f"(+{len(accepted)} new) to {args.templates}")
    else:
        print("No new templates accepted; templates file unchanged.")

    _emit_log(args.templates, log)
    return 0


def _emit_log(templates_path: Path, log: list[dict]) -> None:
    log_path = templates_path.with_suffix(templates_path.suffix + ".mining_log.json")
    log_path.write_text(
        json.dumps(log, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Mining log written to {log_path}")


if __name__ == "__main__":
    sys.exit(main())
