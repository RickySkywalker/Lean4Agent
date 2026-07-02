#!/usr/bin/env python3
"""
SWE_bench_LeanEvolve/run.py — Joint LeanEvolve -> LLMEvolve correction cascade
for SWE-Bench-Verified.

This is the MERGED entry point that runs both workflow-evolution arms over a set
of previously-FAILED instances and reports how many additional problems get
fixed once. It is a thin orchestrator: every heavy step is delegated to the two
existing arm packages and the SWE-bench harness — nothing is reimplemented here.

Per previously-failed instance, the cascade is:

  1. LeanEvolve  — PureLean/run.py   (vendored in this package)
                   (Stage A annotate -> B Lean-guided evolve -> C rerun)
                       -> lean predictions.jsonl
  2. evaluate    — python -m swebench.harness.run_evaluation
                       -> per-instance `resolved` verdicts
                   Instances resolved here are FIXED by the Lean arm.
  3. LLMEvolve   — PureLLMAddsOn/run_e2e.py   (vendored in this package)
                   (LLM-only evolve -> rerun), run ONLY on instances still
                   failing after step 2
                       -> llm predictions.jsonl
  4. evaluate    — same harness, on the still-failing subset
                   Instances resolved here are FIXED by the LLM arm.

A previously-failed instance counts as an "additional pass" iff EITHER arm
resolves it. The two arms reuse their own resumable staging trees (default
locations match the standalone runs), so re-invoking this wrapper picks up all
prior Stage-A/B/C work and only the missing pieces run.

Failure set: by default the instances whose baseline eval `report.json` shows
`resolved == False` under --source-eval-root (intersected with those having a
prior trajectory under --source-outputs-root). `--instance-ids` overrides.

Invocation (typical — glm-5 on Bedrock, the paper's SWE arm):

    source ./configs/LLM-config.env
    python -u experiments/SWE_bench_LeanEvolve/run.py \
        --plan-name passed_workflow_1 \
        --source-outputs-root tmp/runs/passed_workflow_1 \
        --source-eval-root tmp/runs/baseline_eval/logs/run_evaluation/glm5_baseline/bedrock__zai.glm-5 \
        --dataset data/SWE_bench_verified_50problems_subset \
        --split test \
        --model bedrock/zai.glm-5 \
        --max-parallel 5
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

REPO_ROOT = next(p for p in Path(__file__).resolve().parents
                 if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
HERE = Path(__file__).resolve().parent

# Both arms are vendored inside this package so it stays self-contained.
LEAN_ARM = HERE / "PureLean" / "run.py"
LLM_ARM = HERE / "PureLLMAddsOn" / "run_e2e.py"
DEFAULT_PLANS_DIR = REPO_ROOT / "experiments/SWE_bench_verified"
DEFAULT_LAYER2_IR_DIR = REPO_ROOT / "FormalAgentLib/VerificationExamples/layer2_v2_ir"
WORKSPACE_ROOT = (REPO_ROOT / "workspace").resolve()


def log(msg: str) -> None:
    print(msg, flush=True)


def _model_slug(model: str) -> str:
    return "".join(ch for ch in model.lower() if ch.isalnum())


def _model_report_slug(model: str) -> str:
    """SWE-bench writes per-instance reports under <model>.replace('/', '__')."""
    return model.replace("/", "__")


def _abspath(p: str | Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO_ROOT / pp).resolve()


# --------------------------------------------------------------------------- #
# Failure discovery + per-instance resolved verdicts (shared with the arms)
# --------------------------------------------------------------------------- #

def _read_resolved_flag(report_path: Path, instance_id: str) -> bool | None:
    """Return a SWE-bench report.json's `resolved` flag for instance_id, or None
    if the report is missing / unparseable / lacks the instance key."""
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    block = data.get(instance_id) or (next(iter(data.values())) if len(data) == 1 else None)
    if not block:
        return None
    return bool(block.get("resolved", False))


def discover_failed_instances(source_outputs_root: Path, source_eval_root: Path,
                              instance_ids: set[str] | None,
                              limit: int | None,
                              include_unevaluated: bool) -> list[str]:
    """Default: instances whose baseline report shows resolved==False AND have a
    prior trajectory (<inst>_agent_events.log). With `include_unevaluated`,
    trajectories with no baseline report (resolved==None — baseline error /
    not-submitted) are also treated as failed. `instance_ids` overrides the
    filter but is still intersected with available trajectories."""
    available = sorted(
        p.name[: -len("_agent_events.log")]
        for p in source_outputs_root.glob("*_agent_events.log")
    )
    if not available:
        log(f"ERROR: no <inst>_agent_events.log under {source_outputs_root}")
        return []
    avail_set = set(available)

    if instance_ids is not None:
        out = [i for i in sorted(instance_ids) if i in avail_set]
        missing = sorted(instance_ids - avail_set)
        if missing:
            log(f"WARNING: {len(missing)} requested instance(s) have no prior "
                f"trajectory and are dropped: {missing}")
    else:
        out = []
        for inst in available:
            resolved = _read_resolved_flag(source_eval_root / inst / "report.json", inst)
            if resolved is True:
                continue                       # baseline already passed — skip
            if resolved is None and not include_unevaluated:
                continue                       # no baseline report — skip by default
            out.append(inst)

    if limit:
        out = out[:limit]
    return out


def resolved_in_eval(eval_cwd: Path, run_id: str, model: str,
                     instances: Iterable[str]) -> set[str]:
    """Read the per-instance reports the harness wrote under eval_cwd and return
    the subset of `instances` marked resolved==True."""
    base = eval_cwd / "logs" / "run_evaluation" / run_id / _model_report_slug(model)
    resolved: set[str] = set()
    for inst in instances:
        if _read_resolved_flag(base / inst / "report.json", inst) is True:
            resolved.add(inst)
    return resolved


# --------------------------------------------------------------------------- #
# Sub-process helpers
# --------------------------------------------------------------------------- #

def _run(cmd: list[str], *, cwd: Path, dry_run: bool, label: str) -> int:
    printable = " ".join(shlex.quote(c) for c in cmd)
    log(f"\n$ (cd {cwd} && {printable})")
    if dry_run:
        return 0
    t0 = time.time()
    rc = subprocess.run(cmd, cwd=str(cwd), check=False).returncode
    log(f"[{label}] rc={rc} in {round(time.time() - t0, 1)}s")
    return rc


def run_lean_arm(args, instances: list[str], lean_staging: Path) -> Path:
    """Spawn the LeanEvolve A->B->C orchestrator over `instances`. Returns the
    path to the Stage-C predictions.jsonl (may not exist if Stage C made none)."""
    cmd = [sys.executable, "-u", str(LEAN_ARM),
           "--plan-name", args.plan_name,
           "--original-plan-yaml", str(args.original_plan_yaml),
           "--source-outputs-root", str(args.source_outputs_root),
           "--source-eval-root", str(args.source_eval_root),
           "--source-layer2-ir", str(args.source_layer2_ir),
           "--dataset", str(args.dataset),
           "--split", args.split,
           "--model", args.model,
           "--conda-env", args.conda_env,
           "--unified-staging-root", str(lean_staging),
           "--instance-ids", ",".join(instances),
           "--max-parallel", str(args.max_parallel),
           "--per-instance-timeout-sec", str(args.per_instance_timeout_sec),
           "--idle-timeout-sec", str(args.idle_timeout_sec)]
    if args.fresh:
        cmd.append("--fresh")
    if not args.skip_lean_arm:
        _run(cmd, cwd=REPO_ROOT, dry_run=args.dry_run, label="LeanEvolve")
    else:
        log("[LeanEvolve] --skip-lean-arm: reusing existing Stage-C predictions.")
    return lean_staging / "stage_c_rerun" / "predictions.jsonl"


def run_llm_arm(args, instances: list[str], llm_staging: Path) -> Path:
    """Spawn the LLMEvolve evolve->rerun pipeline over `instances` (no internal
    eval — this wrapper evaluates). Returns the Stage-C predictions.jsonl path."""
    cmd = [sys.executable, "-u", str(LLM_ARM),
           "--plan-name", args.plan_name,
           "--original-plan-yaml", str(args.original_plan_yaml),
           "--source-outputs-root", str(args.source_outputs_root),
           "--source-eval-root", str(args.source_eval_root),
           "--dataset", str(args.dataset),
           "--split", args.split,
           "--model", args.model,
           "--unified-staging-root", str(llm_staging),
           "--instance-ids", ",".join(instances),
           "--max-parallel", str(args.max_parallel),
           "--per-instance-timeout-sec", str(args.per_instance_timeout_sec),
           "--idle-timeout-sec", str(args.idle_timeout_sec)]
    if args.fresh:
        cmd.append("--fresh")
    if not args.skip_llm_arm:
        _run(cmd, cwd=REPO_ROOT, dry_run=args.dry_run, label="LLMEvolve")
    else:
        log("[LLMEvolve] --skip-llm-arm: reusing existing Stage-C predictions.")
    return llm_staging / "stage_c_rerun" / "predictions.jsonl"


def filter_predictions(src: Path, keep: set[str], dst: Path) -> int:
    """Write the rows of `src` whose instance_id is in `keep` to `dst`. Returns
    the number of rows written (0 if src is missing / empty)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    if src.exists():
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                iid = json.loads(line).get("instance_id")
            except Exception:
                continue
            if iid in keep:
                rows.append(line)
    dst.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)


def evaluate(args, predictions: Path, eval_cwd: Path, run_id: str,
             instances: list[str], arm: str) -> set[str]:
    """Run the SWE-bench harness on `predictions` (cwd=eval_cwd, the same layout
    as the standalone arm evals) and return the resolved subset of `instances`.
    The harness skips instances whose report already exists, so this is cheap on
    re-runs. Returns {} when there is nothing to score."""
    eval_cwd.mkdir(parents=True, exist_ok=True)
    n = sum(1 for _ in predictions.open()) if predictions.exists() else 0
    if n == 0:
        log(f"[eval:{arm}] no predictions to score ({predictions}); 0 resolved.")
        return set()
    cmd = [sys.executable, "-u", "-m", "swebench.harness.run_evaluation",
           "--dataset_name", str(_abspath(args.dataset)),
           "--predictions_path", str(predictions.resolve()),
           "--run_id", run_id,
           "--max_workers", str(args.eval_max_workers)]
    log(f"[eval:{arm}] scoring {n} prediction(s) with run_id={run_id}")
    _run(cmd, cwd=eval_cwd, dry_run=args.dry_run, label=f"eval:{arm}")
    if args.dry_run:
        return set()
    return resolved_in_eval(eval_cwd, run_id, args.model, instances)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--plan-name", required=True,
                   help="E.g. passed_workflow_1. Prefix for evolved-plan filenames.")
    p.add_argument("--original-plan-yaml", default="",
                   help="Original SWE-bench plan YAML (default: "
                        "experiments/SWE_bench_verified/<plan>.yaml).")
    p.add_argument("--source-outputs-root", required=True,
                   help="Baseline run's outputs dir with <inst>_agent_events.log.")
    p.add_argument("--source-eval-root", required=True,
                   help="Baseline eval dir with <inst>/report.json (failure discovery).")
    p.add_argument("--source-layer2-ir", default="",
                   help="Plan-level Layer-2 IR JSON for the Lean arm (default: "
                        "FormalAgentLib/VerificationExamples/layer2_v2_ir/"
                        "<plan>_layer2_v2.ir.json).")

    p.add_argument("--dataset", required=True, help="HuggingFace dataset name or local path.")
    p.add_argument("--split", default="test")
    p.add_argument("--model", default="bedrock/zai.glm-5")

    p.add_argument("--instance-ids", nargs="*", default=None,
                   help="Whitelist of failed instance ids (overrides resolved==False discovery).")
    p.add_argument("--limit", type=int, default=0, help="Cap on instances (0 = no cap).")
    p.add_argument("--max-parallel", type=int, default=1)
    p.add_argument("--include-unevaluated", action="store_true",
                   help="Also treat trajectories with no baseline report.json "
                        "(baseline error / not-submitted) as failed. Default: "
                        "only instances whose baseline report shows resolved==False.")

    # staging / outputs
    p.add_argument("--workspace-root", default=str(WORKSPACE_ROOT),
                   help="Host path the MCP sandbox mounts as /workspace.")
    p.add_argument("--lean-staging-root", default="",
                   help="LeanEvolve unified staging root (default: "
                        "<workspace>/swe_lean_evolve/<model_slug>/<plan>).")
    p.add_argument("--llm-staging-root", default="",
                   help="LLMEvolve unified staging root (default: "
                        "<workspace>/swe_llm_evolve/<plan>).")
    p.add_argument("--run-root", default="",
                   help="Where joint eval dirs + report land (default: "
                        "tmp/runs/swe_leanevolve/<model_slug>/<plan>).")
    p.add_argument("--lean-eval-cwd", default="", help="Override Lean eval cwd (resume reuse).")
    p.add_argument("--lean-eval-run-id", default="", help="Override Lean eval run_id.")
    p.add_argument("--llm-eval-cwd", default="", help="Override LLM eval cwd (resume reuse).")
    p.add_argument("--llm-eval-run-id", default="", help="Override LLM eval run_id.")

    # knobs
    p.add_argument("--conda-env", default=os.environ.get("CONDA_DEFAULT_ENV", "AgentSPEX_env"),
                   help="Conda env for the Lean arm's Stage-A/B YAML agents.")
    p.add_argument("--per-instance-timeout-sec", type=int, default=10800)
    p.add_argument("--idle-timeout-sec", type=int, default=7200)
    p.add_argument("--eval-max-workers", type=int, default=0,
                   help="SWE-bench harness workers (default: --max-parallel).")

    # orchestration
    p.add_argument("--fresh", action="store_true",
                   help="Disable resume in both arms (re-run every sub-stage).")
    p.add_argument("--skip-lean-arm", action="store_true",
                   help="Don't spawn the Lean evolve/rerun; reuse existing predictions, still eval.")
    p.add_argument("--skip-llm-arm", action="store_true",
                   help="Don't spawn the LLM evolve/rerun; reuse existing predictions, still eval.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print every sub-command without executing.")

    args = p.parse_args()

    if args.instance_ids:
        flat: list[str] = []
        for chunk in args.instance_ids:
            flat.extend(s.strip() for s in chunk.split(",") if s.strip())
        args.instance_ids = set(flat) if flat else None
    else:
        args.instance_ids = None

    # Resolve defaults.
    args.source_outputs_root = _abspath(args.source_outputs_root)
    args.source_eval_root = _abspath(args.source_eval_root)
    args.dataset = _abspath(args.dataset)
    args.original_plan_yaml = (_abspath(args.original_plan_yaml) if args.original_plan_yaml
                               else (DEFAULT_PLANS_DIR / f"{args.plan_name}.yaml"))
    args.source_layer2_ir = (_abspath(args.source_layer2_ir) if args.source_layer2_ir
                             else (DEFAULT_LAYER2_IR_DIR / f"{args.plan_name}_layer2_v2.ir.json"))

    slug = _model_slug(args.model)
    ws = _abspath(args.workspace_root)
    args.lean_staging_root = (_abspath(args.lean_staging_root) if args.lean_staging_root
                              else ws / "swe_lean_evolve" / slug / args.plan_name)
    args.llm_staging_root = (_abspath(args.llm_staging_root) if args.llm_staging_root
                             else ws / "swe_llm_evolve" / args.plan_name)
    args.run_root = (_abspath(args.run_root) if args.run_root
                     else _abspath(f"tmp/runs/swe_leanevolve/{slug}/{args.plan_name}"))

    args.lean_eval_cwd = (_abspath(args.lean_eval_cwd) if args.lean_eval_cwd
                          else args.run_root / "lean_eval")
    args.llm_eval_cwd = (_abspath(args.llm_eval_cwd) if args.llm_eval_cwd
                         else args.run_root / "llm_eval")
    args.lean_eval_run_id = args.lean_eval_run_id or f"{args.plan_name}_lean"
    args.llm_eval_run_id = args.llm_eval_run_id or f"{args.plan_name}_llm"
    if not args.eval_max_workers:
        args.eval_max_workers = max(1, args.max_parallel)
    return args


def main() -> int:
    args = parse_args()

    if not args.original_plan_yaml.exists():
        log(f"ERROR: original plan YAML not found: {args.original_plan_yaml}")
        return 1
    if not args.source_layer2_ir.exists():
        log(f"ERROR: Layer-2 IR not found (needed by the Lean arm): {args.source_layer2_ir}")
        return 1
    args.run_root.mkdir(parents=True, exist_ok=True)

    failed = discover_failed_instances(args.source_outputs_root, args.source_eval_root,
                                       args.instance_ids, args.limit if args.limit else None,
                                       args.include_unevaluated)
    if not failed:
        log("No previously-failed instances to correct.")
        return 0

    log("=" * 78)
    log(f"Joint LeanEvolve -> LLMEvolve cascade over {len(failed)} previously-failed instance(s)")
    log(f"  plan          : {args.plan_name}")
    log(f"  model         : {args.model}")
    log(f"  lean staging  : {args.lean_staging_root}")
    log(f"  llm staging   : {args.llm_staging_root}")
    log(f"  run root      : {args.run_root}")
    log(f"  failed set    : {failed}")
    log("=" * 78)

    # ---- Arm 1: LeanEvolve over all failed, then evaluate ----
    log("\n########## ARM 1: LeanEvolve (Lean-formal-guided) ##########")
    lean_preds = run_lean_arm(args, failed, args.lean_staging_root)
    lean_resolved = evaluate(args, lean_preds, args.lean_eval_cwd,
                             args.lean_eval_run_id, failed, arm="lean")
    log(f"\n[ARM 1 result] LeanEvolve fixed {len(lean_resolved)}/{len(failed)}: "
        f"{sorted(lean_resolved)}")

    # ---- Arm 2: LLMEvolve over the still-failing subset, then evaluate ----
    still_failing = [i for i in failed if i not in lean_resolved]
    llm_resolved: set[str] = set()
    if not still_failing:
        log("\n########## ARM 2: LLMEvolve — skipped (LeanEvolve fixed everything) ##########")
    else:
        log(f"\n########## ARM 2: LLMEvolve (LLM-only) over {len(still_failing)} "
            f"still-failing instance(s) ##########")
        llm_preds = run_llm_arm(args, still_failing, args.llm_staging_root)
        # Score ONLY the still-failing subset, so an instance Lean already fixed
        # is never double-counted even if the LLM arm also reran it.
        filtered = args.llm_eval_cwd / "predictions_still_failing.jsonl"
        kept = filter_predictions(llm_preds, set(still_failing), filtered)
        log(f"[ARM 2] {kept} LLM prediction(s) in the still-failing subset")
        llm_resolved = evaluate(args, filtered, args.llm_eval_cwd,
                                args.llm_eval_run_id, still_failing, arm="llm")
        log(f"\n[ARM 2 result] LLMEvolve fixed {len(llm_resolved)}/{len(still_failing)}: "
            f"{sorted(llm_resolved)}")

    # ---- Joint report ----
    additional = sorted(set(lean_resolved) | set(llm_resolved))
    attribution = {i: ("lean" if i in lean_resolved else "llm") for i in additional}
    report = {
        "plan_name": args.plan_name,
        "model": args.model,
        "failed_instances": failed,
        "n_failed": len(failed),
        "lean_resolved": sorted(lean_resolved),
        "llm_resolved": sorted(llm_resolved),
        "additional_passes": additional,
        "n_additional_passes": len(additional),
        "attribution": attribution,
        "lean_eval": {"cwd": str(args.lean_eval_cwd), "run_id": args.lean_eval_run_id},
        "llm_eval": {"cwd": str(args.llm_eval_cwd), "run_id": args.llm_eval_run_id},
    }
    report_path = args.run_root / "joint_correction_report.json"
    if not args.dry_run:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    log("\n" + "=" * 78)
    log("JOINT CORRECTION SUMMARY")
    log("=" * 78)
    log(f"  previously failed         : {len(failed)}")
    log(f"  fixed by LeanEvolve       : {len(lean_resolved)}  {sorted(lean_resolved)}")
    log(f"  fixed by LLMEvolve        : {len(llm_resolved)}  {sorted(llm_resolved)}")
    log(f"  ADDITIONAL PROBLEM PASSES : {len(additional)}/{len(failed)}  {additional}")
    pct = (100.0 * len(additional) / len(failed)) if failed else 0.0
    log(f"  additional pass rate      : {pct:.1f}% of previously-failed")
    if not args.dry_run:
        log(f"  report                    : {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
