#!/usr/bin/env python3
"""
apply_amendments.py — deterministic post-step that walks the LLM's
amendments.json and applies each `new_instruction` to the working YAML plan.

Inputs:
  --amendments  path to amendments.json. Schema (a JSON list):
                  [
                    {"step_name": str,
                     "predicate_violated": str,            # informational
                     "new_instruction": str | null,        # null => skip
                     "amend": bool},                       # explicit gate
                    ...
                  ]
                Either `amend == true` AND `new_instruction` is a non-empty
                string, OR the entry is treated as `confirmed` (no edit).

  --working_plan_yaml  path to the staged working_plan.yaml that EditYaml.py
                       will mutate in place.

  --digest      path to amendments_digest.json. Each (step_index, step_name)
                with a successful edit is flipped from `confirmed` to
                `amended` so the Phase-5 plan_validator expects the change.

  --package_dir host path to the elaip_LeanEvolve package_files directory
                (so we can spawn EditYaml.py + EditJson.py via subprocess).

Behaviour:
  * Each amendment is applied via `EditYaml.py --set-by-name <name> '<JSON>'`
    where <JSON> is a JSON-encoded string (newlines as \n, quotes escaped).
  * Amendments referring to step names not present in the plan are reported
    but do not abort the script — the LLM occasionally hallucinates names.
  * The script is idempotent: re-running with the same amendments.json
    produces a byte-identical evolved plan.

Exit codes:
  0  success (one or more amendments applied OR all entries confirmed)
  1  fatal — invalid JSON, missing files, all amendments failed
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _coerce_amend(entry: dict) -> bool:
    """An entry should rewrite the step iff `amend == true` AND
    `new_instruction` is a non-empty string. The LLM occasionally returns
    `amend=false` together with a non-empty instruction — we treat that as
    "do not amend" (the LLM signalled confirmed)."""
    if not entry.get("amend"):
        return False
    new_instr = entry.get("new_instruction")
    return isinstance(new_instr, str) and new_instr.strip() != ""


def main() -> int:
    p = argparse.ArgumentParser(
        description="Apply amendments.json to a working YAML plan.")
    p.add_argument("--amendments", required=True,
                   help="Path to amendments.json emitted by Stage B.")
    p.add_argument("--working_plan_yaml", required=True,
                   help="Path to working_plan.yaml (mutated in place).")
    p.add_argument("--digest", required=True,
                   help="Path to amendments_digest.json (verdicts flipped here).")
    p.add_argument("--package_dir", required=True,
                   help="Host path to package_files/ (with EditYaml.py).")
    args = p.parse_args()

    amendments_path = Path(args.amendments)
    working_yaml = Path(args.working_plan_yaml)
    digest_path = Path(args.digest)
    package = Path(args.package_dir)
    edit_yaml = package / "EditYaml.py"
    edit_json = package / "EditJson.py"

    for tag, pp in [("--amendments", amendments_path),
                    ("--working_plan_yaml", working_yaml),
                    ("--digest", digest_path),
                    ("--package_dir/EditYaml.py", edit_yaml),
                    ("--package_dir/EditJson.py", edit_json)]:
        if not pp.exists():
            print(f"ERROR: {tag} not found: {pp}", file=sys.stderr)
            return 1

    try:
        amendments = json.loads(amendments_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: amendments.json is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(amendments, list):
        print(f"ERROR: amendments.json is not a list (got {type(amendments).__name__})",
              file=sys.stderr)
        return 1

    try:
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: digest is not valid JSON: {e}", file=sys.stderr)
        return 1

    # Build a step_name -> digest_index map so we can flip verdicts efficiently.
    digest_idx_by_name: dict[str, int] = {}
    for d_idx, d_rec in enumerate(digest):
        if isinstance(d_rec, dict) and "step_name" in d_rec:
            digest_idx_by_name[d_rec["step_name"]] = d_idx

    applied: list[str] = []
    skipped_confirmed: list[str] = []
    failed: list[tuple[str, str]] = []
    unknown_names: list[str] = []

    for entry in amendments:
        if not isinstance(entry, dict):
            failed.append(("<malformed>", f"entry not a dict: {entry!r}"))
            continue
        step_name = (entry.get("step_name") or "").strip()
        if not step_name:
            failed.append(("<missing>", "no step_name field"))
            continue
        if not _coerce_amend(entry):
            skipped_confirmed.append(step_name)
            continue
        new_instr = entry["new_instruction"]
        # JSON-encode the new instruction as a single string so EditYaml.py
        # parses it as JSON. EditYaml.py's --set-by-name expects a JSON-
        # encoded string literal as the next positional argument.
        encoded = json.dumps(new_instr, ensure_ascii=False)
        rc, _out, err = _run([
            sys.executable, str(edit_yaml),
            "--yaml_path", str(working_yaml),
            "--set-by-name", step_name,
            encoded,
        ])
        if rc != 0:
            # If EditYaml reports the step is missing from the plan, the LLM
            # hallucinated the name — record but don't fail the run.
            err_lower = err.lower()
            if ("not found" in err_lower or "no leaf" in err_lower
                    or "no step" in err_lower):
                unknown_names.append(step_name)
            else:
                failed.append((step_name, err.strip()[:300]))
            continue
        # Flip the digest verdict to `amended` if a digest entry exists.
        d_idx = digest_idx_by_name.get(step_name)
        if d_idx is not None:
            rc2, _o2, err2 = _run([
                sys.executable, str(edit_json),
                "--json_path", str(digest_path),
                "--path", json.dumps([d_idx, "verdict"]),
                "--set", json.dumps("amended"),
            ])
            if rc2 != 0:
                failed.append((step_name, f"digest flip rc={rc2}: {err2[:200]}"))
                continue
        applied.append(step_name)

    # Print a one-line summary suitable for the YAML's save_as variable.
    print(f"applied={len(applied)} confirmed={len(skipped_confirmed)} "
          f"unknown={len(unknown_names)} failed={len(failed)}")
    if applied:
        print(f"  applied: {applied}")
    if skipped_confirmed:
        print(f"  confirmed: {skipped_confirmed}")
    if unknown_names:
        print(f"  unknown step names (LLM hallucination): {unknown_names}")
    if failed:
        print("  failures:")
        for nm, msg in failed:
            print(f"    [{nm}] {msg}")

    if applied or (not failed and (skipped_confirmed or unknown_names)):
        return 0
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
