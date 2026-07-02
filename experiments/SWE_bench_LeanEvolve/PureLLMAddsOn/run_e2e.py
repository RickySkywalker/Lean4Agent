#!/usr/bin/env python3
"""
run_e2e.py - End-to-end orchestrator for the LLM-only plan-evolution baseline.

Chains three stages:

    STAGE B (evolve)   -> experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run.py
        Reads a prior SWE-bench run's trajectories + eval results and
        emits per-instance evolved YAML plans into a durable directory.

    STAGE C (rerun)    -> experiments/SWE_bench_LeanEvolve/PureLean/run.py
        Runs the evolved YAML plans on the SWE-bench dataset, produces
        per-instance diffs and predictions.jsonl.

    STAGE D (evaluate) -> python -m swebench.harness.run_evaluation
        Optional. Submits predictions.jsonl to the SWE-bench harness and
        writes a report.json + test_output.txt for each instance. Skipped
        unless --run-eval is passed.

Stage "A" (Lean-arm's Layer-3 auto-annotation) does not exist here: the
LLM-only arm folds per-step trajectory reasoning directly into Stage B's
YAML workflow.

Resume semantics:

  - Default (intermediate resume): each sub-stage is invoked with its
    own `--resume` flag, so per-instance work already completed is
    skipped. Interrupt the pipeline anywhere and re-run the same
    command to pick up from where it left off.

  - Resume from scratch: pass `--fresh` to drop `--resume` from each
    sub-stage so every instance is re-processed. Does NOT delete any
    artifacts on disk; combine with a manual `rm -rf` of the staging
    dirs if you want a true clean slate.

  - Skip ahead: `--start-stage {evolve,rerun,evaluate}` begins at the
    named stage and assumes earlier stages have already produced their
    artifacts.

  - Single stage: `--only-stage X` runs just one stage and stops.

Invocation (typical):

    source ./experiments/SWE_bench_verified/gpt5.2_config.env
    python -u experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run_e2e.py \\
        --plan-name passed_workflow_1 \\
        --original-plan-yaml ./experiments/SWE_bench_verified/passed_workflow_1.yaml \\
        --source-outputs-root ./outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \\
        --source-eval-root   ./benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1/gpt-5.2 \\
        --dataset ./data/test_dataset/SWE_bench_verified_50problems_subset \\
        --split   test \\
        --model   gpt-5.2 \\
        --unified-staging-root ./outputs/llm_evolve/gpt-5.2/passed_workflow_1 \\
        --limit 10 --max-parallel 10 --skip-resolved --run-eval
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Sequence

# Repo root: the Lean4Agent repo (contains FormalAgentLib/, leanagent/, experiments/, engine/)
HERE = Path(__file__).resolve().parent
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())

STAGE_ORDER = ("evolve", "rerun", "evaluate")

# Sub-stage driver paths (relative to repo root). Both live inside this merged,
# self-contained package.
STAGE_B_DRIVER = "experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run.py"
# Stage C is the per-instance SWE-bench Docker rerun runner from the Lean arm.
STAGE_C_DRIVER = "experiments/SWE_bench_LeanEvolve/PureLean/rerun.py"


@dataclass
class StageResult:
    name: str
    returncode: int
    skipped: bool
    duration_sec: float


def _abspath(p: str | Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO_ROOT / pp).resolve()


def _print_banner(title: str) -> None:
    bar = "=" * 80
    print(f"\n{bar}\n{title}\n{bar}", flush=True)


def _run_subprocess(cmd: Sequence[str], *, cwd: Path, env_extra: dict | None = None,
                    dry_run: bool) -> int:
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"$ (cd {cwd} && {printable})", flush=True)
    if dry_run:
        return 0
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    rc = subprocess.run(list(cmd), cwd=str(cwd), env=env).returncode
    return rc


def _model_slug(model: str) -> str:
    """'gpt-5.2' -> 'gpt52', 'claude-sonnet-4-6' -> 'claudesonnet46'."""
    return "".join(ch for ch in model.lower() if ch.isalnum())


# ---------------------------------------------------------------------------
# STAGE B - evolve (experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run.py)
# ---------------------------------------------------------------------------
def stage_b_evolve(args) -> int:
    driver = REPO_ROOT / STAGE_B_DRIVER
    if not driver.exists():
        print(f"ERROR: stage B driver not found: {driver}", file=sys.stderr)
        return 1

    cmd: List[str] = [
        sys.executable, "-u", str(driver),
        "--outputs_root",       str(_abspath(args.source_outputs_root)),
        "--eval_root",          str(_abspath(args.source_eval_root)),
        "--original_plan_yaml", str(_abspath(args.original_plan_yaml)),
        "--plan_name",          args.plan_name,
        "--output_dir",         str(_abspath(args.stage_b_output_dir)),
        "--staging_root",       str(_abspath(args.stage_b_staging_root)),
        "--workspace_root",     str(_abspath(args.workspace_root)),
    ]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.max_parallel:
        cmd += ["--max_parallel", str(args.max_parallel)]
    if args.skip_resolved:
        cmd += ["--skip_resolved"]
    if args.single_instance:
        cmd += ["--single_instance", args.single_instance]
    if args.instance_ids:
        cmd += ["--instance_ids", ",".join(args.instance_ids)]
    if args.per_instance_timeout_sec is not None:
        cmd += ["--per_instance_timeout_sec", str(args.per_instance_timeout_sec)]
    if args.idle_timeout_sec is not None:
        cmd += ["--idle_timeout_sec", str(args.idle_timeout_sec)]
    if not args.fresh:
        cmd += ["--resume"]
    if args.stage_b_extra:
        cmd += args.stage_b_extra

    return _run_subprocess(cmd, cwd=REPO_ROOT, dry_run=args.dry_run)


# ---------------------------------------------------------------------------
# STAGE C - rerun (experiments/SWE_bench_LeanEvolve/PureLean/run.py)
# ---------------------------------------------------------------------------
def stage_c_rerun(args) -> int:
    driver = REPO_ROOT / STAGE_C_DRIVER
    if not driver.exists():
        print(f"ERROR: stage C driver not found: {driver}", file=sys.stderr)
        return 1

    cmd: List[str] = [
        sys.executable, "-u", str(driver),
        "--task-plans-dir", str(_abspath(args.stage_b_output_dir)),
        "--dataset",        str(_abspath(args.dataset)),
        "--split",          args.split,
        "--model",          args.model,
        "--output-dir",     str(_abspath(args.stage_c_output_dir)),
    ]
    if args.instance_ids:
        cmd += ["--instance-ids", ",".join(args.instance_ids)]
    elif args.single_instance:
        cmd += ["--instance-ids", args.single_instance]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.max_parallel:
        cmd += ["--max-parallel", str(args.max_parallel)]
    if args.save_logs:
        cmd += ["--save-logs"]
    if args.no_exclude:
        cmd += ["--no-exclude"]
    if args.per_instance_timeout_sec:
        cmd += ["--per-instance-timeout-sec", str(args.per_instance_timeout_sec)]
    if args.idle_timeout_sec is not None:
        cmd += ["--idle-timeout-sec", str(args.idle_timeout_sec)]
    if not args.fresh:
        cmd += ["--resume"]
    if args.stage_c_extra:
        cmd += args.stage_c_extra

    return _run_subprocess(cmd, cwd=REPO_ROOT, dry_run=args.dry_run)


# ---------------------------------------------------------------------------
# STAGE D - evaluate (python -m swebench.harness.run_evaluation)
# ---------------------------------------------------------------------------
def stage_d_evaluate(args) -> int:
    predictions = _abspath(args.stage_c_output_dir) / "predictions.jsonl"
    if not predictions.exists():
        print(f"ERROR: stage D: predictions file not found: {predictions}",
              file=sys.stderr)
        return 1

    eval_cwd = _abspath(args.stage_d_eval_cwd) if args.stage_d_eval_cwd \
               else predictions.parent
    eval_cwd.mkdir(parents=True, exist_ok=True)

    run_id = args.stage_d_run_id or f"{args.plan_name}_regen_llm"

    cmd: List[str] = [
        sys.executable, "-u", "-m", "swebench.harness.run_evaluation",
        "--dataset_name",     str(_abspath(args.dataset)),
        "--predictions_path", str(predictions),
        "--run_id",           run_id,
        "--max_workers",      str(args.stage_d_max_workers),
    ]
    if args.stage_d_extra:
        cmd += args.stage_d_extra

    return _run_subprocess(cmd, cwd=eval_cwd, dry_run=args.dry_run)


STAGE_FN: dict[str, Callable[[argparse.Namespace], int]] = {
    "evolve":   stage_b_evolve,
    "rerun":    stage_c_rerun,
    "evaluate": stage_d_evaluate,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[1] if __doc__ else "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument("--plan-name", required=True,
                   help="E.g. passed_workflow_1. Used as the prefix for evolved-plan filenames.")
    p.add_argument("--original-plan-yaml", required=True,
                   help="Path to the original SWE-bench plan YAML being evolved.")

    p.add_argument("--source-outputs-root", required=True,
                   help="Prior run's outputs dir, containing <inst>_agent_events.log per instance. "
                        "E.g. outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1")
    p.add_argument("--source-eval-root", required=True,
                   help="Prior run's eval dir, containing <inst>/report.json + test_output.txt "
                        "(either directly or one level deep under a <model>/ subdir). "
                        "E.g. benchmark_results/.../logs/run_evaluation/passed_workflow_1/gpt-5.2")

    p.add_argument("--dataset", required=True,
                   help="HuggingFace dataset name or local path.")
    p.add_argument("--split", default="test")
    p.add_argument("--model", default="gpt-5.2")

    p.add_argument("--workspace-root",
                   default=str(REPO_ROOT / "workspace"),
                   help="Host path the sandbox Docker mounts as /workspace.")
    p.add_argument("--unified-staging-root",
                   default="",
                   help="Single parent dir for ALL stage staging + outputs. When set, "
                        "auto-derives every stage path as a subfolder:\n"
                        "  <root>/stage_b/               -> --stage-b-staging-root\n"
                        "  <root>/stage_b_evolved_plans/ -> --stage-b-output-dir\n"
                        "  <root>/stage_c_rerun/         -> --stage-c-output-dir\n"
                        "RECOMMENDED: place <root> INSIDE --workspace-root so one "
                        "directory holds every byte of the run (delete <root> for "
                        "a clean reset). If <root> is outside --workspace-root, "
                        "Stage B's Docker-visible staging is split off to "
                        "<workspace_root>/llm_evolve/<tail>/ and you'll need to "
                        "delete BOTH to fully reset.")
    p.add_argument("--stage-b-staging-root",
                   default="",
                   help="Stage B's Docker-visible staging root. Default: "
                        "<workspace>/llm_evolve_run/staging_<model_slug>.")
    p.add_argument("--stage-b-output-dir",
                   default="",
                   help="Durable dir for evolved plans (input to Stage C). Default: "
                        "experiments/SWE_bench_verified/layer3_smoke_test/LLM_only_evolve.")
    p.add_argument("--stage-c-output-dir",
                   default="",
                   help="Where Stage C writes per-instance diffs + predictions.jsonl. "
                        "Required unless --unified-staging-root is set.")
    p.add_argument("--stage-d-run-id",
                   default="",
                   help="sb-cli / swebench.harness run_id. Default: <plan_name>_regen_llm.")
    p.add_argument("--stage-d-eval-cwd",
                   default="",
                   help="Working directory for stage D. Defaults to predictions file's parent.")
    p.add_argument("--stage-d-max-workers", type=int, default=50)

    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-parallel", type=int, default=1)
    p.add_argument("--single-instance", default="",
                   help="Run one instance end-to-end. Passed through to each stage.")
    p.add_argument("--instance-ids", nargs="*", default=None,
                   help="Whitelist for Stage C. If omitted, Stage C uses every plan in "
                        "--stage-b-output-dir.")
    p.add_argument("--skip-resolved", action="store_true",
                   help="Stage B only: skip instances whose prior report.json shows resolved=true.")

    p.add_argument("--save-logs", action="store_true", default=True,
                   help="Stage C: save full agent logs (default: on).")
    p.add_argument("--no-save-logs", dest="save_logs", action="store_false")
    p.add_argument("--no-exclude", action="store_true", default=True,
                   help="Stage C: don't filter by the excluded_instances.txt list (default: on).")
    p.add_argument("--per-instance-timeout-sec", type=int, default=10800,
                   help="Per-instance watchdog in seconds (default: 10800 = 3 h). "
                        "Applied to BOTH stage B (plan evolution AgentSPEX) and "
                        "stage C (SWE-bench rerun). Pass 0 to disable for stage B "
                        "(stage C's flag is a passthrough; 0 may be rejected there).")
    p.add_argument("--idle-timeout-sec", type=int, default=7200,
                   help="Idle-watchdog in seconds (default: 7200 = 2 h). Fires "
                        "when an instance's event log stops growing, regardless "
                        "of total runtime. Applied to BOTH stage B and stage C. "
                        "Complements --per-instance-timeout-sec. Pass 0 to "
                        "disable.")

    p.add_argument("--start-stage", choices=STAGE_ORDER, default="evolve",
                   help="Begin at this stage; skip earlier ones.")
    p.add_argument("--only-stage", choices=STAGE_ORDER, default="",
                   help="Run ONLY this stage and stop.")
    p.add_argument("--run-eval", action="store_true",
                   help="Include stage D (swebench.harness.run_evaluation) after stage C.")
    p.add_argument("--fresh", action="store_true",
                   help="Don't pass --resume to any stage (re-process every instance).")
    p.add_argument("--resume", action="store_true",
                   help="No-op (resume is the default). Accepted for symmetry with "
                        "the sub-stage drivers. Use --fresh to opt out of resume.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print each stage's command but don't execute.")
    p.add_argument("--continue-on-error", action="store_true",
                   help="Continue to the next stage even if the current one returns non-zero.")

    p.add_argument("--stage-b-extra", nargs=argparse.REMAINDER, default=[],
                   help=argparse.SUPPRESS)
    p.add_argument("--stage-c-extra", nargs=argparse.REMAINDER, default=[],
                   help=argparse.SUPPRESS)
    p.add_argument("--stage-d-extra", nargs=argparse.REMAINDER, default=[],
                   help=argparse.SUPPRESS)

    args = p.parse_args()

    if args.instance_ids:
        flat: list[str] = []
        for chunk in args.instance_ids:
            flat.extend(s.strip() for s in chunk.split(",") if s.strip())
        args.instance_ids = flat

    model_slug = _model_slug(args.model)

    # Priority: explicit stage flag > --unified-staging-root > built-in default.
    if args.unified_staging_root:
        unified = _abspath(args.unified_staging_root)
        workspace_abs = _abspath(args.workspace_root)
        try:
            unified.relative_to(workspace_abs)
            unified_under_workspace = True
        except ValueError:
            unified_under_workspace = False

        # Stage B's AgentSPEX talks to the Docker sandbox via MCP and only
        # sees paths under /workspace, so its staging MUST be Docker-visible
        # (i.e. under --workspace-root). To satisfy the "one folder = one
        # run" principle (delete --unified-staging-root → clean reset), the
        # unified root itself must live inside --workspace-root. When it
        # does not, we fall back to splitting staging (Docker-visible) from
        # durables (outside workspace), but loudly warn the user.
        if unified_under_workspace:
            workspace_host = unified
        else:
            tail = "/".join(unified.parts[-2:]) if len(unified.parts) >= 2 \
                   else unified.name
            workspace_host = workspace_abs / "llm_evolve" / tail
            print(
                f"WARNING: --unified-staging-root ({unified}) is OUTSIDE "
                f"--workspace-root ({workspace_abs}).\n"
                f"  Because Stage B's agent talks to the Docker sandbox via "
                f"MCP and only sees paths under /workspace, intermediate "
                f"runtime state is split off to {workspace_host}.\n"
                f"  This means 'delete --unified-staging-root' does NOT fully "
                f"reset the run — you also have to delete {workspace_host}.\n"
                f"  Recommended: use --unified-staging-root under "
                f"{workspace_abs} (e.g. {workspace_abs}/llm_evolve/<model>/<plan>) "
                f"so one directory holds every byte of the run.",
                flush=True,
            )

        if not args.stage_b_staging_root:
            args.stage_b_staging_root = str(workspace_host / "stage_b")
        if not args.stage_b_output_dir:
            args.stage_b_output_dir = str(unified / "stage_b_evolved_plans")
        if not args.stage_c_output_dir:
            args.stage_c_output_dir = str(unified / "stage_c_rerun")

    if not args.stage_b_staging_root:
        args.stage_b_staging_root = f"workspace/llm_evolve_run/staging_{model_slug}"
    if not args.stage_b_output_dir:
        args.stage_b_output_dir = str(
            REPO_ROOT / "experiments/SWE_bench_verified/layer3_smoke_test"
            / "LLM_only_evolve")
    if not args.stage_c_output_dir:
        print("ERROR: --stage-c-output-dir is required "
              "(or pass --unified-staging-root to derive it automatically).",
              file=sys.stderr)
        sys.exit(2)
    if not args.stage_d_run_id:
        args.stage_d_run_id = f"{args.plan_name}_regen_llm"

    for p in (args.stage_b_staging_root, args.stage_b_output_dir,
              args.stage_c_output_dir):
        _abspath(p).mkdir(parents=True, exist_ok=True)

    return args


def _env_sanity_check() -> None:
    if not os.environ.get("MODEL_NAME"):
        print("WARNING: MODEL_NAME is not exported. Stage B's YAML reads ${MODEL_NAME}; "
              "source your model config first, e.g.:\n"
              "    source ./experiments/SWE_bench_verified/gpt5.2_config.env",
              file=sys.stderr)


def main() -> int:
    args = parse_args()
    _env_sanity_check()

    if args.only_stage:
        selected = [args.only_stage]
    else:
        start_idx = STAGE_ORDER.index(args.start_stage)
        selected = list(STAGE_ORDER[start_idx:])
        if not args.run_eval and "evaluate" in selected:
            selected.remove("evaluate")

    print("Pipeline plan:")
    for s in STAGE_ORDER:
        mark = "X" if s in selected else " "
        print(f"  [{mark}] {s}")
    print(f"  resume mode: {'fresh (no --resume)' if args.fresh else 'intermediate resume'}")
    print(f"  dry-run: {args.dry_run}")

    results: List[StageResult] = []
    aborted = False
    for stage_name in selected:
        _print_banner(f"STAGE: {stage_name}")
        t0 = time.time()
        rc = STAGE_FN[stage_name](args)
        dur = round(time.time() - t0, 2)
        results.append(StageResult(stage_name, rc, skipped=False, duration_sec=dur))
        if rc != 0:
            print(f"Stage {stage_name} returned {rc} after {dur}s.", flush=True)
            if not args.continue_on_error:
                aborted = True
                break
        else:
            print(f"Stage {stage_name} OK in {dur}s.", flush=True)

    _print_banner("SUMMARY")
    for r in results:
        mark = "OK" if r.returncode == 0 else f"FAIL({r.returncode})"
        print(f"  {r.name:10s} {mark:10s} {r.duration_sec}s")
    if aborted:
        print("Pipeline aborted on stage failure. Re-run (default is intermediate resume) "
              "to continue after fixing the cause.")
        return next((r.returncode for r in results if r.returncode != 0), 1)
    remaining = [s for s in selected if not any(r.name == s for r in results)]
    if remaining:
        print(f"Did not reach: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
