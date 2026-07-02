#!/usr/bin/env python3
"""
eval_forensics.py - Extract concise failure evidence from a SWE-bench evaluation.

Inputs:
  report.json       SWE-bench evaluation report (keyed by instance_id).
  test_output.txt   Raw pytest / Django test harness output.

Output:
  eval_evidence.json under the staging dir. Schema:

{
  "instance_id": "django__django-14140",
  "resolved": false,
  "patch_exists": true,
  "patch_successfully_applied": true,
  "tests": {
    "f2p_pass": [...], "f2p_fail": [...],
    "p2p_pass_count": 200, "p2p_fail": [...],
    "f2f_fail": [...], "p2f_fail": [...]
  },
  "failure_excerpts": [
    { "test": "queries.test_q.QTests.test_deconstruct",
      "header": "FAIL: test_deconstruct (queries.test_q.QTests)",
      "excerpt_lines": ["Traceback ...", "  File ...", "AssertionError: ..."] }
  ],
  "summary_tail": ["Ran 207 tests in 0.324s", "FAILED (failures=2, skipped=2)"]
}

The file aims to stay under ~4 KB so per-step LLM calls can cite it verbatim.
Long PASS_TO_PASS lists are represented by a count only; only failures and
short success lists are preserved in full.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Strip ANSI color/style escape sequences before matching. Some SWE-bench test
# runners (scikit-learn + sphinx seen in Kimi-K2.5 run) emit colorised output
# that breaks `FAILED` and `=== short test summary info ===` regex anchors.
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


# unittest-style:  "FAIL: test_method (pkg.tests.Class)"  or  "ERROR: setUpClass (...)"
UNITTEST_HEADER_RE = re.compile(r"^(FAIL|ERROR): (\S+)\s*(\(([^)]+)\))?", re.MULTILINE)

# pytest section markers — "=== FAILURES ===", "=== ERRORS ===".
PYTEST_SECTION_START_RE = re.compile(r"^=+\s*(FAILURES|ERRORS)\s*=+\s*$")
# pytest section end markers — any of these close a FAILURES/ERRORS block.
PYTEST_SECTION_END_RE = re.compile(
    r"^(=+\s*(PASSES|short test summary info|warnings summary|slowest|"
    r"\d+ (failed|passed|error|skipped|warning).*?)\s*=+\s*$"
    r"|>>>>>\s*End Test Output.*)",
    re.IGNORECASE,
)
# pytest per-test block header:  "______ test_name ______"  (underscores around name).
# At least 3 underscores on each side; test name may contain spaces and dots.
PYTEST_BLOCK_HEADER_RE = re.compile(r"^_{3,}\s+(\S.*?)\s+_{3,}\s*$")

# pytest "FAILED test_id [- short_error]" summary lines near the end of output.
PYTEST_FAILED_SUMMARY_RE = re.compile(
    r"^(FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$"
)

# sympy bin/test custom format:
#   ________________________________________________________________________________
#   ____________ sympy/printing/tests/test_pycode.py:test_MpmathPrinter ____________
# The first line is a pure-underscore separator; the second has the test id.
SYMPY_SEP_RE = re.compile(r"^_{40,}\s*$")

SUMMARY_LINE_RE = re.compile(
    r"^(Ran \d+ tests? in [\d.]+s.*"
    r"|OK$"
    r"|FAILED.*"
    r"|ERRORS?.*"
    r"|PASSED.*"
    r"|Destroying test database.*"
    r"|=+\s*\d+ (failed|passed|error).*=+)",
    re.MULTILINE,
)


def _trim_block(block: list[str], excerpt_lines: int) -> list[str]:
    """Collapse runs of blank lines; keep head + error-bearing tail if oversized."""
    trimmed: list[str] = []
    for b in block:
        if not b.strip() and trimmed and not trimmed[-1].strip():
            continue
        trimmed.append(b)
    if len(trimmed) <= excerpt_lines:
        return trimmed
    # Prefer to keep assertion / "E   " / "Error:" / "AssertionError" lines.
    # Keep first half head, last half tail — error lines tend to sit at the end
    # of a pytest block ("E   AssertionError: ..." then "file.py:42: Error").
    head_n = max(3, excerpt_lines // 3)
    tail_n = excerpt_lines - head_n - 1
    return (
        trimmed[:head_n]
        + [f"... [+{len(trimmed) - head_n - tail_n} lines elided]"]
        + trimmed[-tail_n:]
    )


def _extract_pytest_blocks(
    lines: list[str], start_idx: int, max_excerpts: int, excerpt_lines: int
) -> tuple[list[dict], int]:
    """Starting at a `= FAILURES =` / `= ERRORS =` header line, emit one record
    per `____ name ____` block until the section ends. Returns (records, end_idx)."""
    results: list[dict] = []
    header_line = lines[start_idx]
    kind = "FAIL" if "FAILURES" in header_line else "ERROR"

    i = start_idx + 1
    # Walk to each per-test block header.
    while i < len(lines):
        ln = lines[i]
        if PYTEST_SECTION_END_RE.match(ln):
            return results, i
        m = PYTEST_BLOCK_HEADER_RE.match(ln)
        if not m:
            i += 1
            continue
        if len(results) >= max_excerpts:
            # Consume remaining section without emitting.
            i += 1
            continue
        test_name = m.group(1).strip()
        # Skip noise like "PASSES" marker lines that look like underscore blocks.
        if re.fullmatch(r"_+", test_name):
            i += 1
            continue
        header = ln.rstrip()
        block: list[str] = []
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if PYTEST_SECTION_END_RE.match(nxt):
                break
            if PYTEST_BLOCK_HEADER_RE.match(nxt):
                break
            block.append(nxt.rstrip())
            j += 1
        results.append({
            "kind": kind,
            "test": test_name,
            "header": header,
            "excerpt_lines": _trim_block(block, excerpt_lines),
        })
        i = j
    return results, i


def _extract_unittest_blocks(
    lines: list[str], max_excerpts: int, excerpt_lines: int
) -> list[dict]:
    """Handle unittest '====\\nFAIL: test ...\\n----' blocks anywhere in output."""
    results: list[dict] = []
    for i, line in enumerate(lines):
        if len(results) >= max_excerpts:
            break
        m = UNITTEST_HEADER_RE.match(line)
        if not m:
            continue
        kind = m.group(1)
        test_method = m.group(2)
        test_class = m.group(4) or ""
        block: list[str] = []
        j = i + 1
        # unittest blocks end at the next '===' separator or a blank after Tb.
        while j < len(lines) and j - i <= excerpt_lines * 3:
            nxt = lines[j]
            if re.match(r"^=+\s*$", nxt):
                break
            if UNITTEST_HEADER_RE.match(nxt):
                break
            block.append(nxt.rstrip())
            j += 1
        full_name = f"{test_class}.{test_method}" if test_class else test_method
        results.append({
            "kind": kind,
            "test": full_name,
            "header": line.rstrip(),
            "excerpt_lines": _trim_block(block, excerpt_lines),
        })
    return results


def _extract_sympy_blocks(
    lines: list[str], max_excerpts: int, excerpt_lines: int
) -> list[dict]:
    """sympy bin/test emits two underscore lines around a test id:
           ________________________________________________________________________________
           ____________ sympy/printing/tests/test_pycode.py:test_MpmathPrinter ____________
       Followed by a Python-style Traceback.
    """
    results: list[dict] = []
    i = 0
    while i < len(lines) - 1:
        if len(results) >= max_excerpts:
            break
        if SYMPY_SEP_RE.match(lines[i]):
            m = PYTEST_BLOCK_HEADER_RE.match(lines[i + 1])
            if m:
                test_name = m.group(1).strip()
                header = lines[i + 1].rstrip()
                block: list[str] = []
                j = i + 2
                while j < len(lines) and j - i <= excerpt_lines * 3:
                    nxt = lines[j]
                    if SYMPY_SEP_RE.match(nxt):
                        break
                    if nxt.startswith("=== tests finished"):
                        break
                    block.append(nxt.rstrip())
                    j += 1
                results.append({
                    "kind": "FAIL",
                    "test": test_name,
                    "header": header,
                    "excerpt_lines": _trim_block(block, excerpt_lines),
                })
                i = j
                continue
        i += 1
    return results


def _extract_failed_summary_lines(
    lines: list[str], already_captured: set[str], max_excerpts: int
) -> list[dict]:
    """Pytest summary-only form (common with --tb=no or truncated output):
           FAILED tests/foo.py::test_x - AssertionError: foo != bar
       Emits one minimal record per test id not yet captured."""
    results: list[dict] = []
    for ln in lines:
        if len(results) >= max_excerpts:
            break
        m = PYTEST_FAILED_SUMMARY_RE.match(ln.rstrip())
        if not m:
            continue
        kind = m.group(1) if m.group(1) == "ERROR" else "FAIL"
        test_id = m.group(2)
        short_err = (m.group(3) or "").strip()
        # Skip if we already captured this test via a richer block.
        if any(test_id in cap or cap in test_id for cap in already_captured):
            continue
        excerpt = [short_err] if short_err else ["(no short message; see raw test_output)"]
        results.append({
            "kind": kind,
            "test": test_id,
            "header": ln.rstrip(),
            "excerpt_lines": excerpt,
        })
    return results


def extract_failures(test_output: str, max_excerpts: int = 6, excerpt_lines: int = 15
                     ) -> list[dict]:
    """Return a short list of failure blocks with truncated excerpts.

    Handles four formats seen in SWE-bench traces:
      - pytest FAILURES/ERRORS sections with `____ name ____` blocks
      - unittest `FAIL:` / `ERROR:` headers
      - sympy bin/test custom separator-pair format
      - pytest tail summary `FAILED test_id - short_err` (fallback)

    Emits results in deduplicated order, richer blocks first."""
    test_output = _strip_ansi(test_output)
    lines = test_output.splitlines()
    results: list[dict] = []

    # 1) pytest FAILURES / ERRORS section (richest source when present).
    for i, line in enumerate(lines):
        if len(results) >= max_excerpts:
            break
        if PYTEST_SECTION_START_RE.match(line):
            section_results, _ = _extract_pytest_blocks(
                lines, i, max_excerpts - len(results), excerpt_lines
            )
            results.extend(section_results)

    # 2) sympy bin/test separator-pair format.
    if len(results) < max_excerpts:
        results.extend(
            _extract_sympy_blocks(lines, max_excerpts - len(results), excerpt_lines)
        )

    # 3) unittest-style FAIL:/ERROR: blocks.
    if len(results) < max_excerpts:
        results.extend(
            _extract_unittest_blocks(lines, max_excerpts - len(results), excerpt_lines)
        )

    # 4) Fallback: pytest summary lines for tests not yet captured.
    if len(results) < max_excerpts:
        captured = {r["test"] for r in results}
        results.extend(
            _extract_failed_summary_lines(lines, captured, max_excerpts - len(results))
        )

    # Deduplicate by (test, header) keeping the first (richest) record.
    seen: set[tuple[str, str]] = set()
    dedup: list[dict] = []
    for r in results:
        key = (r.get("test", ""), r.get("header", "")[:80])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup[:max_excerpts]


def extract_summary_tail(test_output: str, max_lines: int = 8) -> list[str]:
    out: list[str] = []
    for m in SUMMARY_LINE_RE.finditer(_strip_ansi(test_output)):
        out.append(m.group(0).strip())
    if len(out) > max_lines:
        out = out[-max_lines:]
    return out


def pick_instance_block(report: dict, instance_id: str) -> dict | None:
    if instance_id in report:
        return report[instance_id]
    if len(report) == 1:
        return next(iter(report.values()))
    return None


def main():
    p = argparse.ArgumentParser(description="Extract eval evidence from SWE-bench results.")
    p.add_argument("--report", required=True, help="Path to report.json")
    p.add_argument("--test_output", required=True, help="Path to test_output.txt")
    p.add_argument("--staging_dir", required=True, help="Output directory (will be created)")
    p.add_argument("--instance_id", default="", help="Instance id (for report key lookup)")
    p.add_argument("--max_f2p_success", type=int, default=40,
                   help="If F2P success list is longer than this, keep a count only")
    args = p.parse_args()

    report_path = Path(args.report).resolve()
    test_out_path = Path(args.test_output).resolve()
    staging = Path(args.staging_dir).resolve()
    staging.mkdir(parents=True, exist_ok=True)

    if not report_path.exists():
        print(f"ERROR: report.json not found: {report_path}", file=sys.stderr)
        sys.exit(1)
    if not test_out_path.exists():
        print(f"ERROR: test_output.txt not found: {test_out_path}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_path.read_text(encoding="utf-8"))

    instance_id = args.instance_id
    if not instance_id:
        if len(report) == 1:
            instance_id = next(iter(report.keys()))
        else:
            print("ERROR: report.json has multiple keys; pass --instance_id", file=sys.stderr)
            sys.exit(1)

    block = pick_instance_block(report, instance_id)
    if block is None:
        print(f"ERROR: instance_id {instance_id!r} not found in report.json "
              f"(available: {list(report.keys())})", file=sys.stderr)
        sys.exit(1)

    tests_status = block.get("tests_status", {}) or {}

    def _get(key, bucket):
        return (tests_status.get(key, {}) or {}).get(bucket, []) or []

    f2p_success = _get("FAIL_TO_PASS", "success")
    f2p_failure = _get("FAIL_TO_PASS", "failure")
    p2p_success = _get("PASS_TO_PASS", "success")
    p2p_failure = _get("PASS_TO_PASS", "failure")
    f2f_failure = _get("FAIL_TO_FAIL", "failure")
    p2f_failure = _get("PASS_TO_FAIL", "failure")

    if len(f2p_success) > args.max_f2p_success:
        f2p_success_out = {"count": len(f2p_success),
                           "first_5": f2p_success[:5]}
    else:
        f2p_success_out = f2p_success

    test_output = test_out_path.read_text(encoding="utf-8", errors="replace")
    failures = extract_failures(test_output)
    tail = extract_summary_tail(test_output)

    evidence = {
        "instance_id": instance_id,
        "report_path": str(report_path),
        "test_output_path": str(test_out_path),
        "resolved": bool(block.get("resolved", False)),
        "patch_exists": bool(block.get("patch_exists", False)),
        "patch_is_None": bool(block.get("patch_is_None", False)),
        "patch_successfully_applied": bool(block.get("patch_successfully_applied", False)),
        "tests": {
            "f2p_pass": f2p_success_out,
            "f2p_fail": f2p_failure,
            "p2p_pass_count": len(p2p_success),
            "p2p_fail": p2p_failure,
            "f2f_fail": f2f_failure,
            "p2f_fail": p2f_failure,
        },
        "failure_excerpts": failures,
        "summary_tail": tail,
    }

    out_path = staging / "eval_evidence.json"
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK: eval evidence -> {out_path} "
          f"(resolved={evidence['resolved']}, "
          f"F2P fail={len(f2p_failure)}, P2P fail={len(p2p_failure)}, "
          f"failure_excerpts={len(failures)})")


if __name__ == "__main__":
    main()
