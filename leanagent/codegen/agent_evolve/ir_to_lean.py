#!/usr/bin/env python3
"""
ir_to_lean.py - Pure-Python Layer 3 IR -> Lean source codegen.

No Lean toolchain is required. The dynamic layer is the only path
(`AgentVerifier/DynamicVerification/`, namespace `AgenticKernel.Dyn`):

  * `ir_kind: "layer3_v2"` (the unified schema) and `ir_kind: "layer3"`
    (legacy SWE, from `leanagent/codegen/agent_evolve/layer3_ir_init.py`) are
    BOTH generated through `layer3_v2_codegen.generate_layer3_v2_lean`, which
    reads either shape (see its docstring) and emits the dynamic layer
    (`layer3ToJson` / `renderFullReport`).

The old generator (`TaskPlanToLean.generate_layer3_lean`, old
`AgentVerifier.DynamicVerification.*`) has been retired along with the V1
dynamic layer; everything now targets the dynamic layer.

CLI:
  python ir_to_lean.py --ir <layer3_ir.json> --out <per_step.lean>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEAN_VERIFIER_DIR = HERE.parent / "lean_verifier"
sys.path.insert(0, str(LEAN_VERIFIER_DIR))


def main():
    p = argparse.ArgumentParser(description="Generate a Layer 3 .lean file from an annotated IR JSON.")
    p.add_argument("--ir", required=True, help="Path to annotated Layer 3 IR JSON")
    p.add_argument("--out", required=True, help="Output .lean path")
    args = p.parse_args()

    ir_path = Path(args.ir).resolve()
    out_path = Path(args.out).resolve()
    if not ir_path.exists():
        print(f"ERROR: IR not found: {ir_path}", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(ir_path.read_text(encoding="utf-8"))
    kind = raw.get("ir_kind")
    if kind not in ("layer3", "layer3_v2"):
        print(f"ERROR: expected ir_kind in (layer3, layer3_v2), got {kind!r}", file=sys.stderr)
        sys.exit(1)

    try:
        import layer3_v2_codegen as L3V2  # type: ignore
    except Exception as e:
        print(f"ERROR: cannot import layer3_v2_codegen from {LEAN_VERIFIER_DIR}: {e}", file=sys.stderr)
        sys.exit(1)

    lean_source = L3V2.generate_layer3_v2_lean(raw)
    n_dyn = len(raw.get("dyn_nodes", []) or [])
    n_inj = len(raw.get("llm_injections", []) or [])
    mode = f"{L3V2._norm_layer2_ref(raw)['mode']}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(lean_source, encoding="utf-8")
    print(f"OK: Layer 3 Lean ({mode}) -> {out_path} "
          f"({n_dyn} dyn_nodes, {n_inj} llm_injections)")


if __name__ == "__main__":
    main()
