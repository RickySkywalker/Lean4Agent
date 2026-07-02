#!/usr/bin/env python3
"""
run_plan_evolve.py - Outer batch driver for step 3 (Lean-guided YAML plan
evolution). Mirrors `run_agent_evolve.py`'s surface (`--limit`, `--resume`,
`--max_parallel`, `--dry_run`) and reuses its staging / PTY / SIGWINCH
infrastructure by importing from the same package.

For each SWE-bench instance this driver:

  1. Stages the original YAML plan + step 2's `layer3_query.json` +
     `eval_evidence.json` into `<staging_root>/inputs/<inst>/`.
  2. Runs `scripts/run_agent.sh` on `evolve_plan.yaml`, passing per-instance
     paths via environment variables. All paths are container-view
     (`/workspace/...`) because the YAML's `shell_run` tool can only see
     files under `/workspace/`.
  3. After the YAML completes, copies the validated `evolved_plan.yaml` from
     `<staging_root>/outputs/<inst>/` to the durable smoke-test location
     (`experiments/SWE_bench_verified/layer3_smoke_test/Lean_guided_modification/
     passed_workflow_1_<inst>_lean.yaml`) which step 4 consumes.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Reuse step 2's PTY / SIGWINCH / staging machinery.
from run_agent_evolve import (  # type: ignore
    _STDOUT_LOCK,
    _ACTIVE_CHILDREN,
    _ACTIVE_CHILDREN_LOCK,
    _read_pty_stream,
    _spawn_with_pty,
    _install_winch_handler_once,
    _MIN_CHILD_COLUMNS,
)
import run_agent_evolve as _step2  # for setting module-level globals
from staging_paths import (
    LEAN_REPL_SUBDIR,
    PACKAGE_SUBDIR,
    lean_repl_staging_path,
    step2_eval_evidence_path,
    step3_instance_inputs_dir,
    step3_instance_staging_dir,
    step3_instance_outputs_dir,
    step3_instance_runtime_dir,
    durable_evolved_plan_path,
    SMOKE_TEST_LEAN_GUIDED_SUBDIR,
    STEP3_INPUT_ORIGINAL_YAML,
    STEP3_INPUT_LAYER3_QUERY,
    STEP3_INPUT_EVAL_EVIDENCE,
    STEP3_STAGING_WORKING_YAML,
    STEP3_STAGING_DIGEST,
    STEP3_OUTPUT_EVOLVED_YAML,
    STEP3_OUTPUT_VALIDATION_REPORT,
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())

PACKAGE_FILES = [
    "EditYaml.py",
    "EditJson.py",
    "lean_report_loader.py",
    "plan_validator.py",
    "failure_pattern_templates.json",
    "classify_failure.py",
    "inject_verify_directives.py",
]


def find_instances(source_staging_root: Path, plan_name: str) -> list[str]:
    """Enumerate instances by the `layer3_query.json` files step 2 produced."""
    lean_repl = source_staging_root / LEAN_REPL_SUBDIR
    if not lean_repl.exists():
        return []
    out: list[str] = []
    prefix = f"{plan_name}_"
    for p in sorted(lean_repl.glob(f"{prefix}*.json")):
        name = p.name[len(prefix):-len(".json")]
        if name:
            out.append(name)
    return out


def stage_shared(staging_root: Path, yaml_plan: Path) -> None:
    pkg = staging_root / PACKAGE_SUBDIR
    pkg.mkdir(parents=True, exist_ok=True)
    for fname in PACKAGE_FILES:
        src = HERE / fname
        if src.exists():
            shutil.copy2(src, pkg / fname)
    shutil.copy2(yaml_plan, staging_root / yaml_plan.name)
    # Per-run shared ledger directory for classify_failure.py's cross-instance
    # frequency cap. Created here so stage_workspace can reference it.
    (staging_root / "shared_ledger").mkdir(parents=True, exist_ok=True)


def stage_workspace(workspace_root: Path, staging_root: Path, instance_id: str,
                    source_staging_root: Path, plan_name: str,
                    original_plan_yaml: Path, yaml_plan: Path) -> dict:
    """Copy per-instance inputs into `<staging_root>/inputs/<inst>/`. Returns
    a dict of container-view paths the YAML's env vars will point at."""
    ws_root = staging_root
    pkg = ws_root / PACKAGE_SUBDIR
    inputs = step3_instance_inputs_dir(ws_root, instance_id)
    staging = step3_instance_staging_dir(ws_root, instance_id)
    outputs = step3_instance_outputs_dir(ws_root, instance_id)
    for p in (inputs, staging, outputs):
        p.mkdir(parents=True, exist_ok=True)

    # Source files from step 2's staging.
    src_query = lean_repl_staging_path(source_staging_root, plan_name, instance_id)
    src_eval = step2_eval_evidence_path(source_staging_root, instance_id)
    if not src_query.exists():
        raise FileNotFoundError(
            f"Step 2's layer3_query.json not found for {instance_id}: {src_query}")
    if not src_eval.exists():
        raise FileNotFoundError(
            f"Step 2's eval_evidence.json not found for {instance_id}: {src_eval}")

    ws_original = inputs / STEP3_INPUT_ORIGINAL_YAML
    ws_query = inputs / STEP3_INPUT_LAYER3_QUERY
    ws_eval = inputs / STEP3_INPUT_EVAL_EVIDENCE
    shutil.copy2(original_plan_yaml, ws_original)
    shutil.copy2(src_query, ws_query)
    shutil.copy2(src_eval, ws_eval)

    # The working plan lives under staging/ so it is disposable/idempotent.
    ws_working = staging / STEP3_STAGING_WORKING_YAML

    def c_path(host_path: Path) -> str:
        rel = host_path.resolve().relative_to(workspace_root.resolve())
        return f"/workspace/{rel}"

    shared_ledger_host = ws_root / "shared_ledger"
    shared_ledger_host.mkdir(parents=True, exist_ok=True)
    return {
        "workspace_root":        workspace_root,
        "ws_root_host":          ws_root,
        "ws_root_container":     c_path(ws_root),
        "package_dir_container": c_path(pkg),
        "staging_dir_container": c_path(staging),
        "staging_dir_host":      staging,
        "outputs_dir_container": c_path(outputs),
        "outputs_dir_host":      outputs,
        "original_plan_container": c_path(ws_original),
        "working_plan_container":  c_path(ws_working),
        "working_plan_host":       ws_working,
        "layer3_query_container":  c_path(ws_query),
        "eval_evidence_container": c_path(ws_eval),
        "yaml_plan_container":     c_path(ws_root / yaml_plan.name),
        "shared_ledger_container": c_path(shared_ledger_host),
    }


def _is_instance_complete(durable_path: Path, validation_report_path: Path) -> bool:
    """An instance is complete iff the durable evolved plan exists. The
    durable copy is gated on validation passing at write time (see
    `run_instance`), so a durable file on disk is itself proof that some
    pipeline run produced and validated it. The validation_report.json is
    only advisory: if it happens to exist AND shows `pass: true`, that's a
    stronger signal, but if a later run overwrote it with `pass: false` (e.g.
    a different model reusing the same workspace staging dir), we should NOT
    invalidate the known-good durable file."""
    if not durable_path.exists():
        return False
    if validation_report_path.exists():
        try:
            rep = json.loads(validation_report_path.read_text(encoding="utf-8"))
            if not bool((rep.get("summary") or {}).get("pass")):
                # Report says fail — check if it was written AFTER the durable
                # file. If it was written BEFORE (or by a different run with a
                # different model), trust the durable and resume anyway.
                try:
                    if (validation_report_path.stat().st_mtime <=
                            durable_path.stat().st_mtime):
                        return True  # durable is newer / equal → trust it
                    # Report is newer than durable AND says fail → do not resume.
                    return False
                except OSError:
                    return True
        except Exception:
            pass
    return True


def _prior_validation_failed(validation_report_path: Path) -> tuple[bool, list]:
    """Return (failed, failing_checks). `failed` is True iff a prior run wrote
    `validation_report.json` and its summary says `pass: false`. Used to detect
    instances that completed all 13 LLM steps but produced an evolved plan
    that didn't satisfy the structural validator — re-running them with a
    near-deterministic LLM will just reproduce the same failure, so by default
    we skip them rather than burn the same compute again."""
    if not validation_report_path.exists():
        return False, []
    try:
        rep = json.loads(validation_report_path.read_text(encoding="utf-8"))
    except Exception:
        return False, []
    summary = rep.get("summary") or {}
    if summary.get("pass") is False:
        # plan_validator.py emits `failing_checks` as an integer count, but
        # some earlier schema versions emitted a list of check names. Accept
        # either: a list passes through, an int becomes a summary tuple, any
        # other scalar gets coerced to a one-element list.
        fc = summary.get("failing_checks")
        if isinstance(fc, list):
            failing = fc
        elif isinstance(fc, int):
            # Pull failing check names from the `checks` array if present.
            failing = [c.get("check") for c in (rep.get("checks") or [])
                       if isinstance(c, dict) and not c.get("pass")]
            if not failing:
                failing = [f"{fc} failing check(s) (names unavailable)"]
        elif fc is None:
            failing = []
        else:
            failing = [str(fc)]
        return True, failing
    return False, []


def run_instance(instance_id: str,
                 source_staging_root: Path,
                 staging_root: Path,
                 workspace_root: Path,
                 plan_name: str,
                 original_plan_yaml: Path,
                 yaml_plan: Path,
                 smoke_test_output_dir: Path,
                 conda_env: str,
                 dry_run: bool,
                 stream_logs: bool,
                 child_columns: int,
                 child_lines: int,
                 resume: bool,
                 retry_failed_validation: bool = False) -> dict:
    result: dict = {
        "instance_id": instance_id,
        "status": "unknown",
        "yaml_returncode": None,
        "error": None,
        "resume_actions": [],
    }

    durable_output = smoke_test_output_dir / f"{plan_name}_{instance_id}_lean.yaml"
    outputs_dir = step3_instance_outputs_dir(staging_root, instance_id)
    validation_report = outputs_dir / STEP3_OUTPUT_VALIDATION_REPORT

    if resume and _is_instance_complete(durable_output, validation_report):
        result["status"] = "resumed_complete"
        result["resume_actions"].append(
            f"durable evolved plan + passing validation already present: {durable_output}")
        result["durable_output"] = str(durable_output)
        if dry_run:
            result["status"] = "dry_run_would_skip_complete"
        return result

    # Skip instances whose previous run completed all LLM steps but produced
    # an evolved plan the structural validator rejected. Re-running them with
    # an effectively deterministic LLM just reproduces the same failure and
    # burns the same 13 LLM calls. Pass --retry_failed_validation to override.
    if resume and not retry_failed_validation:
        prev_failed, failing = _prior_validation_failed(validation_report)
        if prev_failed:
            result["status"] = "previously_failed_validation"
            result["validation_report"] = str(validation_report)
            result["validation_summary"] = {"pass": False, "failing_checks": failing}
            result["error"] = (
                f"prior run completed all steps but validation rejected the "
                f"evolved plan (failing_checks={failing}). "
                f"Pass --retry_failed_validation to force a fresh re-run."
            )
            if dry_run:
                result["status"] = "dry_run_would_skip_failed_validation"
            return result

    if dry_run:
        result["status"] = "dry_run"
        result["command"] = "(would stage + run evolve_plan.yaml + copy to durable)"
        return result

    # Stage per-instance workspace.
    try:
        stage = stage_workspace(workspace_root, staging_root, instance_id,
                                source_staging_root, plan_name,
                                original_plan_yaml, yaml_plan)
    except FileNotFoundError as e:
        result["status"] = "skipped_missing_input"
        result["error"] = str(e)
        return result

    # Build env for the YAML agent.
    env = os.environ.copy()
    # Disable per-step workspace-manifest snapshots for this Stage B
    # subprocess. With HOST_WORKSPACE set, the AgentSPEX scans the entire
    # <workspace_root> after every step and copies every file >1 MB to
    # <workspace_backup_path>. Under concurrent runs (multiple evolve
    # workers sharing /workspace), this thrashes NFS I/O and causes
    # OSError(EIO) on the next LLM call — especially lethal for local
    # vLLM endpoints (Gemma4) where httpx and the disk compete on the
    # same host. Stage B's durable output is just evolved_plan.yaml in
    # stage["outputs_dir_container"]; no manifest snapshot needed.
    #
    # NOTE: HOST_WORKSPACE itself is re-exported by `source config/
    # host.env` inside scripts/run_agent.sh (with `set -a`), so
    # clearing it here is not enough. We also flip the
    # DISABLE_WORKSPACE_MANIFEST switch that agent.py reads from the
    # process environment; host.env does not mention that var, so the
    # source call cannot overwrite it.
    #
    # For OPENAI_API_KEY / VLLM_API_BASE / MODEL_NAME (and the other
    # provider keys) the situation is the opposite: scripts/run_agent.sh
    # now snapshots any caller-exported value before sourcing vm.env/
    # host.env and restores it afterwards, so whatever the user exported
    # (e.g. via `source experiments/SWE_bench_verified/<model>_config.
    # env`) reaches the inner `python -m agent.run` intact.
    env["HOST_WORKSPACE"] = ""
    env["DISABLE_WORKSPACE_MANIFEST"] = "1"
    env.update({
        "INSTANCE_ID":          instance_id,
        "PLAN_NAME":            plan_name,
        "ORIGINAL_PLAN_YAML":   stage["original_plan_container"],
        "WORKING_PLAN_YAML":    stage["working_plan_container"],
        "LAYER3_QUERY_PATH":    stage["layer3_query_container"],
        "SOURCE_EVAL_EVIDENCE": stage["eval_evidence_container"],
        "STAGING_DIR":          stage["staging_dir_container"],
        "INSTANCE_OUTPUT_DIR":  stage["outputs_dir_container"],
        "PACKAGE_DIR":          stage["package_dir_container"],
        # Shared-state ledger so the classifier's cross-instance frequency cap
        # (see classify_failure.py / evolve_plan.yaml) can span this entire run
        # rather than just one instance. All per-instance invocations read/
        # write the same JSON under <shared_ledger_dir>/template_frequency.json.
        "SHARED_LEDGER_DIR":    stage.get(
            "shared_ledger_container",
            "/workspace/plan_evolve_shared_ledger"),
        # The driver's default cap: ceil(total_instances / 3) gives each
        # template ~1/3 of the run at most. Overridable via env.
        "TEMPLATE_FREQUENCY_CAP": os.environ.get(
            "TEMPLATE_FREQUENCY_CAP",
            str(max(3, (stage.get("total_instances") or 12) // 3))),
    })
    # Drop any inherited COLUMNS/LINES so Rich in the child reads the live PTY
    # size via os.get_terminal_size(fd) and picks up SIGWINCH updates. If
    # COLUMNS is pinned in env, shutil.get_terminal_size() short-circuits and
    # never re-reads the PTY even after our handler pushes new dimensions.
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    env.setdefault("FORCE_COLOR", "1")
    env.setdefault("CLICOLOR_FORCE", "1")

    run_agent = REPO_ROOT / "scripts" / "run_agent.sh"
    if not run_agent.exists():
        result["status"] = "error"
        result["error"] = f"scripts/run_agent.sh not found at {run_agent}"
        return result

    runtime_dir = step3_instance_runtime_dir(staging_root, instance_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # Resume the inner AgentSPEX from its own checkpoint when one exists.
    # Without this, scripts/run_agent.sh rotates checkpoint.json out of the
    # way and starts from step 1 — wasting all the LLM calls from a run that
    # was interrupted (Ctrl+C, OOM, etc.) partway through. We only opt in
    # when the runtime dir actually has a checkpoint.json so a fresh instance
    # behaves identically to before.
    #
    # Exception: if we got here via --retry_failed_validation, the prior
    # checkpoint says "all 13 steps done" — resuming would short-circuit
    # straight to the same failed evolved_plan.yaml. Force a fresh restart
    # in that case (the inner script auto-rotates the stale checkpoint).
    inner_resume_args = ""
    checkpoint_path = runtime_dir / "checkpoint.json"
    prev_failed_now_retrying = (resume and retry_failed_validation
                                and _prior_validation_failed(validation_report)[0])
    if resume and checkpoint_path.exists() and not prev_failed_now_retrying:
        inner_resume_args = " --resume"
        result["resume_actions"].append(
            f"inner agent --resume from existing checkpoint: {checkpoint_path}")
    elif prev_failed_now_retrying:
        result["resume_actions"].append(
            "retry_failed_validation: forcing fresh inner-agent restart "
            "(stale checkpoint will be auto-rotated by run_agent.sh)")

    cmd_parts = [
        f"source {shlex.quote(str(REPO_ROOT))}/config/host.env >/dev/null 2>&1 || true",
        'source "$(conda info --base)/etc/profile.d/conda.sh"',
        f"conda activate {shlex.quote(conda_env)}",
        f"export PYTHONPATH={shlex.quote(str(REPO_ROOT / 'engine' / 'src'))}:${{PYTHONPATH:-}}",
        ("bash "
         f"{shlex.quote(str(run_agent))} "
         f"{shlex.quote(str(yaml_plan))} "
         f"--no_dashboard "
         f"--output_dir {shlex.quote(str(runtime_dir))}"
         f"{inner_resume_args}"),
    ]
    cmd_str = " && ".join(cmd_parts)

    driver_log_path = runtime_dir / "driver.log"
    t0 = time.time()
    init_rows = child_lines if child_lines > 0 else 40
    init_cols = child_columns if child_columns > 0 else 120
    proc, master_fd = _spawn_with_pty(
        ["bash", "-c", cmd_str], cwd=str(REPO_ROOT), env=env,
        rows=init_rows, cols=init_cols,
    )
    with _ACTIVE_CHILDREN_LOCK:
        _ACTIVE_CHILDREN[proc.pid] = (master_fd, instance_id)
    try:
        all_lines, tail = _read_pty_stream(master_fd, instance_id, stream_logs)
    finally:
        with _ACTIVE_CHILDREN_LOCK:
            _ACTIVE_CHILDREN.pop(proc.pid, None)
        try:
            os.close(master_fd)
        except OSError:
            pass
    proc.wait()

    driver_log_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    result["yaml_runtime_sec"] = round(time.time() - t0, 2)
    result["yaml_returncode"] = proc.returncode
    result["yaml_output_tail"] = "\n".join(tail)
    result["driver_log"] = str(driver_log_path)

    evolved_host = outputs_dir / STEP3_OUTPUT_EVOLVED_YAML
    if not evolved_host.exists():
        result["status"] = "yaml_failed"
        result["error"] = (f"YAML exit={proc.returncode}; evolved_plan.yaml not produced "
                           f"at {evolved_host}")
        return result

    # Gate the durable copy on validation_report.json showing all checks pass.
    if not validation_report.exists():
        result["status"] = "no_validation_report"
        result["error"] = f"validation_report.json not found at {validation_report}"
        return result
    try:
        rep = json.loads(validation_report.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "validation_report_unreadable"
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    summary = rep.get("summary") or {}
    result["validation_summary"] = summary
    if not summary.get("pass"):
        result["status"] = "validation_failed"
        result["error"] = (f"validation did not pass: "
                           f"failing_checks={summary.get('failing_checks')}")
        return result

    # All good - copy to durable location for step 4.
    smoke_test_output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(evolved_host, durable_output)
    result["durable_output"] = str(durable_output)
    result["status"] = "ok"
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description="Batch runner for step 3 (Lean-guided YAML plan evolution).")
    p.add_argument("--source_staging_root", required=True,
                   help=("Step 2's staging root, e.g. "
                         "workspace/agent_evolve_run/staging_gpt52. Must contain "
                         "lean_repl/<plan>_<inst>.json for each instance."))
    p.add_argument("--staging_root", default="",
                   help=("Step 3's own staging root, e.g. "
                         "workspace/agent_evolve_run/staging_gpt52_evolve. "
                         "Must be inside --workspace_root. Default: "
                         "<workspace_root>/agent_evolve_run/staging_evolve."))
    p.add_argument("--plan_name", default="passed_workflow_1")
    p.add_argument("--original_plan_yaml", required=True,
                   help="Path to the original SWE-bench YAML plan (the plan to evolve).")
    p.add_argument("--yaml_plan", default=str(HERE / "evolve_plan.yaml"),
                   help="Path to evolve_plan.yaml.")
    p.add_argument("--smoke_test_output_dir",
                   default=str(REPO_ROOT / SMOKE_TEST_LEAN_GUIDED_SUBDIR),
                   help=("Directory that receives the durable evolved plans "
                         "(<plan_name>_<inst>_lean.yaml). Default mirrors the "
                         "existing skill-produced reference outputs."))
    p.add_argument("--workspace_root",
                   default="workspace",
                   help="Host path the sandbox Docker mounts as /workspace.")
    p.add_argument("--conda_env", default="agent_env")
    p.add_argument("--single_instance", default="")
    p.add_argument("--instance_ids", default="",
                   help="Comma-separated whitelist of instance IDs to process "
                        "(matching against lean_repl/<plan>_<inst>.json outputs "
                        "of Stage A). Overrides --limit ordering.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max_parallel", type=int, default=1)
    p.add_argument("--stream_logs", action="store_true", default=True)
    p.add_argument("--no_stream_logs", dest="stream_logs", action="store_false")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--retry_failed_validation", action="store_true",
                   help="When --resume sees a prior validation_report.json that "
                        "says fail, do not skip — force a fresh re-run. Without "
                        "this flag, instances whose prior run completed all "
                        "steps but failed structural validation are skipped "
                        "(status=previously_failed_validation) to avoid burning "
                        "the same compute on a near-deterministic LLM.")
    p.add_argument("--dry_run", action="store_true")
    p.add_argument("--summary", default="",
                   help="Where to write the JSON summary. Default: <staging_root>/_summary.json")
    args = p.parse_args()

    source_staging_root = Path(args.source_staging_root).resolve()
    original_plan_yaml = Path(args.original_plan_yaml).resolve()
    yaml_plan = Path(args.yaml_plan).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    smoke_test_output_dir = Path(args.smoke_test_output_dir).resolve()

    if not source_staging_root.exists():
        print(f"ERROR: --source_staging_root not found: {source_staging_root}", file=sys.stderr)
        return 1
    if not original_plan_yaml.exists():
        print(f"ERROR: --original_plan_yaml not found: {original_plan_yaml}", file=sys.stderr)
        return 1
    if not yaml_plan.exists():
        print(f"ERROR: --yaml_plan not found: {yaml_plan}", file=sys.stderr)
        return 1
    if not workspace_root.exists():
        print(f"ERROR: --workspace_root not found: {workspace_root}", file=sys.stderr)
        return 1

    if args.staging_root:
        staging_root = Path(args.staging_root).resolve()
    else:
        staging_root = workspace_root / "agent_evolve_run" / "staging_evolve"
    try:
        staging_root.relative_to(workspace_root)
    except ValueError:
        print(f"ERROR: --staging_root ({staging_root}) must be inside --workspace_root "
              f"({workspace_root}) so the sandbox Docker can see it under /workspace/.",
              file=sys.stderr)
        return 1
    staging_root.mkdir(parents=True, exist_ok=True)

    # Enumerate instances.
    if args.single_instance:
        instances = [args.single_instance]
    elif args.instance_ids:
        requested = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        available = set(find_instances(source_staging_root, args.plan_name))
        missing = [i for i in requested if i not in available]
        if missing:
            print(f"WARNING: {len(missing)} requested instance(s) not found under "
                  f"{source_staging_root / 'lean_repl'}: {missing}", flush=True)
        instances = [i for i in requested if i in available]
    else:
        instances = find_instances(source_staging_root, args.plan_name)
    if not instances:
        print(f"ERROR: no instances found under {source_staging_root / LEAN_REPL_SUBDIR}",
              file=sys.stderr)
        return 1

    # Apply --limit after filtering (resume itself handles per-instance skip).
    summary: list[dict] = []
    to_process: list[tuple[int, int, str]] = []
    total = len(instances)
    selected = 0
    for idx, inst in enumerate(instances, 1):
        if args.limit and selected >= args.limit:
            print(f"[limit] reached --limit={args.limit}; stopping "
                  f"after selecting {selected} (out of {total} found).", flush=True)
            break
        to_process.append((idx, total, inst))
        selected += 1

    if not to_process:
        print("No instances to process.", flush=True)
        return 0

    print(f"\n{len(to_process)} instance(s) queued "
          f"(max_parallel={args.max_parallel}, dry_run={args.dry_run}, resume={args.resume})",
          flush=True)

    if not args.dry_run:
        stage_shared(staging_root, yaml_plan)

    # Width / height for child PTYs.
    try:
        term_cols, term_lines = shutil.get_terminal_size(fallback=(120, 40))
    except Exception:
        term_cols, term_lines = 120, 40
    longest_inst = max((len(x[2]) for x in to_process), default=0)
    prefix_pad = longest_inst + 3
    if args.stream_logs:
        child_columns = max(_MIN_CHILD_COLUMNS, term_cols - prefix_pad)
    else:
        child_columns = max(120, term_cols)
    child_lines = term_lines

    _step2._PREFIX_PAD = prefix_pad
    _step2._STREAM_LOGS_ENABLED = bool(args.stream_logs)
    if not args.dry_run:
        _install_winch_handler_once()

    def _work(item: tuple[int, int, str]) -> dict:
        idx, tot, inst = item
        with _STDOUT_LOCK:
            print(f"[{idx}/{tot}] {inst} -> starting", flush=True)
        r = run_instance(inst, source_staging_root, staging_root, workspace_root,
                         args.plan_name, original_plan_yaml, yaml_plan,
                         smoke_test_output_dir, args.conda_env,
                         args.dry_run, stream_logs=args.stream_logs,
                         child_columns=child_columns, child_lines=child_lines,
                         resume=args.resume,
                         retry_failed_validation=args.retry_failed_validation)
        msg = (f"[{idx}/{tot}] {inst} -> {r['status']}"
               + (f" ({r.get('error')})" if r.get("error") else ""))
        with _STDOUT_LOCK:
            print(msg, flush=True)
        return r

    summary_lock = threading.Lock()
    if args.max_parallel > 1 and not args.dry_run:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            future_to_inst = {executor.submit(_work, item): item[2] for item in to_process}
            for fut in as_completed(future_to_inst):
                inst = future_to_inst[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"instance_id": inst, "status": "error",
                         "error": f"{type(e).__name__}: {e}"}
                    print(f"[{inst}] unexpected exception: {e}", flush=True)
                with summary_lock:
                    summary.append(r)
    else:
        for item in to_process:
            r = _work(item)
            summary.append(r)

    summary_path = Path(args.summary) if args.summary else (staging_root / "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    totals: dict[str, int] = {}
    for r in summary:
        totals[r["status"]] = totals.get(r["status"], 0) + 1
    print(f"\nSUMMARY -> {summary_path}")
    for k, v in sorted(totals.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
