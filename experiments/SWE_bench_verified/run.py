"""SWE-Bench-Verified runner - main entry point.

Example usage:

# Run a single instance
python experiments/SWE_bench_verified/run.py \
    --instance-ids django__django-15280 \
    --model claude-opus-4-6 \
    --dashboard \
    --save-logs \
    --max-parallel 8 \
    --output-dir outputs/debug2

# Run a dataset subset in parallel
python experiments/SWE_bench_verified/run.py \
    --dataset jerry128/SWE-bench_Verified_subset_0 \
    --model claude-opus-4-6 \
    --max-parallel 8 \
    --no-exclude \
    --dashboard \
    --save-logs \
    --output-dir outputs/swe_bench_results

# Submit predictions for evaluation
sb-cli submit swe-bench_verified test \
    --predictions_path outputs/swe_bench_results/predictions.jsonl \
    --run_id my-run-id

sb-cli list-runs swe-bench_verified test
sb-cli get-report swe-bench_verified test my-run-id -o ./reports
"""

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Make experiments/ importable so this package resolves whether run directly or imported
# by a sibling runner (e.g. SWE_bench_LeanEvolve); sibling dirs reuse names like config.py.
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from SWE_bench_verified.config import (InstanceResult,
                                       load_excluded_instances,
                                       parse_args)
from SWE_bench_verified.docker_exec_client import DockerExecClient
from SWE_bench_verified.instance import (run_instance,
                                         save_patch_to_jsonl)
from datasets import load_dataset
from harness.agent import AgentSPEX
from harness.utils.idle_watchdog import IdleWatchdog

# Global dashboard process for signal handler access
_dashboard_proc: Optional[subprocess.Popen] = None
_dashboard_keep: bool = False


UNSAFE_PORTS = {
    5060,  # SIP
    5061,  # SIP-TLS
    6000,  # X11
    6566,  # SANE
    6665,
    6666,
    6667,
    6668,
    6669,  # IRC
}


def find_available_port(start_port: int) -> int:
    """Find an available port starting from start_port.

    Mimics the logic in run_agent.sh that finds the next available port.
    Skips ports that browsers block for security reasons.
    """
    port = start_port
    while port < start_port + 100:  # Try up to 100 ports
        if port in UNSAFE_PORTS:
            port += 1
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    # Fall back to original port if all are in use
    return start_port


def cleanup_dashboard() -> None:
    """Clean up dashboard process gracefully.

    Mimics the cleanup() function in run_agent.sh:
    - Check if process is still running
    - Send SIGTERM
    - Wait for process to exit
    """
    global _dashboard_proc
    if _dashboard_proc is None:
        return
    if _dashboard_keep:
        return

    try:
        # Check if process is still running (like kill -0 in bash)
        if _dashboard_proc.poll() is None:
            _dashboard_proc.terminate()
            try:
                # Wait for process to exit (like wait in bash)
                _dashboard_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't respond to SIGTERM
                _dashboard_proc.kill()
                _dashboard_proc.wait()
    except Exception:
        pass
    finally:
        _dashboard_proc = None


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    cleanup_dashboard()
    sys.exit(0)


def main():
    """Main entry point for the SWE-Bench runner."""
    global _dashboard_proc, _dashboard_keep

    args = parse_args()
    _dashboard_keep = args.dashboard_keep

    # Set up signal handlers for graceful shutdown (like trap in bash)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Register cleanup on normal exit
    atexit.register(cleanup_dashboard)

    try:
        if args.dashboard:
            _dashboard_proc = start_dashboard(args)

        run_full_pipeline(args)
    finally:
        cleanup_dashboard()


def _is_instance_completed(output_dir: Path, instance_id: str) -> bool:
    """Check if an instance already completed by looking for workflow_end in its events log."""
    event_log = output_dir / f"{instance_id}_agent_events.log"
    if not event_log.exists():
        return False
    try:
        with open(event_log, "rb") as f:
            f.seek(0, 2)
            pos = max(0, f.tell() - 4096)
            f.seek(pos)
            lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
        return bool(lines) and '"type": "workflow_end"' in lines[-1]
    except Exception:
        return False


def run_full_pipeline(args):
    """Run the full SWE-Bench pipeline: process instances and optionally evaluate."""
    print(f"Loading dataset {args.dataset} (split: {args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)

    if args.instance_ids:
        print(f"Filtering dataset for instance IDs: {args.instance_ids}")
        filtered_indices = []
        for i, instance in enumerate(dataset):
            if instance["instance_id"] in args.instance_ids:
                filtered_indices.append(i)

        if not filtered_indices:
            print(f"Error: None of the specified instance IDs found in dataset")
            print(
                f"Available instances: {[inst['instance_id'] for inst in dataset[:5]]}..."
            )
            sys.exit(1)

        dataset = dataset.select(filtered_indices)
        print(f"Found {len(dataset)} matching task(s)")

    # Filter out excluded instances (unless --no-exclude is set)
    if not args.no_exclude:
        excluded = load_excluded_instances(args.exclude_file)
        if excluded:
            filtered_indices = []
            excluded_ids = []
            for i, instance in enumerate(dataset):
                if instance["instance_id"] not in excluded:
                    filtered_indices.append(i)
                else:
                    excluded_ids.append(instance["instance_id"])

            if filtered_indices:
                dataset = dataset.select(filtered_indices)
            if excluded_ids:
                print(
                    f"Excluded {len(excluded_ids)} instance(s) from {args.exclude_file}"
                )

    # Apply limit if specified
    if args.limit and args.limit < len(dataset):
        dataset = dataset.select(range(args.limit))
        print(f"Limited to first {args.limit} instance(s)")

    print(f"\n{len(dataset)} task(s) to process")
    if args.max_parallel > 1:
        print(f"Running with max {args.max_parallel} parallel instances")

    # Create output directory
    output_dir = Path(args.output_dir)

    # Resume: skip instances that already completed (workflow_end in events log)
    resumed_results: List[InstanceResult] = []
    if getattr(args, "resume", False) and not output_dir.exists():
        print(
            f"Warning: --resume specified but output directory does not exist: {output_dir}"
        )
        print("Starting from scratch.")
    elif getattr(args, "resume", False):
        # Collect all existing .diff files from the output directory
        # so we can merge prior results into predictions.jsonl
        prior_diffs: dict = {}  # instance_id -> patch text
        for diff_file in output_dir.glob("*.diff"):
            patch = diff_file.read_text()
            if patch.strip():
                prior_diffs[diff_file.stem] = patch

        remaining_indices = []
        for i, instance in enumerate(dataset):
            iid = instance["instance_id"]
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
                remaining_indices.append(i)

        # Include .diff results from prior runs that are not in the current dataset,
        # but only if the instance actually completed (workflow_end in events log)
        for iid, patch in prior_diffs.items():
            if _is_instance_completed(output_dir, iid):
                resumed_results.append(
                    InstanceResult(instance_id=iid, success=True, patch=patch)
                )

        skipped = len(resumed_results)
        if skipped:
            print(f"Resuming: {skipped} instance(s) already completed, skipping")
        if remaining_indices:
            dataset = dataset.select(remaining_indices)
        else:
            dataset = []

    output_dir.mkdir(parents=True, exist_ok=True)

    total_tasks = len(dataset)
    if total_tasks == 0 and resumed_results:
        print("All instances already completed.")
    elif total_tasks > 0:
        print(f"\n{total_tasks} task(s) to process")

    def process_single_instance(instance_data: tuple) -> InstanceResult:
        """Process a single instance. Used by ThreadPoolExecutor.

        Guarded by two watchdogs (see _watchdog_fire): a hard wall-clock
        deadline (--per-instance-timeout-sec) and an idle/no-progress
        deadline (--idle-timeout-sec). Either firing tears down the
        container and writes a synthetic workflow_end so downstream parsers
        and --resume treat the instance as finished. The instance work runs
        in a daemon sub-thread, so if it stays wedged past the grace period
        (Python threads cannot be killed from outside) we abandon it and
        return a LOCAL timeout failure for this instance only — the rest of
        the run keeps going, and --resume can revisit it later. We never
        kill the whole driver.
        """
        idx, total, instance = instance_data
        instance_id = instance["instance_id"]

        print(f"\n{'='*80}")
        print(f"[{idx}/{total}] Starting: {instance_id}")
        print(f"{'='*80}")

        docker_client = None
        timeout_fired = {"v": False}
        TIMEOUT_SEC = int(getattr(args, "per_instance_timeout_sec", 7200))
        IDLE_TIMEOUT_SEC = int(getattr(args, "idle_timeout_sec", 7200))
        events_log = output_dir / f"{instance_id}_agent_events.log"
        WATCHDOG_GRACE_SEC = int(os.environ.get("WATCHDOG_GRACE_SEC", "600"))
        # Set when the worker sub-thread finishes (normally or via exception).
        worker_done = threading.Event()
        # Armed by the watchdog WATCHDOG_GRACE_SEC after it fires: the cue to
        # stop waiting on a wedged worker and record a local timeout failure.
        giveup = threading.Event()

        def _watchdog_fire():
            timeout_fired["v"] = True
            print(
                f"[{instance_id}] WATCHDOG: exceeded deadline — killing container "
                f"and synthesizing workflow_end",
                flush=True,
            )
            try:
                if docker_client is not None:
                    docker_client.close()
            except Exception:
                pass
            # Synthetic workflow_end so parsers / --resume see a completed trace.
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
                print(
                    f"[{instance_id}] WATCHDOG: failed to write synthetic "
                    f"workflow_end: {e}",
                    flush=True,
                )

            # Grace period, then give up LOCALLY (no driver-wide SIGKILL).
            # If the worker doesn't exit within WATCHDOG_GRACE_SEC of the
            # watchdog firing, we stop waiting on it and record a timeout
            # failure for THIS instance only — the rest of the run keeps
            # going. The worker runs as a daemon thread (see below), so a
            # genuinely wedged worker (C-level rich spin, hung httpx read)
            # is abandoned and reaped when the driver exits, instead of
            # taking the whole ThreadPoolExecutor down with it.
            def _arm_giveup() -> None:
                _time.sleep(WATCHDOG_GRACE_SEC)
                giveup.set()

            threading.Thread(target=_arm_giveup, daemon=True).start()

        watchdog = None
        if TIMEOUT_SEC > 0:
            watchdog = threading.Timer(TIMEOUT_SEC, _watchdog_fire)
            watchdog.daemon = True

        idle_wd: Optional[IdleWatchdog] = None
        if IDLE_TIMEOUT_SEC > 0:
            def _idle_fire() -> None:
                if not timeout_fired["v"]:
                    print(
                        f"[{instance_id}] IDLE-WATCHDOG: no event-log growth for "
                        f"{IDLE_TIMEOUT_SEC}s — firing watchdog",
                        flush=True,
                    )
                    _watchdog_fire()

            idle_wd = IdleWatchdog(
                event_log_path=events_log,
                idle_seconds=IDLE_TIMEOUT_SEC,
                poll_interval=30.0,
                warmup_seconds=min(600.0, IDLE_TIMEOUT_SEC / 4),
                on_stall=_idle_fire,
            )
            idle_wd.start()

        # The actual instance work runs in a DAEMON sub-thread so this pool
        # worker can never wedge: a hung run_instance() would otherwise pin a
        # ThreadPoolExecutor slot forever and hang the whole driver at
        # shutdown. Isolating it lets us stop waiting after the grace period,
        # record a LOCAL timeout failure, and let the rest of the run proceed;
        # the abandoned daemon thread is reaped when the driver exits.
        work: dict = {}  # 'result' on success, 'error' on exception

        def _run_work() -> None:
            try:
                work["result"] = run_instance(
                    instance,
                    agent,
                    agent.mcp_client,
                    args,
                    output_dir,
                    save_logs=args.save_logs,
                )
            except Exception as e:  # surfaced to the outer handler below
                work["error"] = e
            finally:
                worker_done.set()

        try:
            image = DockerExecClient.resolve_image_name(instance_id)
            print(
                f"[{instance_id}] Starting SWE-bench container: {image} "
                f"(watchdog={TIMEOUT_SEC}s, idle={IDLE_TIMEOUT_SEC}s)"
            )
            docker_client = DockerExecClient(image=image)
            agent = AgentSPEX(mcp_client=docker_client)
            if watchdog is not None:
                watchdog.start()

            worker_thread = threading.Thread(
                target=_run_work,
                name=f"swebench-worker[{instance_id}]",
                daemon=True,
            )
            worker_thread.start()

            # Wait for the worker, but never indefinitely on a wedged one:
            # once the watchdog's grace period expires (giveup) we abandon it.
            while not worker_done.wait(timeout=2.0):
                if giveup.is_set():
                    break

            if not worker_done.is_set():
                # Worker still alive after grace — abandon it LOCALLY. The
                # synthetic workflow_end was already written by _watchdog_fire,
                # so --resume treats this instance as finished and the rest of
                # the run is untouched.
                print(
                    f"[{instance_id}] WATCHDOG: worker failed to exit within "
                    f"{WATCHDOG_GRACE_SEC}s grace — abandoning wedged worker and "
                    f"recording a local timeout failure (run continues)",
                    flush=True,
                )
                return InstanceResult(
                    instance_id=instance_id,
                    success=False,
                    error=f"timeout_{TIMEOUT_SEC}s (watchdog abandoned wedged worker)",
                )

            if "error" in work:
                e = work["error"]
                if timeout_fired["v"]:
                    print(f"[{instance_id}] Error after watchdog kill: {e}")
                    return InstanceResult(
                        instance_id=instance_id,
                        success=False,
                        error=f"timeout_{TIMEOUT_SEC}s (watchdog killed agent)",
                    )
                print(f"[{instance_id}] Error: {e}")
                return InstanceResult(
                    instance_id=instance_id,
                    success=False,
                    error=str(e),
                )

            if timeout_fired["v"]:
                print(f"[{instance_id}] Completed AFTER timeout fire (partial result)")
                return InstanceResult(
                    instance_id=instance_id,
                    success=False,
                    error=f"timeout_{TIMEOUT_SEC}s (watchdog killed agent)",
                )
            print(f"[{instance_id}] Completed successfully")
            return work["result"]
        except Exception as e:
            # Setup-path failure in the pool thread itself (image resolve,
            # container start, agent construction). Record it locally so the
            # run — and, in sequential mode, the driver loop — keeps going.
            if timeout_fired["v"]:
                print(f"[{instance_id}] Error after watchdog kill: {e}")
                return InstanceResult(
                    instance_id=instance_id,
                    success=False,
                    error=f"timeout_{TIMEOUT_SEC}s (watchdog killed agent)",
                )
            print(f"[{instance_id}] Error: {e}")
            return InstanceResult(
                instance_id=instance_id,
                success=False,
                error=str(e),
            )
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if idle_wd is not None:
                idle_wd.stop()
            # Close docker only when the worker has actually finished. If we
            # abandoned a wedged worker, _watchdog_fire already closed the
            # client; closing again here could race the still-live daemon.
            if docker_client is not None and worker_done.is_set():
                try:
                    docker_client.close()
                except Exception:
                    pass

    # Prepare instance data with index info
    instance_data_list = [
        (i + 1, len(dataset), instance) for i, instance in enumerate(dataset)
    ]

    # Process instances (parallel or sequential based on max_parallel)
    results: List[InstanceResult] = []
    if args.max_parallel > 1:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            future_to_instance = {
                executor.submit(process_single_instance, data): data[2]["instance_id"]
                for data in instance_data_list
            }

            for future in as_completed(future_to_instance):
                instance_id = future_to_instance[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f"[{instance_id}] Unexpected error: {e}")
                    results.append(
                        InstanceResult(
                            instance_id=instance_id,
                            success=False,
                            error=str(e),
                        )
                    )
    else:
        # Sequential execution
        for data in instance_data_list:
            result = process_single_instance(data)
            results.append(result)

    # Merge resumed and new results
    all_results = resumed_results + results

    # Save all patches to JSONL format (always rewrite to include resumed + new)
    predictions_file = output_dir / "predictions.jsonl"
    if predictions_file.exists():
        predictions_file.unlink()

    print(f"\n{'='*80}")
    print(f"Saving predictions to {predictions_file}")
    print(f"{'='*80}\n")

    for result in all_results:
        if result.success:
            save_patch_to_jsonl(
                result.instance_id, result.patch, args.model, predictions_file
            )

    # Print summary
    successful = sum(1 for r in all_results if r.success)
    failed = len(all_results) - successful
    print(f"\n{'='*80}")
    print(
        f"Run complete: {successful}/{len(all_results)} patches generated successfully"
        + (f" ({failed} failed)" if failed else "")
        + (f" ({len(resumed_results)} resumed)" if resumed_results else "")
    )
    print(f"Predictions: {predictions_file}")
    print(f"\nTo evaluate with sb-cli:")
    print(f"  sb-cli submit swe-bench_verified test \\")
    print(f"      --predictions_path {predictions_file.resolve()} \\")
    print(f"      --run_id <your-run-id>")
    print(f"  sb-cli get-report swe-bench_verified test <your-run-id> -o ./reports")
    print(f"{'='*80}\n")


def start_dashboard(args) -> subprocess.Popen:
    """Start dashboard pointing at output directory logs.

    Finds an available port starting from args.dashboard_port,
    similar to the logic in run_agent.sh.
    """
    repo_root = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
    log_root = repo_root / "outputs"
    log_root.mkdir(parents=True, exist_ok=True)
    script_path = repo_root / "scripts" / "dashboard.py"

    requested_port = args.dashboard_port
    if requested_port in UNSAFE_PORTS:
        print(
            f"Warning: Port {requested_port} is blocked by browsers (ERR_UNSAFE_PORT)"
        )
    port = find_available_port(requested_port)
    if port != requested_port:
        print(f"Port {requested_port} unavailable, using port {port}")

    cmd = [
        sys.executable,
        str(script_path),
        "--log-root",
        str(log_root),
        "--port",
        str(port),
        "--no-auto-close",
    ]
    if args.dashboard_no_browser:
        cmd.append("--no-browser")
    print(f"Starting dashboard: {' '.join(cmd)}")
    print(f"Dashboard: http://127.0.0.1:{port}")
    return subprocess.Popen(cmd)


if __name__ == "__main__":
    main()
