#!/usr/bin/env python3
"""summarize_ir.py - One-line summary of a Layer 3 IR JSON for status reporting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description="Print a one-line Layer 3 IR summary.")
    p.add_argument("--ir", required=True, help="Path to Layer 3 IR JSON")
    args = p.parse_args()

    path = Path(args.ir).resolve()
    if not path.exists():
        print(f"MISSING: {path}")
        sys.exit(1)

    ir = json.loads(path.read_text(encoding="utf-8"))
    n_dyn = len(ir.get("dyn_nodes", []))
    n_exec = len(ir.get("exec_state", []))
    n_inj = len(ir.get("llm_injections", []))
    prefix = ir.get("prefix", "")
    suffix = ir.get("suffix", "")
    print(f"Layer 3 IR ready at {path} — dyn_nodes={n_dyn}, "
          f"exec_state_entries={n_exec}, llm_injections={n_inj}, "
          f"prefix={prefix!r}, suffix={suffix!r}")


if __name__ == "__main__":
    main()
