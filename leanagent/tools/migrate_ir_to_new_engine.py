#!/usr/bin/env python3
"""migrate_ir_to_new_engine.py — one-time migration of a Layer-2/3 IR JSON from the OLD agent engine's type model to the NEW AgentSPEX engine's type model.

Two changes, matching the Lean type-model migration:
  1. step/task SEMANTIC SWAP — the new engine swaps the roles: `step` is now the STATEFUL action (persistent conversation history) and `task` is the STATELESS fresh call. The old IRs encode stateful nodes as `task`; flip every `step`<->`task` so a stateful node (old `task`) becomes `step`, matching the re-targeted Lean predicates (taskChain/context-visibility key on `.step`).
  2. FIVE DELETED step types — `discover/synthesize/validate/save/evaluate` no longer exist in the new parser/StepType. Map each to the stateless `task` primitive (one-shot, no conversation history) and coerce any structured write type to `TString` so the node satisfies the `task` writesConsistent rule (a serialized JSON list is consumed downstream by `for_each`'s TString branch). This is the D2 "old plans no longer verifiable in their original form (accepted)" semantic loss, applied mechanically.

The codegen itself stays a faithful 1:1 tool (a NEW-format plan's `step:` maps straight to `.step`); the swap lives here, in the historical-data migration, not in the codegen.
"""

import argparse
import collections
import json
import sys

STEP_TASK_SWAP = {"step": "task", "task": "step"}
DELETED_TYPES = {"discover", "synthesize", "validate", "save", "evaluate"}
# A `task` (or `step`) node's single write must be TString-compatible; structured outputs from the deleted LLM step types are re-modelled as serialized text.
TSTRING_OK = {"TString", "TUnknown"}


def migrate_node(n: dict) -> str | None:
    """Mutate one IR node in place. Returns the kind of change applied (for stats), or None if untouched."""
    st = n.get("step_type")
    if st in STEP_TASK_SWAP:
        n["step_type"] = STEP_TASK_SWAP[st]
        return f"swap:{st}->{n['step_type']}"
    if st in DELETED_TYPES:
        n["step_type"] = "task"
        for w in (n.get("writes") or []):
            bt = (w.get("base_type") or "").strip()
            if bt not in TSTRING_OK:
                w["base_type"] = "TString"
        return f"deleted:{st}->task"
    return None


def migrate_ir(ir: dict) -> collections.Counter:
    stats = collections.Counter()
    for n in ir.get("nodes", []):
        change = migrate_node(n)
        if change:
            stats[change] += 1
    # Layer-3 IRs carry a nested workflow + dyn_nodes block; migrate those node lists too.
    wf = ir.get("workflow")
    if isinstance(wf, dict):
        for n in wf.get("nodes", []):
            change = migrate_node(n)
            if change:
                stats["wf:" + change] += 1
    for dn in ir.get("dyn_nodes", []):
        st = dn.get("step_type")
        if st in STEP_TASK_SWAP:
            dn["step_type"] = STEP_TASK_SWAP[st]
            stats[f"dyn:swap:{st}"] += 1
        elif st in DELETED_TYPES:
            dn["step_type"] = "task"
            stats[f"dyn:deleted:{st}"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="input IR JSON (old type model)")
    ap.add_argument("--out", required=True, help="output IR JSON (new type model)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    ir = json.load(open(args.inp))
    stats = migrate_ir(ir)
    json.dump(ir, open(args.out, "w"), indent=2)
    if not args.quiet:
        print(f"[migrate_ir] {args.inp} -> {args.out}  changes={dict(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
