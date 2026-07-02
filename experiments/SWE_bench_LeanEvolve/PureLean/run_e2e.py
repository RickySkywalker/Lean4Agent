#!/usr/bin/env python3
"""
run_e2e.py - DEPRECATED.

The end-to-end Lean-guided plan-evolution pipeline for SWE-Bench is now a single
self-contained orchestrator at:

    experiments/SWE_bench_LeanEvolve/PureLean/run.py

`run.py` runs Stage A (annotate) and Stage B (evolve) per instance — using the
relocated helpers in `package_files/` and dispatching `annotate_layer3.yaml` /
`evolve_plan.yaml` via `package_files/yaml_runner.run_yaml_agent` — then spawns
the sibling `rerun.py` for Stage C (the SWE-bench Docker rerun). It no longer
depends on `leanagent/codegen/agent_evolve/{run_agent_evolve,run_plan_evolve}.py`.

This module used to chain four standalone driver subprocesses (annotate ->
evolve -> rerun -> evaluate). It is kept only as a pointer so existing
invocations fail loudly with migration guidance instead of silently running
stale code.

ARG MIGRATION (run_e2e.py -> run.py):
    --plan-name                 (unchanged)
    --original-plan-yaml        (unchanged)
    --source-outputs-root       (unchanged)
    --source-eval-root          (unchanged)
    --source-layer2-ir          (unchanged)
    --dataset / --split / --model               (unchanged)
    --limit / --max-parallel                    (unchanged)
    --stage-c-output-dir        (unchanged)
    --unified-staging-root      (unchanged; now MUST be under <repo>/workspace/)
    --single-instance X         ->  --instance-ids X
    --instance-ids a,b          (unchanged)
    --no-run-lean               (unchanged)
    --verifier-dir              ->  --verifier-dir (unchanged)
    --per-instance-timeout-sec / --idle-timeout-sec   (unchanged)
    --fresh                     (unchanged)
    --start-stage / --only-stage {annotate,evolve,rerun,evaluate}
                                ->  --only-stage {A,B,annotate,evolve} (Stage C
                                    runs after A+B unless --only-stage is A/B);
                                    the separate swebench `evaluate` stage is no
                                    longer orchestrated here — run
                                    `python -m swebench.harness.run_evaluation`
                                    on <stage-c-output-dir>/predictions.jsonl.
    --stage-a-results-dir       ->  --results-dir
    --stage-b-smoke-test-dir    ->  --durable-plans-dir
    --stage-a-staging-root / --stage-b-staging-root / --workspace-root
                                ->  derived automatically under
                                    --unified-staging-root.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_NEW = HERE / "run.py"

_MSG = f"""\
============================================================================
  experiments/SWE_bench_LeanEvolve/PureLean/run_e2e.py is DEPRECATED.

  Use the self-contained orchestrator instead:

      python -u {_NEW}  <args>

  See the module docstring at the top of this file for the run_e2e -> run.py
  argument migration table, and `python {_NEW} --help`.
============================================================================
"""


def main() -> int:
    sys.stderr.write(_MSG)
    sys.stderr.write(
        "Refusing to run the removed four-driver pipeline. Re-invoke run.py.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
