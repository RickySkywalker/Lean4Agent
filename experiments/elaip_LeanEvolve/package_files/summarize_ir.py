#!/usr/bin/env python3
"""
summarize_ir.py — One-line ELAIP Layer-3 IR summary for the annotator's
final phase.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ir", required=True, help="Path to layer3_ir.json")
    args = p.parse_args()
    ir = json.loads(Path(args.ir).read_text(encoding="utf-8"))
    n_dyn = len(ir.get("dyn_nodes") or [])
    n_paired = sum(1 for d in (ir.get("dyn_nodes") or [])
                   if d.get("execution_status") == "completed")
    n_skipped = sum(1 for d in (ir.get("dyn_nodes") or [])
                    if d.get("execution_status") == "skipped")
    n_exec = len(ir.get("exec_state") or [])
    n_inj = len(ir.get("llm_injections") or [])
    holds_true = sum(1 for inj in (ir.get("llm_injections") or [])
                     if (inj.get("holds") is True
                         or (isinstance(inj.get("judgement"), dict)
                             and inj["judgement"].get("holds") is True)))
    holds_false = n_inj - holds_true
    print(f"OK: ELAIP Layer-3 IR plan={ir.get('plan_name')} qid={ir.get('question_id')} "
          f"dyn_nodes={n_dyn} (paired={n_paired}, skipped={n_skipped}) "
          f"exec_state={n_exec} llm_injections={n_inj} "
          f"(holds_true={holds_true}, holds_false={holds_false})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
