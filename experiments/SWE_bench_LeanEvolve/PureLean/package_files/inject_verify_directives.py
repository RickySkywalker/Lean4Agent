#!/usr/bin/env python3
"""Deterministic post-processor for the evolved YAML plan.

Stage B's LLM rewrite of the `verify_fix` step is deliberately
template/general so the plan can be reused across instances. But the
agent at run time needs to know which specific test(s) to consider as
the canonical pass/fail signal — otherwise it picks an arbitrary
neighbour test (we observed `test_i18n_app_dirs` ran instead of the
actual FAIL_TO_PASS `test_get_language_from_path_real`).

This script splices a small instance-specific block into the verify_fix
instruction:
  - the literal FAIL_TO_PASS test IDs from eval_evidence.tests.f2p_fail
  - a `python -c "from pkg import x"` import-sanity check after every
    edit, so syntactically broken patches surface immediately
  - a hard trigger: "if any of these IDs FAIL/ERROR, your fix is
    incomplete — return to fix_issue and look for sibling call-sites"

The block is bounded (≤ ~25 lines) and clearly marked, so it's easy to
audit and idempotent (running twice doesn't double-inject).

CLI:
  python inject_verify_directives.py \\
      --working_plan_yaml <path> \\
      --eval_evidence    <path>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

INJECT_HEADER = "<!-- BEGIN F2P_VERIFY_INJECTION (auto, do-not-edit) -->"
INJECT_FOOTER = "<!-- END F2P_VERIFY_INJECTION -->"
VERIFY_NAMES = {"verify_fix", "verify_solution", "validate_fix"}


def _format_test_id_for_django(t: str) -> str | None:
    """Django uses `runtests.py <module.ClassName.test_method>` rather
    than pytest paths. The eval reports surface unittest-style names like
    'test_X (pkg.tests.ClassY)' — convert to 'pkg.tests.ClassY.test_X'."""
    if "::" in t:
        # pytest style — leave as-is
        return t
    if "(" in t and t.endswith(")"):
        method, _, rest = t.partition("(")
        path = rest[:-1]
        return f"{path}.{method.strip()}"
    return t


def _build_block_minimal() -> str:
    """Zero-leakage minimal injection: just an import-sanity discipline.

    No instance-specific test IDs, no class names, no file paths.
    Targets the failure mode we observed in round 7: agent applies a
    semantically reasonable edit but breaks Python syntax via misaligned
    sed/heredoc, ships the broken file, eval rejects with
    `malformed patch` or unresolved tests.

    Kept terse (≤ ~2 sentences) so it never becomes the dominant
    fraction of the verify_fix instruction — round 11 showed that the
    longer version (with explicit revert recipes and a CRITICAL block)
    pushed Qwen3.5 to terminate verify_fix in a single iteration."""
    return (
        f"{INJECT_HEADER} "
        f"After every edit, run `python -c \"import <pkg>\"` "
        f"(substitute the patched package). If it exits non-zero or "
        f"prints a Traceback, the edit broke the file — revert and "
        f"redo with indentation preserved before continuing. "
        f"{INJECT_FOOTER}"
    )


def _build_block(f2p_fail: list[str], p2p_fail: list[str] | None = None,
                 failure_excerpts: list[dict] | None = None) -> str:
    p2p_fail = p2p_fail or []
    failure_excerpts = failure_excerpts or []
    pretty_f2p = [_format_test_id_for_django(str(t).strip())
                  for t in (f2p_fail or [])[:6] if t]
    pretty_p2p = [_format_test_id_for_django(str(t).strip())
                  for t in p2p_fail[:6] if t]

    f2p_block = "\n".join(f"  * `{tid}` (must PASS)" for tid in pretty_f2p) or \
                "  (no FAIL_TO_PASS failures captured; rely on PASS_TO_PASS regressions below)"
    p2p_block = "\n".join(f"  * `{tid}` (must NOT regress — was passing before)"
                          for tid in pretty_p2p)

    if pretty_p2p:
        tests_section = (
            f"{f2p_block}\n\n"
            f"And these PASS_TO_PASS tests must NOT regress (they were passing\n"
            f"before the agent's previous attempt; if your fix introduces a\n"
            f"regression here, the fix is wrong even if FAIL_TO_PASS now passes):\n\n"
            f"{p2p_block}"
        )
    else:
        tests_section = f2p_block

    # Try to surface the class names that appeared in failure tracebacks.
    # When the test traceback names a specific class, patches to OTHER classes
    # in the same file are almost certainly wasted (agent error mode we
    # observed: patched ResolvedOuterRef when bug was in Window).
    class_hints: list[str] = []
    for fe in failure_excerpts[:3]:
        for ln in (fe.get("excerpt_lines") or []):
            m = re.search(r"\bclass\s+([A-Z][A-Za-z0-9_]+)\s*[(:]", ln)
            if m:
                class_hints.append(m.group(1))
            m2 = re.search(r"in\s+([A-Z][A-Za-z0-9_]+)\.[a-z_]+\s*\(", ln)
            if m2:
                class_hints.append(m2.group(1))
    class_hints = list(dict.fromkeys(class_hints))[:6]

    if class_hints:
        class_warning = (
            "\n\nCLASS HINT (from failing test's traceback in failure_excerpts):\n"
            f"  Likely-affected class(es): {', '.join('`'+c+'`' for c in class_hints)}\n"
            "  BEFORE adding a new method, verify the class you patch is the\n"
            "  one whose methods appear in the failing test's traceback.\n"
            "  Adding `as_sqlite` / `__init__` / etc. to a neighbouring class\n"
            "  in the same file is invisible to the failing test."
        )
    else:
        class_warning = ""

    return f"""{INJECT_HEADER}

CANONICAL TEST CONTRACT (from eval_evidence):

{tests_section}{class_warning}

MANDATORY EXECUTION GATE: this verify step is NOT complete until you
have invoked `shell_run` at least twice in THIS step — once to re-run
`/testbed/reproduce_issue.py` and once to invoke the codebase's own
test runner against the canonical test ID(s) above. Do NOT respond
with `VERIFIED=true` or `VERIFIED=false` before issuing both shell_run
calls in this step. Reusing a result from a previous step is invalid;
the verification must be observed in this step's tool output.

After every edit, run a quick import-sanity check (`python -c "import
<pkg>"` — substitute the patched package, e.g. `django`, `sklearn`,
`sympy`). Then run the canonical test ID(s) above using the codebase's
own runner (`python tests/runtests.py <dotted.ID> -v 2` for Django,
`python -m pytest <path::ID> -xvs` for pytest projects).

If the canonical IDs still show FAIL/ERROR after your edit: identify
the CLASS the failing test instantiates (`grep -rn 'def test_<name>'
tests/` then read the test body). Your patch must be on THAT class —
adding methods to a sibling class in the same module is invisible to
the test. Return to fix_issue, do NOT submit.

<CRITICAL>The fix is complete iff every canonical test ID above passes
and no previously-passing test regressed. A passing reproduction
script alone is NOT sufficient. If you respond with VERIFIED=... in
this step without first running the canonical test ID(s) via
shell_run in this same step, set VERIFIED=false.</CRITICAL>

{INJECT_FOOTER}"""


def inject(plan_yaml_path: Path, eval_evidence_path: Path,
           rich: bool = False) -> int:
    if not plan_yaml_path.exists():
        print(f"ERROR: plan {plan_yaml_path} not found", file=sys.stderr)
        return 2
    if not eval_evidence_path.exists():
        print(f"ERROR: eval_evidence {eval_evidence_path} not found",
              file=sys.stderr)
        return 2

    eval_evidence = json.loads(eval_evidence_path.read_text(encoding="utf-8"))
    f2p_fail = (eval_evidence.get("tests") or {}).get("f2p_fail") or []
    p2p_fail = (eval_evidence.get("tests") or {}).get("p2p_fail") or []
    failure_excerpts = eval_evidence.get("failure_excerpts") or []
    if eval_evidence.get("resolved") is True:
        print("OK: instance already resolved — skipping injection.")
        return 0

    text = plan_yaml_path.read_text(encoding="utf-8")
    if INJECT_HEADER in text:
        print("OK: F2P injection already present (idempotent skip).")
        return 0

    if rich:
        block = _build_block(f2p_fail, p2p_fail, failure_excerpts).rstrip() + "\n"
    else:
        block = _build_block_minimal().rstrip() + "\n"

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    injected = 0
    while i < n:
        line = lines[i]
        out.append(line)
        # Look for `name: verify_fix` (indented under a task)
        stripped = line.strip()
        if stripped.startswith("name:") and any(
            v in stripped for v in VERIFY_NAMES
        ):
            # Walk forward: find the next `instruction: |` line.
            j = i + 1
            while j < n and "instruction:" not in lines[j]:
                # Bail if we hit the next step (`- task:` or `- step:`)
                if lines[j].lstrip().startswith(("- task:", "- step:")):
                    j = n  # cancel
                    break
                j += 1
            if j >= n:
                i += 1
                continue
            # Determine literal-block indent. The instruction key is at
            # some indent X; its body is indented X + 4 (YAML convention
            # in this repo). Capture indent from first non-empty body line.
            instr_indent = None
            k = j + 1
            while k < n:
                b = lines[k]
                if not b.strip():
                    k += 1
                    continue
                instr_indent = len(b) - len(b.lstrip())
                break
            if instr_indent is None:
                i += 1
                continue
            # Find end of literal block: a line whose indent < instr_indent
            # AND is non-empty.
            end = k
            while end < n:
                b = lines[end]
                if b.strip() and (len(b) - len(b.lstrip())) < instr_indent:
                    break
                end += 1
            # Insert our block right before `end`. Indent each block line.
            indented = "\n".join(
                (" " * instr_indent) + ln if ln.strip() else ln
                for ln in block.splitlines()
            ) + "\n"
            # Append everything between i+1 .. end-1, then the block, then end.
            out.extend(lines[i + 1:end])
            out.append(indented)
            i = end
            injected += 1
            continue
        i += 1

    if not injected:
        print("WARNING: no verify_fix step matched; plan unchanged.",
              file=sys.stderr)
        return 0

    plan_yaml_path.write_text("".join(out), encoding="utf-8")
    print(f"OK: F2P verify directives injected into {injected} step(s) "
          f"of {plan_yaml_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--working_plan_yaml", required=True, type=Path)
    p.add_argument("--eval_evidence", required=True, type=Path)
    p.add_argument("--rich-injection", action="store_true",
                   help="Use the rich injection block that names canonical "
                        "FAIL_TO_PASS test IDs and adds a mandatory "
                        "shell_run-twice gate. Default off (minimal "
                        "import-sanity-only block).")
    args = p.parse_args()
    return inject(args.working_plan_yaml, args.eval_evidence,
                  rich=args.rich_injection)


if __name__ == "__main__":
    sys.exit(main())
