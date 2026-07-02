"""SWE-Bench regen runner (Stage C) — runs evolved task plans, one per instance.

This is the per-instance SWE-bench Docker rerun runner. It was previously named
`run.py`; it is now `rerun.py` because `run.py` is the self-contained A->B->C
orchestrator (mirroring experiments/elaip_LeanEvolve/run.py). The orchestrator's
Stage C spawns this module on the directory of evolved per-instance plans; it can
also be invoked directly (the original interface, below).

Mirrors `experiments/SWE_bench_verified/run.py` but dispatches each
instance to a per-instance YAML discovered from `--task-plans-dir`
instead of using a single `--task-plan-file` for the whole set.

Example (standalone):

    source experiments/SWE_bench_verified/gpt5.2_config.env
    python experiments/SWE_bench_LeanEvolve/PureLean/rerun.py \\
        --task-plans-dir .../layer3_smoke_test/Lean_guided_modification \\
        --dataset .../SWE_bench_verified_50problems_subset \\
        --instance-ids django__django-14140,sympy__sympy-13551 \\
        --split test \\
        --limit 50 \\
        --model gpt-5.2 \\
        --max-parallel 10 \\
        --no-exclude --save-logs --resume \\
        --output-dir outputs/.../passed_workflow_1_regen
"""

import atexit
import copy
import json
import os
import signal
import sys
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# Make importable: experiments/ (for the still-present SWE_bench_verified) and
# this merged package dir (for the in-package PureLean.config). This package is
# self-contained: it does not import any sibling evolve package.
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2]))   # .../experiments
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))   # .../SWE_bench_LeanEvolve
from PureLean.config import (
    InstanceResult,
    discover_plans,
    load_excluded_instances,
    parse_args,
)
# Reuse the verified-side runner internals — they're stable.
import SWE_bench_verified.run as _verified_run
from SWE_bench_verified.docker_exec_client import DockerExecClient
from SWE_bench_verified.instance import (
    run_instance,
    save_patch_to_jsonl,
)
from SWE_bench_verified.run import (
    _is_instance_completed,
    _signal_handler,
    cleanup_dashboard,
    start_dashboard,
)
from datasets import load_dataset

from harness.agent import AgentSPEX
from harness.utils.idle_watchdog import IdleWatchdog


def main():
    """Entry point — same orchestration shape as the verified runner."""
    args = parse_args()
    _verified_run._dashboard_keep = args.dashboard_keep

    # Disable per-step workspace-manifest snapshots for Stage C. With
    # HOST_WORKSPACE set, every AgentSPEX instance spawned below would
    # scan the entire <workspace_root> after every step and copy every
    # file >1 MB to <workspace_backup_path>. Under concurrent runs
    # (ThreadPoolExecutor with max-parallel workers sharing /workspace),
    # this thrashes NFS I/O and causes OSError(EIO) on the next LLM
    # call — especially lethal for local vLLM endpoints (Gemma4). The
    # SWE-bench agent's real per-instance state lives inside its own
    # per-instance SWE-bench docker container (via docker_exec_client);
    # the /workspace/ snapshot mechanism adds no value here.
    os.environ["HOST_WORKSPACE"] = ""

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(cleanup_dashboard)

    try:
        if args.dashboard:
            _verified_run._dashboard_proc = start_dashboard(args)
        run_full_pipeline(args)
    finally:
        cleanup_dashboard()


def run_full_pipeline(args):
    """Discover per-instance plans, filter the dataset, dispatch agents."""
    plans_dir = Path(args.task_plans_dir)
    if not plans_dir.is_dir():
        print(f"Error: --task-plans-dir not found: {plans_dir}")
        sys.exit(1)

    instance_to_plan = discover_plans(plans_dir)
    if not instance_to_plan:
        print(f"Error: no YAML plans discovered in {plans_dir}")
        print(
            "Plan filenames must contain the instance id, "
            "e.g. passed_workflow_1_<repo>__<repo>-<num>_lean.yaml"
        )
        sys.exit(1)
    print(
        f"Discovered {len(instance_to_plan)} evolved plan(s) in {plans_dir}:"
    )
    for iid, p in sorted(instance_to_plan.items()):
        print(f"  - {iid}  ←  {p.name}")

    print(f"\nLoading dataset {args.dataset} (split: {args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)

    plan_iids = set(instance_to_plan.keys())

    # Build the effective whitelist: intersection of CLI --instance-ids
    # (if given) and the plan-directory contents.
    if args.instance_ids:
        whitelist = set(args.instance_ids) & plan_iids
        missing_in_plans = set(args.instance_ids) - plan_iids
        if missing_in_plans:
            print(
                f"Warning: {len(missing_in_plans)} requested instance id(s) "
                f"have no plan in {plans_dir}: {sorted(missing_in_plans)}"
            )
        if not whitelist:
            print(
                "Error: no overlap between --instance-ids and the plan dir; "
                "nothing to run."
            )
            sys.exit(1)
    else:
        whitelist = plan_iids

    indices = [
        i for i, inst in enumerate(dataset) if inst["instance_id"] in whitelist
    ]
    if not indices:
        print(
            "Error: no rows in the dataset match the plan-directory "
            "instance ids."
        )
        sys.exit(1)
    dataset = dataset.select(indices)
    print(
        f"Filtered dataset to {len(dataset)} instance(s) with evolved plans."
    )

    # Standard exclude / limit filters (same semantics as verified runner).
    if not args.no_exclude:
        excluded = load_excluded_instances(args.exclude_file)
        if excluded:
            keep = [
                i
                for i, inst in enumerate(dataset)
                if inst["instance_id"] not in excluded
            ]
            dropped = len(dataset) - len(keep)
            if keep:
                dataset = dataset.select(keep)
            if dropped:
                print(
                    f"Excluded {dropped} instance(s) from {args.exclude_file}"
                )

    if args.limit and args.limit < len(dataset):
        dataset = dataset.select(range(args.limit))
        print(f"Limited to first {args.limit} instance(s)")

    print(f"\n{len(dataset)} task(s) to process")
    if args.max_parallel > 1:
        print(f"Running with max {args.max_parallel} parallel instances")

    output_dir = Path(args.output_dir)

    # Resume — skip instances whose events log already shows workflow_end.
    resumed_results: List[InstanceResult] = []
    if getattr(args, "resume", False) and not output_dir.exists():
        print(
            f"Warning: --resume specified but output directory does not "
            f"exist: {output_dir}. Starting from scratch."
        )
    elif getattr(args, "resume", False):
        prior_diffs: dict = {}
        for diff_file in output_dir.glob("*.diff"):
            patch = diff_file.read_text()
            if patch.strip():
                prior_diffs[diff_file.stem] = patch

        remaining = []
        for i, inst in enumerate(dataset):
            iid = inst["instance_id"]
            if _is_instance_completed(output_dir, iid):
                patch = prior_diffs.pop(iid, "")
                resumed_results.append(
                    InstanceResult(
                        instance_id=iid,
                        success=bool(patch.strip()),
                        patch=patch,
                    )
                )
            else:
                remaining.append(i)

        # Pull in any older completed instances not in the current dataset.
        for iid, patch in prior_diffs.items():
            if _is_instance_completed(output_dir, iid):
                resumed_results.append(
                    InstanceResult(instance_id=iid, success=True, patch=patch)
                )

        if resumed_results:
            print(
                f"Resuming: {len(resumed_results)} instance(s) already "
                f"completed, skipping"
            )
        dataset = dataset.select(remaining) if remaining else []

    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(dataset)
    if total == 0 and resumed_results:
        print("All instances already completed.")
    elif total > 0:
        print(f"\n{total} task(s) to process")

    def process_single_instance(instance_data: tuple) -> InstanceResult:
        """Run one instance with its own evolved plan."""
        idx, n, instance = instance_data
        iid = instance["instance_id"]
        plan_path = instance_to_plan.get(iid)

        if plan_path is None:
            # Defensive: shouldn't happen because we filtered above.
            if args.workflow_file:
                plan_path = Path(args.workflow_file)
                print(
                    f"[{iid}] No per-instance plan; falling back to "
                    f"{plan_path}"
                )
            else:
                return InstanceResult(
                    instance_id=iid,
                    success=False,
                    error="no per-instance plan and no --task-plan-file fallback",
                )

        print(f"\n{'='*80}")
        print(f"[{idx}/{n}] Starting: {iid}")
        print(f"  using plan: {plan_path.name}")
        print(f"{'='*80}")

        # Per-thread copy of args so concurrent threads don't race on
        # `workflow_file`.
        per_args = copy.copy(args)
        per_args.workflow_file = str(plan_path)

        docker_client = None
        timeout_fired = {"v": False}
        TIMEOUT_SEC = int(getattr(args, "per_instance_timeout_sec", 10800))

        def _watchdog_fire():
            """At the timeout, forcibly tear down the agent's docker+MCP and
            inject a synthetic workflow_end into the event log so downstream
            parsers see a completed-looking trace.

            Known limitation: if the worker thread is blocked on a long httpx
            read (e.g. a local vLLM that stopped responding), closing Docker
            here does NOT unblock that thread — Python threads cannot be
            killed from outside, and LiteLLM/httpx may hold the socket
            indefinitely. To guarantee the driver makes progress, we schedule
            a GRACE-PERIOD SIGKILL of the whole driver process: if the
            watchdog fires and the worker doesn't cooperate within the grace
            period, we SIGKILL the driver. Resume at the run_e2e level picks
            up from the diff files that were already written.
            """
            timeout_fired["v"] = True
            print(f"[{iid}] WATCHDOG: exceeded {TIMEOUT_SEC}s — killing container "
                  f"and synthesizing workflow_end", flush=True)
            try:
                if docker_client is not None:
                    docker_client.close()
            except Exception:
                pass
            # Best-effort synthetic workflow_end appended to the events log.
            events_log = output_dir / f"{iid}_agent_events.log"
            try:
                events_log.parent.mkdir(parents=True, exist_ok=True)
                ev = {
                    "type": "workflow_end",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "total_tokens": 0, "prompt_tokens": 0,
                        "completion_tokens": 0, "total_steps": 0,
                        "output_dir": str(output_dir),
                        "final_file_path": "",
                        "reasoning_tokens": 0, "cost": 0.0,
                        "synthetic_timeout": True,
                        "timeout_sec": TIMEOUT_SEC,
                    },
                }
                with open(events_log, "a", encoding="utf-8") as f:
                    f.write(f"<<<EVENT>>>{json.dumps(ev)}<<</EVENT>>>\n")
            except Exception as e:
                print(f"[{iid}] WATCHDOG: failed to write synthetic workflow_end: {e}",
                      flush=True)

            # Grace-period driver-nuke: if the worker thread fails to exit
            # within `WATCHDOG_GRACE_SEC` seconds of the watchdog firing,
            # SIGKILL the whole driver so the outer run_e2e's --resume can
            # pick up. Without this, a single hung httpx read can pin the
            # entire driver for hours, and the other parallel workers that
            # finished cleanly sit around waiting for ThreadPoolExecutor to
            # shut down.
            WATCHDOG_GRACE_SEC = int(os.environ.get("WATCHDOG_GRACE_SEC", "600"))

            def _grace_and_nuke() -> None:
                _time.sleep(WATCHDOG_GRACE_SEC)
                # DANGER ZONE — do NOT call print(), sys.stdout.flush(),
                # logging, or anything else that goes through Python's
                # stdio stack. Stdout is almost always redirected to an
                # NFS-backed log file (e.g. under /shared/...); if NFS
                # is under backpressure or the filesystem write queue
                # stalls, print/flush blocks indefinitely. We observed
                # the driver surviving 49+ minutes past watchdog fire
                # because the pre-kill print() was wedged — SIGKILL
                # never issued.
                #
                # Strategy: log best-effort in a SEPARATE daemon thread
                # (so its blocking cannot prevent the kill), then kill
                # from THIS thread without touching stdio. If os.kill
                # somehow fails, fall back to os._exit(137) — skips
                # atexit handlers and Python stdio flushes.
                def _log_best_effort() -> None:
                    msg = (f"[{iid}] WATCHDOG: worker failed to exit "
                           f"within {WATCHDOG_GRACE_SEC}s grace — "
                           f"SIGKILL driver (resume will pick up from "
                           f"written diffs)\n").encode()
                    try:
                        os.write(2, msg)  # raw POSIX write to stderr fd
                    except Exception:
                        pass
                threading.Thread(target=_log_best_effort, daemon=True).start()
                # Brief window so the log attempt can land if stderr is
                # unblocked; don't wait long — kill is the contract.
                _time.sleep(0.1)
                try:
                    os.kill(os.getpid(), signal.SIGKILL)
                except Exception:
                    pass
                # Belt-and-suspenders — unreachable if SIGKILL delivered.
                os._exit(137)

            threading.Thread(target=_grace_and_nuke, daemon=True).start()

        watchdog = threading.Timer(TIMEOUT_SEC, _watchdog_fire)
        watchdog.daemon = True

        # Idle watchdog: fires when the event log stops growing for
        # IDLE_TIMEOUT_SEC (default 7200 = 2 h). Complements the fixed
        # TIMEOUT_SEC watchdog above. Either firing calls the same
        # _watchdog_fire path, which tears down Docker + writes synthetic
        # workflow_end + schedules grace-period driver SIGKILL.
        IDLE_TIMEOUT_SEC = int(getattr(args, "idle_timeout_sec", 7200))
        idle_wd: IdleWatchdog | None = None
        if IDLE_TIMEOUT_SEC > 0:
            idle_evt_log = output_dir / f"{iid}_agent_events.log"

            def _idle_fire() -> None:
                if not timeout_fired["v"]:
                    print(f"[{iid}] IDLE-WATCHDOG: no event-log growth for "
                          f"{IDLE_TIMEOUT_SEC}s — firing watchdog", flush=True)
                    _watchdog_fire()

            idle_wd = IdleWatchdog(event_log_path=idle_evt_log,
                                   idle_seconds=IDLE_TIMEOUT_SEC,
                                   poll_interval=30.0,
                                   warmup_seconds=min(600.0, IDLE_TIMEOUT_SEC / 4),
                                   on_stall=_idle_fire)
            idle_wd.start()

        try:
            image = DockerExecClient.resolve_image_name(iid)
            print(f"[{iid}] Starting SWE-bench container: {image} "
                  f"(watchdog={TIMEOUT_SEC}s)")
            docker_client = DockerExecClient(image=image)
            agent = AgentSPEX(mcp_client=docker_client)
            watchdog.start()
            result = run_instance(
                instance,
                agent,
                agent.mcp_client,
                per_args,
                output_dir,
                save_logs=args.save_logs,
            )
            if timeout_fired["v"]:
                print(f"[{iid}] Completed AFTER timeout fire (partial/empty result)")
                return InstanceResult(
                    instance_id=iid, success=False,
                    error=f"timeout_{TIMEOUT_SEC}s (watchdog killed agent)",
                )
            print(f"[{iid}] Completed successfully")
            return result
        except Exception as e:
            if timeout_fired["v"]:
                print(f"[{iid}] Error after watchdog kill: {e}")
                return InstanceResult(
                    instance_id=iid, success=False,
                    error=f"timeout_{TIMEOUT_SEC}s (watchdog killed agent)",
                )
            print(f"[{iid}] Error: {e}")
            return InstanceResult(
                instance_id=iid,
                success=False,
                error=str(e),
            )
        finally:
            watchdog.cancel()
            if idle_wd is not None:
                idle_wd.stop()
            if docker_client is not None:
                try:
                    docker_client.close()
                except Exception:
                    pass

    instance_data_list = [
        (i + 1, len(dataset), inst) for i, inst in enumerate(dataset)
    ]

    results: List[InstanceResult] = []
    if args.max_parallel > 1:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            futures = {
                executor.submit(process_single_instance, d): d[2]["instance_id"]
                for d in instance_data_list
            }
            for fut in as_completed(futures):
                iid = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    print(f"[{iid}] Unexpected error: {e}")
                    results.append(
                        InstanceResult(
                            instance_id=iid, success=False, error=str(e)
                        )
                    )
    else:
        for d in instance_data_list:
            results.append(process_single_instance(d))

    all_results = resumed_results + results

    # Always rewrite predictions.jsonl so it reflects resumed + new.
    predictions_file = output_dir / "predictions.jsonl"
    if predictions_file.exists():
        predictions_file.unlink()

    print(f"\n{'='*80}")
    print(f"Saving predictions to {predictions_file}")
    print(f"{'='*80}\n")

    for r in all_results:
        if r.success:
            save_patch_to_jsonl(
                r.instance_id, r.patch, args.model, predictions_file
            )

    successful = sum(1 for r in all_results if r.success)
    failed = len(all_results) - successful
    print(f"\n{'='*80}")
    print(
        f"Run complete: {successful}/{len(all_results)} patches generated "
        f"successfully"
        + (f" ({failed} failed)" if failed else "")
        + (
            f" ({len(resumed_results)} resumed)"
            if resumed_results
            else ""
        )
    )
    print(f"Predictions: {predictions_file}")
    print("\nTo evaluate with sb-cli:")
    print("  sb-cli submit swe-bench_verified test \\")
    print(f"      --predictions_path {predictions_file.resolve()} \\")
    print("      --run_id <your-run-id>")
    print(
        "  sb-cli get-report swe-bench_verified test <your-run-id> "
        "-o ./reports"
    )
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
