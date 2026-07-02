#!/usr/bin/env python3
"""migrate_lean_steptype.py — in-place migration of a generated Layer-2/3 `.lean` example from the OLD agent engine's StepType labelling to the NEW AgentSPEX labelling.

The generated examples are derived artifacts whose ONLY engine-coupled content is the `stepType := .X` field on each node. Rather than re-run the full IR->codegen pipeline (which would reflow the human-written comments the team uses as a provenance signal), this tool applies the minimal targeted edit:

  1. step/task SEMANTIC SWAP — `stepType := .step` <-> `stepType := .task`. The new engine makes `step` the STATEFUL action and `task` the STATELESS one, so a node that was stateful (old `.task`) becomes `.step`, matching the re-targeted Lean predicates (computeTaskChain / context-visibility key on `.step`). This is a verdict-preserving relabel: the static `native_decide` soundness theorems keep their value.
  2. FIVE DELETED step types — `.discover/.synthesize/.validate/.save/.evaluate` no longer exist; rewrite each to `.task` (the stateless primitive). NOTE: a node whose write variable carries a non-TString type (e.g. a `discover` writing `TList TJson`) will fail `writesConsistent` as a `.task`; such files need the IR-regen path (migrate_ir_to_new_engine.py) instead — this tool reports them so they are not silently mis-migrated.

Everything else in the file (structure, comments, namespaces, theorems, #evals) is byte-preserved.
"""

import argparse
import re
import sys

SWAP_PLACEHOLDER = "stepType := .__SWAP__"
DELETED = ["discover", "synthesize", "validate", "save", "evaluate"]
# A `.task`/`.step` node's single write must be TString-compatible; flag the structured ones for the IR path.
NON_TSTRING_WRITE = re.compile(r"\.TList\b|\.TFloat\b|\.TBool\b|\.TInt\b|\.TJson\b")


def migrate_text(text: str) -> tuple[str, dict]:
    stats = {"swap_step_to_task": 0, "swap_task_to_step": 0}
    # count before mutating (the placeholder dance hides direction otherwise)
    stats["swap_step_to_task"] = len(re.findall(r"stepType := \.step\b", text))
    stats["swap_task_to_step"] = len(re.findall(r"stepType := \.task\b", text))
    # swap .step <-> .task via a placeholder so the two replacements don't chase each other
    text = re.sub(r"stepType := \.step\b", SWAP_PLACEHOLDER, text)
    text = re.sub(r"stepType := \.task\b", "stepType := .step", text)
    text = text.replace(SWAP_PLACEHOLDER, "stepType := .task")
    # deleted types -> .task
    for d in DELETED:
        n = len(re.findall(rf"stepType := \.{d}\b", text))
        if n:
            stats[f"deleted_{d}_to_task"] = n
            text = re.sub(rf"stepType := \.{d}\b", "stepType := .task", text)
    return text, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="generated .lean example files to migrate in place")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    flagged = []
    for path in args.files:
        src = open(path).read()
        had_deleted = any(re.search(rf"stepType := \.{d}\b", src) for d in DELETED)
        out, stats = migrate_text(src)
        if had_deleted and NON_TSTRING_WRITE.search(src):
            flagged.append(path)
        if not args.dry_run:
            open(path, "w").write(out)
        changed = {k: v for k, v in stats.items() if v}
        print(f"[{'dry ' if args.dry_run else ''}migrate] {path}  {changed}")
    if flagged:
        print("\nWARNING — these files use a deleted step type AND a non-TString write; migrate them via migrate_ir_to_new_engine.py instead (write-type coercion):", file=sys.stderr)
        for f in flagged:
            print(f"  {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
