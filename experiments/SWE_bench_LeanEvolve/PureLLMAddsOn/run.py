#!/usr/bin/env python3
"""
run.py - Batch driver for LLM-only task-plan evolution.

For each SWE-bench instance that has BOTH an agent event log AND an evaluation
result, this driver:

  1. Stages the original YAML plan + event log + report.json + test_output.txt
     into `<staging_root>/inputs/<inst>/`.
  2. Runs `scripts/run_agent.sh` on `evolve.yaml`, passing per-instance paths
     via environment variables. All paths are container-view (`/workspace/...`)
     because the YAML's `shell_run` tool can only see files under
     `/workspace/`.
  3. After the YAML completes, copies the validated `evolved_plan.yaml` from
     `<staging_root>/outputs/<inst>/` to the durable location
     (`experiments/SWE_bench_verified/layer3_smoke_test/LLM_only_evolve/
     <plan_name>_<inst>_llm.yaml`) which downstream re-inference consumes.

PTY / SIGWINCH / stdout-locking infrastructure is reused from
`leanagent/codegen/agent_evolve/run_agent_evolve.py` by path-importing that module.

Resume + limit semantics (fix for prior bug):
  - `--resume` + `--limit N` processes N *incomplete* instances. The resume
    filter drops already-completed instances BEFORE `--limit` is applied.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
AGENT_EVOLVE_DIR = REPO_ROOT / "leanagent" / "codegen" / "agent_evolve"

# Reuse the PTY / SIGWINCH / stdout-locking infrastructure from the Lean arm.
# NOTE: leanagent/codegen/agent_evolve/ also has a `staging_paths.py`; we keep our own
# helpers in `paths.py` to avoid the name collision entirely.
sys.path.insert(0, str(AGENT_EVOLVE_DIR))
from run_agent_evolve import (  # type: ignore  # noqa: E402
    _STDOUT_LOCK,
    _ACTIVE_CHILDREN,
    _ACTIVE_CHILDREN_LOCK,
    _MIN_CHILD_COLUMNS,
    _spawn_with_pty,
    _read_pty_stream,
    _install_winch_handler_once,
    is_resolved as _is_resolved,
)
import run_agent_evolve as _shared  # for setting module-level globals  # noqa: E402

sys.path.insert(0, str(HERE))
from paths import (  # noqa: E402
    PACKAGE_SUBDIR,
    DURABLE_YAML_SUFFIX,
    durable_output_dir,
    instance_amendments_digest_path,
    instance_event_log_path,
    instance_inputs_dir,
    instance_original_yaml_path,
    instance_outputs_dir,
    instance_report_json_path,
    instance_runtime_dir,
    instance_staging_dir,
    instance_test_output_path,
    instance_validation_report_path,
    instance_evolved_yaml_path,
    instance_working_yaml_path,
    package_dir as _package_dir,
)

# Idle watchdog — fires when the AgentSPEX stops appending to its event log
# for more than `idle_seconds`. Complements the fixed per-instance timeout.
sys.path.insert(0, str(REPO_ROOT / "AgentSPEX" / "src"))
from harness.utils.idle_watchdog import IdleWatchdog  # noqa: E402


PACKAGE_FILES = [
    "trace_segmenter.py",
    "eval_forensics.py",
    "EditYaml.py",
    "EditJson.py",
    "plan_validator.py",
    "plan_salvager.py",
    "seed_digest.py",
]

# Host-side import of the salvager so run.py can build a salvaged YAML when
# the validator rejects an evolved plan.  Mirrors the file copied into
# <staging_root>/package/.
sys.path.insert(0, str(HERE / "package_files"))
from plan_salvager import salvage_plan as _salvage_plan  # noqa: E402


def _find_eval_paths(eval_root: Path, instance_id: str) -> tuple[Path, Path] | None:
    """Locate `<eval_root>/<inst>/report.json` + `test_output.txt`.

    Supports two conventions:
      (a) <eval_root>/<inst>/{report.json,test_output.txt}
      (b) <eval_root>/<model>/<inst>/{report.json,test_output.txt}
          (picks the single model subdirectory if (a) is not present)

    Returns (report_path, test_output_path) or None if either is missing.
    """
    direct_report = eval_root / instance_id / "report.json"
    direct_test = eval_root / instance_id / "test_output.txt"
    if direct_report.exists() and direct_test.exists():
        return direct_report, direct_test
    # Try one-level-deep model subdir.
    for sub in sorted(p for p in eval_root.iterdir() if p.is_dir()):
        candidate_report = sub / instance_id / "report.json"
        candidate_test = sub / instance_id / "test_output.txt"
        if candidate_report.exists() and candidate_test.exists():
            return candidate_report, candidate_test
    return None


def find_instances(outputs_root: Path, eval_root: Path) -> list[str]:
    """Return instance IDs with BOTH an event log and eval artefacts."""
    out: list[str] = []
    for p in sorted(outputs_root.glob("*_agent_events.log")):
        inst = p.name[: -len("_agent_events.log")]
        if not inst:
            continue
        if _find_eval_paths(eval_root, inst) is not None:
            out.append(inst)
    return out


def stage_shared(staging_root: Path, yaml_plan: Path) -> None:
    """One-time setup of directories and files shared across all instances.
    Safe to call repeatedly (idempotent). Call this BEFORE spawning parallel
    workers so per-instance stage_workspace() calls never race on shared paths."""
    pkg = _package_dir(staging_root)
    pkg.mkdir(parents=True, exist_ok=True)
    for fname in PACKAGE_FILES:
        src = HERE / "package_files" / fname
        if not src.exists():
            raise FileNotFoundError(f"package helper not found: {src}")
        shutil.copy2(src, pkg / fname)
    shutil.copy2(yaml_plan, staging_root / yaml_plan.name)


def stage_workspace(workspace_root: Path, staging_root: Path, instance_id: str,
                    outputs_root: Path, eval_root: Path,
                    original_plan_yaml: Path, yaml_plan: Path) -> dict:
    """Copy PER-INSTANCE inputs into the shared workspace. Returns a mapping
    of role → container-view path strings the YAML's env vars point at."""
    inputs = instance_inputs_dir(staging_root, instance_id)
    staging = instance_staging_dir(staging_root, instance_id)
    outputs = instance_outputs_dir(staging_root, instance_id)
    for p in (inputs, staging, outputs):
        p.mkdir(parents=True, exist_ok=True)

    src_event_log = outputs_root / f"{instance_id}_agent_events.log"
    if not src_event_log.exists():
        raise FileNotFoundError(f"event log not found: {src_event_log}")
    eval_paths = _find_eval_paths(eval_root, instance_id)
    if eval_paths is None:
        raise FileNotFoundError(
            f"eval artefacts (report.json + test_output.txt) not found for "
            f"{instance_id} under {eval_root}")
    src_report, src_test_output = eval_paths

    ws_original = instance_original_yaml_path(staging_root, instance_id)
    ws_event_log = instance_event_log_path(staging_root, instance_id)
    ws_report = instance_report_json_path(staging_root, instance_id)
    ws_test_output = instance_test_output_path(staging_root, instance_id)
    ws_working = instance_working_yaml_path(staging_root, instance_id)

    shutil.copy2(original_plan_yaml, ws_original)
    shutil.copy2(src_event_log, ws_event_log)
    shutil.copy2(src_report, ws_report)
    shutil.copy2(src_test_output, ws_test_output)

    def c_path(host_path: Path) -> str:
        rel = host_path.resolve().relative_to(workspace_root.resolve())
        return f"/workspace/{rel}"

    return {
        "workspace_root":         workspace_root,
        "ws_root_container":      c_path(staging_root),
        "package_dir_container":  c_path(_package_dir(staging_root)),
        "staging_dir_container":  c_path(staging),
        "staging_dir_host":       staging,
        "outputs_dir_container":  c_path(outputs),
        "outputs_dir_host":       outputs,
        "original_plan_container": c_path(ws_original),
        "working_plan_container":  c_path(ws_working),
        "working_plan_host":       ws_working,
        "event_log_container":     c_path(ws_event_log),
        "report_container":        c_path(ws_report),
        "test_output_container":   c_path(ws_test_output),
        "yaml_plan_container":     c_path(staging_root / yaml_plan.name),
    }


def _attempt_stage_b_recovery(staging_root: Path, instance_id: str,
                              original_plan_yaml: Path,
                              result: dict) -> dict | None:
    """Salvage an orphaned Stage B evolution for tool-weak models.

    Some models (e.g. Gemma-4) unreliably invoke `shell_run` on the final
    `cp` or `plan_validator.py` steps, so evolve.yaml exits with all the
    real work done in `staging/<inst>/working_plan.yaml` but never copies
    that file to `outputs/<inst>/evolved_plan.yaml` (status='yaml_failed')
    and/or never runs the validator (status='no_validation_report').

    This function checks whether staging's working_plan.yaml differs from
    the original and, if so:
        1. copies it to the expected evolved_plan.yaml path
        2. synthesizes an amendments_digest.json if none exists
           (marking every leaf that differs as 'amended')
        3. runs plan_validator.py to produce validation_report.json

    If the validator passes, the result dict is updated so the caller can
    treat the instance as ok. Returns the updated result dict on recovery,
    or None if nothing was recoverable.
    """
    working = instance_working_yaml_path(staging_root, instance_id)
    if not working.exists():
        return None
    try:
        orig_text = original_plan_yaml.read_text(encoding="utf-8")
        work_text = working.read_text(encoding="utf-8")
    except OSError:
        return None
    if orig_text == work_text:
        # nothing was actually evolved
        return None

    # Synthesize amendments_digest if missing (Gemma skipped earlier steps
    # too). Walk leaf instructions with a simple PyYAML load and mark every
    # leaf whose instruction differs as 'amended'.
    digest_path = instance_amendments_digest_path(staging_root, instance_id)
    if not digest_path.exists():
        try:
            import yaml as _yaml
            def _leaves(plan):
                out = []
                def walk(seq):
                    for it in seq or []:
                        if not isinstance(it, dict): continue
                        for k, v in it.items():
                            if k in ("task", "step") and isinstance(v, dict):
                                out.append((v.get("name", ""),
                                            v.get("instruction", "")))
                            elif k in ("for_each", "while"):
                                walk((v or {}).get("steps", []))
                            elif k == "if":
                                for br in ("steps_true", "steps_false", "steps"):
                                    walk((v or {}).get(br, []))
                            elif k == "switch":
                                for c in (v or {}).get("cases", []):
                                    walk((c or {}).get("steps", []))
                                walk(((v or {}).get("default") or {}).get("steps", []))
                            elif k == "parallel":
                                for br in (v or {}).get("branches", []):
                                    walk((br or {}).get("steps", []))
                walk(plan.get("workflow", []))
                return out
            o_map = dict(_leaves(_yaml.safe_load(orig_text)))
            e_map = dict(_leaves(_yaml.safe_load(work_text)))
            digest = []
            for i, (nm, _) in enumerate(_leaves(_yaml.safe_load(orig_text))):
                verdict = ("amended" if o_map.get(nm, "") != e_map.get(nm, "")
                           else "confirmed")
                digest.append({"step_index": i, "step_name": nm,
                               "verdict": verdict})
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            digest_path.write_text(json.dumps(digest, indent=2),
                                   encoding="utf-8")
        except Exception as e:
            result["recovery_note"] = (
                f"failed to synthesize digest: {type(e).__name__}: {e}")
            return None

    # Copy working_plan.yaml → evolved_plan.yaml only if the target doesn't
    # already exist (Docker-written files may be non-overwritable due to
    # UID mismatch).
    evolved_host = instance_evolved_yaml_path(staging_root, instance_id)
    evolved_host.parent.mkdir(parents=True, exist_ok=True)
    if not evolved_host.exists():
        shutil.copy2(working, evolved_host)

    # Run plan_validator.py if no validation_report yet
    report_path = instance_validation_report_path(staging_root, instance_id)
    validator_script = (REPO_ROOT / "leanagent" / "codegen" / "agent_evolve"
                        / "plan_validator.py")
    if not report_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validator_script),
                 "--original", str(original_plan_yaml),
                 "--evolved", str(evolved_host),
                 "--digest", str(digest_path),
                 "--report", str(report_path)],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0 and not report_path.exists():
                result["recovery_note"] = (
                    f"validator returned rc={proc.returncode}; "
                    f"stderr={proc.stderr[:200]}")
                return None
        except Exception as e:
            result["recovery_note"] = (
                f"validator spawn failed: {type(e).__name__}: {e}")
            return None
    result["recovery_applied"] = True
    return result


def _is_instance_complete(durable_path: Path, validation_report_path: Path) -> bool:
    """An instance is complete iff the durable evolved plan file exists.

    Two paths can write the durable plan: the happy path (Phase-5 validator
    confirmed all checks pass) and `_apply_fail_safe_salvage` (validation
    failed, but a salvaged plan was still written so Stage C has something
    to run). Both outcomes are terminal for Stage B — re-rolling a salvaged
    instance just re-salvages it, creating an infinite re-evolve loop on
    every `--resume`. So existence of the durable plan is the sole signal.

    `validation_report_path` is accepted for signature back-compat but is
    no longer consulted."""
    return durable_path.exists()


def _apply_fail_safe_salvage(*,
                             instance_id: str,
                             staging_root: Path,
                             original_plan_yaml: Path,
                             durable_output: Path,
                             result: dict) -> None:
    """Build a best-effort YAML at `durable_output` when validation fails (or
    didn't even run), so stage_c always has something to rerun.  Updates
    `result` in place: status becomes `salvaged_full` or `salvaged_partial`,
    the original failure reason is moved to `result["pre_salvage_status"]` /
    `result["pre_salvage_error"]`, and `result["salvage"]` carries the detail.
    The original `error` field is cleared so downstream summaries don't treat
    a salvaged instance as a hard failure."""
    evolved = instance_evolved_yaml_path(staging_root, instance_id)
    report = instance_validation_report_path(staging_root, instance_id)
    salvage_summary_path = (instance_outputs_dir(staging_root, instance_id)
                            / "salvage_summary.json")
    try:
        salv = _salvage_plan(
            original_plan_yaml,
            evolved if evolved.exists() else None,
            report if report.exists() else None,
            durable_output,
        )
    except Exception as e:
        # Last-resort: copy original verbatim so durable_output exists.
        try:
            shutil.copy2(original_plan_yaml, durable_output)
        except OSError:
            pass
        salv = {"mode": "full_fallback",
                "reverted_steps": [],
                "kept_evolved_steps": [],
                "reason": f"salvager raised {type(e).__name__}: {e}"}
    try:
        salvage_summary_path.parent.mkdir(parents=True, exist_ok=True)
        salvage_summary_path.write_text(
            json.dumps(salv, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    except OSError:
        pass

    result["pre_salvage_status"] = result.get("status")
    result["pre_salvage_error"] = result.get("error")
    result["salvage"] = salv
    result["status"] = ("salvaged_partial" if salv.get("mode") == "partial"
                        else "salvaged_full")
    result["error"] = None
    result["durable_output"] = str(durable_output)


def run_instance(instance_id: str,
                 outputs_root: Path,
                 eval_root: Path,
                 staging_root: Path,
                 workspace_root: Path,
                 plan_name: str,
                 original_plan_yaml: Path,
                 yaml_plan: Path,
                 output_dir: Path,
                 conda_env: str,
                 dry_run: bool,
                 stream_logs: bool,
                 child_columns: int,
                 child_lines: int,
                 resume: bool,
                 per_instance_timeout_sec: int = 0,
                 idle_timeout_sec: int = 0,
                 fail_safe_salvage: bool = True) -> dict:
    result: dict = {
        "instance_id": instance_id,
        "status": "unknown",
        "yaml_returncode": None,
        "error": None,
        "resume_actions": [],
    }

    durable_output = output_dir / f"{plan_name}_{instance_id}{DURABLE_YAML_SUFFIX}"
    validation_report = instance_validation_report_path(staging_root, instance_id)

    if resume and _is_instance_complete(durable_output, validation_report):
        result["status"] = "resumed_complete"
        result["resume_actions"].append(
            f"durable evolved plan + passing validation already present: {durable_output}")
        result["durable_output"] = str(durable_output)
        if dry_run:
            result["status"] = "dry_run_would_skip_complete"
        return result

    if dry_run:
        result["status"] = "dry_run"
        result["command"] = "(would stage + run evolve.yaml + copy to durable)"
        return result

    try:
        stage = stage_workspace(workspace_root, staging_root, instance_id,
                                outputs_root, eval_root,
                                original_plan_yaml, yaml_plan)
    except FileNotFoundError as e:
        result["status"] = "skipped_missing_input"
        result["error"] = str(e)
        return result

    env = os.environ.copy()
    env.update({
        "INSTANCE_ID":         instance_id,
        "PLAN_NAME":           plan_name,
        "ORIGINAL_PLAN_YAML":  stage["original_plan_container"],
        "WORKING_PLAN_YAML":   stage["working_plan_container"],
        "EVENT_LOG_PATH":      stage["event_log_container"],
        "REPORT_PATH":         stage["report_container"],
        "TEST_OUTPUT_PATH":    stage["test_output_container"],
        "STAGING_DIR":         stage["staging_dir_container"],
        "INSTANCE_OUTPUT_DIR": stage["outputs_dir_container"],
        "PACKAGE_DIR":         stage["package_dir_container"],
    })
    # Drop any inherited COLUMNS/LINES so Rich reads the live PTY size via
    # os.get_terminal_size(fd) and picks up SIGWINCH updates. Pinning COLUMNS
    # in env makes shutil.get_terminal_size() short-circuit to the stale value.
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    env.setdefault("FORCE_COLOR", "1")
    env.setdefault("CLICOLOR_FORCE", "1")
    # Disable per-step workspace manifest snapshots for this evolve subprocess.
    # With HOST_WORKSPACE set, the AgentSPEX scans the entire <workspace_root>
    # after every step and copies every file >1MB to <workspace_backup_path>,
    # which under concurrent runs (multiple evolves sharing the same workspace)
    # thrashes the filesystem and causes EIO on the next LLM call — especially
    # lethal for local vLLM endpoints (Gemma4 etc.) where the httpx socket
    # lives on the same box. We don't need snapshots here: our only artifact
    # is evolved_plan.yaml which already lives in staging/outputs/<inst>/.
    #
    # NOTE: HOST_WORKSPACE itself is re-exported by `source config/host.env`
    # inside scripts/run_agent.sh (with `set -a`), so simply clearing it here
    # is not enough. Instead we flip the DISABLE_WORKSPACE_MANIFEST switch
    # that agent.py reads from the process environment; host.env does not
    # mention that var, so the source call can't overwrite it.
    #
    # Caller-provided OPENAI_API_KEY / VLLM_API_BASE / MODEL_NAME (and the
    # other provider keys) ARE preserved by scripts/run_agent.sh via an
    # explicit snapshot-then-restore around the vm.env/host.env sources, so
    # setting them in os.environ here is sufficient — they will reach the
    # inner `python -m agent.run` intact.
    env["DISABLE_WORKSPACE_MANIFEST"] = "1"

    run_agent = REPO_ROOT / "AgentSPEX" / "scripts" / "run_agent.sh"
    if not run_agent.exists():
        result["status"] = "error"
        result["error"] = f"AgentSPEX/scripts/run_agent.sh not found at {run_agent}"
        return result

    runtime_dir = instance_runtime_dir(staging_root, instance_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    agent_resume_flag = "--resume " if resume else ""
    cmd_parts = [
        f"source {shlex.quote(str(REPO_ROOT / 'AgentSPEX'))}/config/host.env >/dev/null 2>&1 || true",
        'source "$(conda info --base)/etc/profile.d/conda.sh"',
        f"conda activate {shlex.quote(conda_env)}",
        f"export PYTHONPATH={shlex.quote(str(REPO_ROOT / 'AgentSPEX' / 'src'))}:${{PYTHONPATH:-}}",
        ("bash "
         f"{shlex.quote(str(run_agent))} "
         f"{shlex.quote(str(yaml_plan))} "
         f"--no_dashboard "
         f"{agent_resume_flag}"
         f"--output_dir {shlex.quote(str(runtime_dir))}"),
    ]
    cmd_str = " && ".join(cmd_parts)

    driver_log_path = runtime_dir / "driver.log"
    t0 = time.time()
    init_rows = child_lines if child_lines > 0 else 40
    init_cols = child_columns if child_columns > 0 else 120
    proc, master_fd = _spawn_with_pty(
        ["bash", "-c", cmd_str], cwd=str(REPO_ROOT / "AgentSPEX"), env=env,
        rows=init_rows, cols=init_cols,
    )
    with _ACTIVE_CHILDREN_LOCK:
        _ACTIVE_CHILDREN[proc.pid] = (master_fd, instance_id)

    # Watchdog thread: kill the child's process group if it exceeds the
    # per-instance timeout. A hung LLM or wedged AgentSPEX would otherwise
    # block `_read_pty_stream` indefinitely. Setting `watchdog_done` when
    # the stream drains (normal exit) prevents the watchdog from firing
    # post-hoc.
    watchdog_done = threading.Event()
    watchdog_fired = {"flag": False}

    def _watchdog() -> None:
        if per_instance_timeout_sec <= 0:
            return
        if watchdog_done.wait(timeout=per_instance_timeout_sec):
            return  # child finished in time
        if proc.poll() is None:
            watchdog_fired["flag"] = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            # Grace period before SIGKILL.
            time.sleep(3)
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    wd_thread: threading.Thread | None = None
    if per_instance_timeout_sec > 0:
        wd_thread = threading.Thread(target=_watchdog, daemon=True)
        wd_thread.start()

    # Idle watchdog. Fires when the AgentSPEX's event log stops growing for
    # `idle_seconds` — catches wedged agents that the fixed timeout would
    # otherwise let run until its full duration. The idle watchdog's
    # on_stall callback kills the process group; the subsequent `proc.wait`
    # returns and downstream code classifies the result as timeout-via-idle.
    idle_wd: IdleWatchdog | None = None
    idle_fired = {"flag": False}
    if idle_timeout_sec > 0:
        evt_log = runtime_dir / "agent_events.log"

        def _on_idle_stall() -> None:
            idle_fired["flag"] = True
            watchdog_fired["flag"] = True
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                time.sleep(3)
                if proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

        idle_wd = IdleWatchdog(event_log_path=evt_log,
                               idle_seconds=idle_timeout_sec,
                               poll_interval=30.0,
                               warmup_seconds=min(600.0, idle_timeout_sec / 4),
                               on_stall=_on_idle_stall)
        idle_wd.start()

    try:
        all_lines, tail = _read_pty_stream(master_fd, instance_id, stream_logs)
    finally:
        watchdog_done.set()
        if idle_wd is not None:
            idle_wd.stop()
        with _ACTIVE_CHILDREN_LOCK:
            _ACTIVE_CHILDREN.pop(proc.pid, None)
        try:
            os.close(master_fd)
        except OSError:
            pass
    proc.wait()
    if wd_thread is not None:
        wd_thread.join(timeout=1)

    driver_log_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    result["yaml_runtime_sec"] = round(time.time() - t0, 2)
    result["yaml_returncode"] = proc.returncode
    result["yaml_output_tail"] = "\n".join(tail)
    result["driver_log"] = str(driver_log_path)
    result["timeout_watchdog_sec"] = per_instance_timeout_sec
    result["idle_watchdog_sec"] = idle_timeout_sec
    result["idle_watchdog_fired"] = idle_fired["flag"]

    if watchdog_fired["flag"]:
        if idle_fired["flag"]:
            result["status"] = "idle_timeout"
            result["error"] = (f"idle-watchdog fired (no event-log growth for "
                               f"{idle_timeout_sec}s); AgentSPEX subprocess killed")
        else:
            result["status"] = "timeout"
            result["error"] = (f"per-instance watchdog fired after "
                               f"{per_instance_timeout_sec}s; AgentSPEX subprocess killed")
        return result

    evolved_host = instance_evolved_yaml_path(staging_root, instance_id)
    if not evolved_host.exists():
        # Tool-weak-model recovery: maybe the AgentSPEX finished the real
        # work but skipped the final `cp`. Check staging/working_plan.yaml.
        recovery = _attempt_stage_b_recovery(
            staging_root, instance_id, original_plan_yaml, result)
        if recovery is None or not evolved_host.exists():
            result["status"] = "yaml_failed"
            result["error"] = (f"YAML exit={proc.returncode}; evolved_plan.yaml "
                               f"not produced at {evolved_host}")
            if "recovery_note" in result:
                result["error"] += f" | recovery_note={result['recovery_note']}"
            if fail_safe_salvage:
                _apply_fail_safe_salvage(
                    instance_id=instance_id, staging_root=staging_root,
                    original_plan_yaml=original_plan_yaml,
                    durable_output=durable_output, result=result)
            return result

    if not validation_report.exists():
        # Recovery path in case the AgentSPEX skipped the validate step.
        recovery = _attempt_stage_b_recovery(
            staging_root, instance_id, original_plan_yaml, result)
        if recovery is None or not validation_report.exists():
            result["status"] = "no_validation_report"
            result["error"] = (f"validation_report.json not found at "
                               f"{validation_report}")
            if fail_safe_salvage:
                _apply_fail_safe_salvage(
                    instance_id=instance_id, staging_root=staging_root,
                    original_plan_yaml=original_plan_yaml,
                    durable_output=durable_output, result=result)
            return result
    try:
        rep = json.loads(validation_report.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "validation_report_unreadable"
        result["error"] = f"{type(e).__name__}: {e}"
        if fail_safe_salvage:
            _apply_fail_safe_salvage(
                instance_id=instance_id, staging_root=staging_root,
                original_plan_yaml=original_plan_yaml,
                durable_output=durable_output, result=result)
        return result
    summary = rep.get("summary") or {}
    result["validation_summary"] = summary
    if not summary.get("pass"):
        result["status"] = "validation_failed"
        result["error"] = (f"validation did not pass: "
                           f"failing_checks={summary.get('failing_checks')}")
        if fail_safe_salvage:
            _apply_fail_safe_salvage(
                instance_id=instance_id, staging_root=staging_root,
                original_plan_yaml=original_plan_yaml,
                durable_output=durable_output, result=result)
        return result

    durable_output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(evolved_host, durable_output)
    result["durable_output"] = str(durable_output)
    result["status"] = "ok"
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description="Batch runner for LLM-only task-plan evolution.")
    p.add_argument("--outputs_root", required=True,
                   help=("Directory containing `<inst>_agent_events.log` files "
                         "from the prior agent run that is being evolved."))
    p.add_argument("--eval_root", required=True,
                   help=("Directory containing per-instance SWE-bench eval "
                         "artefacts (report.json + test_output.txt). Either "
                         "`<eval_root>/<inst>/` or `<eval_root>/<model>/<inst>/` "
                         "layout is accepted."))
    p.add_argument("--original_plan_yaml", required=True,
                   help="Path to the original SWE-bench YAML plan to evolve.")
    p.add_argument("--plan_name", default="passed_workflow_1",
                   help="Plan name embedded in durable output filenames.")
    p.add_argument("--yaml_plan", default=str(HERE / "evolve.yaml"),
                   help="Path to evolve.yaml.")
    p.add_argument("--output_dir", default=str(durable_output_dir(REPO_ROOT)),
                   help=("Directory that receives the durable evolved plans "
                         "(<plan_name>_<inst>_llm.yaml)."))
    p.add_argument("--workspace_root",
                   default="workspace",
                   help="Host path the sandbox Docker mounts as /workspace.")
    p.add_argument("--staging_root", default="",
                   help=("Staging root. Must be inside --workspace_root. Default: "
                         "<workspace_root>/llm_evolve_run/staging."))
    p.add_argument("--conda_env", default="agent_env")
    p.add_argument("--single_instance", default="")
    p.add_argument("--instance_ids", default="",
                   help="Comma-separated whitelist of instance IDs to process. "
                        "Overrides full-dir enumeration. E.g. "
                        "django__django-14140,matplotlib__matplotlib-25775.")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap on the number of INCOMPLETE instances to process "
                        "(0 = unlimited). Applied after --resume filtering.")
    p.add_argument("--max_parallel", type=int, default=1)
    p.add_argument("--stream_logs", action="store_true", default=True)
    p.add_argument("--no_stream_logs", dest="stream_logs", action="store_false")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry_run", action="store_true")
    p.add_argument("--skip_resolved", action="store_true",
                   help="Skip instances whose report.json shows resolved == true.")
    p.add_argument("--per_instance_timeout_sec", type=int, default=10800,
                   help="Per-instance watchdog in seconds (default: 10800 = 3 h). "
                        "Kills the AgentSPEX subprocess if it exceeds this time and "
                        "records status='timeout' for the instance. Pass 0 to disable.")
    p.add_argument("--idle_timeout_sec", type=int, default=7200,
                   help="Idle-watchdog: kill the AgentSPEX subprocess if its event log "
                        "has not grown in this many seconds (default: 7200 = 2 h). "
                        "Complements --per_instance_timeout_sec. Pass 0 to disable.")
    p.add_argument("--summary", default="",
                   help="Where to write the JSON summary. Default: <staging_root>/_summary.json")
    p.add_argument("--fail_safe_salvage", dest="fail_safe_salvage",
                   action="store_true", default=True,
                   help=("When the validator rejects an evolved plan (or the "
                         "evolved YAML / validation report is missing), build "
                         "a best-effort salvaged YAML at the durable output "
                         "path so stage_c always has something to rerun. Per-"
                         "step salvage is attempted when only per-step content "
                         "checks fail; otherwise falls back to the original "
                         "plan verbatim. Status becomes salvaged_partial / "
                         "salvaged_full instead of validation_failed. Default "
                         "ON."))
    p.add_argument("--no_fail_safe_salvage", dest="fail_safe_salvage",
                   action="store_false",
                   help="Restore strict behavior: drop instances on validation "
                        "failure instead of salvaging.")
    args = p.parse_args()

    outputs_root = Path(args.outputs_root).resolve()
    eval_root = Path(args.eval_root).resolve()
    original_plan_yaml = Path(args.original_plan_yaml).resolve()
    yaml_plan = Path(args.yaml_plan).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    output_dir = Path(args.output_dir).resolve()

    for p_arg, p_val in [
        ("--outputs_root", outputs_root),
        ("--eval_root", eval_root),
        ("--original_plan_yaml", original_plan_yaml),
        ("--yaml_plan", yaml_plan),
        ("--workspace_root", workspace_root),
    ]:
        if not p_val.exists():
            print(f"ERROR: {p_arg} not found: {p_val}", file=sys.stderr)
            return 1

    if args.staging_root:
        staging_root = Path(args.staging_root).resolve()
    else:
        staging_root = workspace_root / "llm_evolve_run" / "staging"
    try:
        staging_root.relative_to(workspace_root)
    except ValueError:
        print(f"ERROR: --staging_root ({staging_root}) must be inside --workspace_root "
              f"({workspace_root}) so the sandbox Docker can see it under /workspace/.",
              file=sys.stderr)
        return 1
    staging_root.mkdir(parents=True, exist_ok=True)

    # Enumerate candidate instances.
    if args.single_instance:
        instances = [args.single_instance]
    elif args.instance_ids:
        requested = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        available = set(find_instances(outputs_root, eval_root))
        missing = [i for i in requested if i not in available]
        if missing:
            print(f"WARNING: {len(missing)} requested instance(s) not found in "
                  f"--outputs_root / --eval_root: {missing}", flush=True)
        instances = [i for i in requested if i in available]
    else:
        instances = find_instances(outputs_root, eval_root)
    if not instances:
        print(f"ERROR: no instances found with both event log under {outputs_root} "
              f"and eval artefacts under {eval_root}", file=sys.stderr)
        return 1

    total = len(instances)
    original_instances = list(instances)

    # --- filter pass 1: --skip_resolved ---
    if args.skip_resolved:
        kept: list[str] = []
        skipped_resolved: list[str] = []
        for inst in instances:
            eval_paths = _find_eval_paths(eval_root, inst)
            if eval_paths is None:
                kept.append(inst)  # no decision possible, keep
                continue
            report, _ = eval_paths
            res = _is_resolved(report, inst)
            if res is True:
                skipped_resolved.append(inst)
            else:
                kept.append(inst)
        if skipped_resolved:
            print(f"[skip_resolved] skipping {len(skipped_resolved)} already-resolved "
                  f"instance(s): {', '.join(skipped_resolved[:5])}"
                  f"{' …' if len(skipped_resolved) > 5 else ''}", flush=True)
        instances = kept

    # --- filter pass 2: --resume drops already-complete instances ---
    #
    # Runs BEFORE --limit. The already-complete count is SUBTRACTED from the
    # --limit budget so that `--limit N --resume` means "ensure the final
    # durable population holds N evolved plans", not "queue N more on top of
    # whatever is already done". Prior semantic kept growing the population
    # on every re-run; the current one converges to N and is a no-op once N
    # is reached.
    already_complete_count = 0
    if args.resume:
        kept2: list[str] = []
        skipped_complete: list[str] = []
        for inst in instances:
            durable = output_dir / f"{args.plan_name}_{inst}{DURABLE_YAML_SUFFIX}"
            vrep = instance_validation_report_path(staging_root, inst)
            if _is_instance_complete(durable, vrep):
                skipped_complete.append(inst)
            else:
                kept2.append(inst)
        already_complete_count = len(skipped_complete)
        if skipped_complete:
            print(f"[resume] skipping {already_complete_count} already-complete "
                  f"instance(s): {', '.join(skipped_complete[:5])}"
                  f"{' …' if already_complete_count > 5 else ''}", flush=True)
        instances = kept2

    # --- filter pass 3: --limit caps the TOTAL target, counting completes ---
    #
    # effective_budget = max(0, --limit - already_complete). If the budget is
    # 0, stage B queues nothing and returns immediately; downstream stages
    # still consume the full population of `already_complete_count` durable
    # plans that `--task-plans-dir` points at.
    if args.limit:
        effective_budget = max(0, args.limit - already_complete_count)
    else:
        effective_budget = None  # unlimited

    selected = 0
    to_process: list[tuple[int, int, str]] = []
    for idx, inst in enumerate(instances, 1):
        if effective_budget is not None and selected >= effective_budget:
            print(f"[limit] --limit={args.limit} already satisfied by "
                  f"{already_complete_count} complete + {selected} queued = "
                  f"{already_complete_count + selected} total; "
                  f"stopping (of {len(instances)} incomplete available, "
                  f"from {total} total).", flush=True)
            break
        to_process.append((idx, len(instances), inst))
        selected += 1

    if not to_process:
        print("No instances to process.", flush=True)
        # Still write an (empty) summary for idempotency.
        summary_path = Path(args.summary) if args.summary else (staging_root / "_summary.json")
        summary_path.write_text(json.dumps([], indent=2) + "\n", encoding="utf-8")
        return 0

    print(f"\n{len(to_process)} instance(s) queued of {total} found "
          f"(max_parallel={args.max_parallel}, dry_run={args.dry_run}, "
          f"resume={args.resume}, skip_resolved={args.skip_resolved})", flush=True)

    if not args.dry_run:
        stage_shared(staging_root, yaml_plan)

    # Child PTY dimensions. Drive the dashboard's colored-box width from the
    # live parent terminal minus the per-line prefix pad so the box resizes
    # correctly on SIGWINCH (prior bug was a mismatched width).
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

    # Push PREFIX_PAD and STREAM_LOGS_ENABLED into the shared module so the
    # SIGWINCH handler computes the same child_columns on resize.
    _shared._PREFIX_PAD = prefix_pad
    _shared._STREAM_LOGS_ENABLED = bool(args.stream_logs)
    if not args.dry_run:
        _install_winch_handler_once()

    summary: list[dict] = []
    summary_lock = threading.Lock()

    def _work(item: tuple[int, int, str]) -> dict:
        idx, tot, inst = item
        with _STDOUT_LOCK:
            print(f"[{idx}/{tot}] {inst} -> starting", flush=True)
        r = run_instance(inst, outputs_root, eval_root, staging_root,
                         workspace_root, args.plan_name, original_plan_yaml,
                         yaml_plan, output_dir, args.conda_env,
                         args.dry_run, stream_logs=args.stream_logs,
                         child_columns=child_columns, child_lines=child_lines,
                         resume=args.resume,
                         per_instance_timeout_sec=args.per_instance_timeout_sec,
                         idle_timeout_sec=args.idle_timeout_sec,
                         fail_safe_salvage=args.fail_safe_salvage)
        msg = (f"[{idx}/{tot}] {inst} -> {r['status']}"
               + (f" ({r.get('error')})" if r.get("error") else ""))
        with _STDOUT_LOCK:
            print(msg, flush=True)
        return r

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
