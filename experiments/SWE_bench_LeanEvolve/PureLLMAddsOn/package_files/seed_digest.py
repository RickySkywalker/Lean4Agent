#!/usr/bin/env python3
"""
seed_digest.py - Initialise amendments_digest.json for a plan being evolved.

Walks the original YAML plan's workflow and emits a list of
`{step_index, step_name, verdict: "confirmed"}` entries, one per instruction-
bearing leaf step. The per-step rewrite loop in the evolve workflow overwrites
individual entries' `verdict` to `"amended"` as it rewrites instructions.

The resulting digest is consumed by `plan_validator.py` in Phase 5 to decide
which steps must stay byte-identical (confirmed) and which must differ
(amended).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from plan_validator import _flatten_leaves  # type: ignore  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed amendments_digest.json.")
    ap.add_argument("--yaml", required=True, help="Path to the original YAML plan.")
    ap.add_argument("--out", required=True, help="Path to write amendments_digest.json.")
    args = ap.parse_args()

    yaml_path = Path(args.yaml)
    out_path = Path(args.out)

    plan = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    leaves = _flatten_leaves(plan.get("workflow") or [])
    digest = [
        {"step_index": i, "step_name": name, "verdict": "confirmed"}
        for i, (name, _instr) in enumerate(leaves)
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(digest, indent=2) + "\n", encoding="utf-8")
    print(f"OK: seeded {len(digest)} step(s) into {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
