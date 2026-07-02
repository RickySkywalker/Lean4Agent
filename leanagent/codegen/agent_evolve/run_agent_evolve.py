#!/usr/bin/env python3
"""
run_agent_evolve.py - Outer batch driver for the Layer 3 auto-annotation pipeline.

For each SWE-bench instance, this driver:

  1. Stages package scripts and input files into the shared workspace that the
     sandbox Docker mounts as /workspace. Inside the Docker, the YAML's
     `shell_run` tool can only see files under /workspace, so everything the
     YAML reads must live there.
  2. Runs `scripts/run_agent.sh` on `annotate_layer3.yaml`, passing per-instance
     paths via environment variables. Two path flavours are distinguished:
       * `*_PATH`           — container view (/workspace/...) — read by shell_run
       * `HOST_*`           — host view (/home/... or /shared/...) — embedded
                              into the Lean IR's report_path / event_log_path
                              fields so that when `lake env lean` runs on the
                              host, the paths resolve.
  3. After the YAML completes, copies the produced layer3_ir.json from the
     workspace back into the host-side results_dir, and runs `ir_to_lean.py`
     (pure Python, no Lean binary) to emit the .lean file.

CLI:
  python run_agent_evolve.py \\
      --outputs_root /.../outputs/.../passed_workflow_1 \\
      --eval_root /.../benchmark_results/.../gpt-5.2 \\
      --layer2_ir /.../passed_workflow_1_django_11333_per_step.ir.json \\
      --plan_name passed_workflow_1 \\
      --results_dir /.../leanagent/codegen/agent_evolve/outputs \\
      [--workspace_root workspace] \\
      [--single_instance django__django-14140] [--skip_resolved] [--dry_run]
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())

PACKAGE_FILES = [
    "trace_segmenter.py",
    "eval_forensics.py",
    "layer3_ir_init.py",
    "EditJson.py",
    "summarize_ir.py",
    "tighten_layer3_verdicts.py",
]


def find_instances(outputs_root: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(outputs_root.glob("*_agent_events.log")):
        name = p.name
        if name.endswith("_agent_events.log"):
            out.append(name[: -len("_agent_events.log")])
    return out


def is_resolved(report_path: Path, instance_id: str) -> bool | None:
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


def stage_shared(staging_root: Path, yaml_plan: Path) -> None:
    """One-time setup of directories and files shared across all instances.
    Safe to call repeatedly (idempotent). Call this BEFORE spawning parallel
    workers so per-instance stage_workspace() calls never race on shared paths."""
    pkg = staging_root / "package"
    pkg.mkdir(parents=True, exist_ok=True)
    for fname in PACKAGE_FILES:
        shutil.copy2(HERE / fname, pkg / fname)
    shutil.copy2(yaml_plan, staging_root / yaml_plan.name)


def stage_workspace(workspace_root: Path, staging_root: Path, instance_id: str,
                    event_log: Path, full_log: Path | None,
                    report: Path, test_output: Path, layer2_ir: Path,
                    yaml_plan: Path) -> dict:
    """Copy PER-INSTANCE inputs into the shared workspace. Returns a mapping
    of role → (container_path, host_path) tuples. The YAML consumes container
    paths; the Lean IR consumes host paths.

    staging_root is the per-run base directory (must be inside workspace_root
    so Docker can see it). All per-instance subdirs live under staging_root.
    stage_shared() must have been called first to pre-populate the package/
    subdir; this function only writes into per-instance subdirs.
    """
    ws_root = staging_root
    pkg = ws_root / "package"
    inputs = ws_root / "inputs" / instance_id
    staging = ws_root / "staging" / instance_id
    outputs = ws_root / "outputs" / instance_id
    for p in (inputs, staging, outputs):
        p.mkdir(parents=True, exist_ok=True)

    ws_event_log = inputs / "agent_events.log"
    ws_full_log = inputs / "full.log" if full_log and full_log.exists() else None
    ws_report = inputs / "report.json"
    ws_test_output = inputs / "test_output.txt"
    ws_layer2_ir = inputs / "layer2_ir.json"
    shutil.copy2(event_log, ws_event_log)
    if ws_full_log:
        shutil.copy2(full_log, ws_full_log)  # type: ignore[arg-type]
    shutil.copy2(report, ws_report)
    shutil.copy2(test_output, ws_test_output)
    shutil.copy2(layer2_ir, ws_layer2_ir)

    def c_path(host_path: Path) -> str:
        rel = host_path.resolve().relative_to(workspace_root.resolve())
        return f"/workspace/{rel}"

    return {
        "workspace_root": workspace_root,
        "ws_root_host": ws_root,
        "ws_root_container": c_path(ws_root),
        "package_dir_container": c_path(pkg),
        "staging_dir_container": c_path(staging),
        "staging_dir_host": staging,
        "outputs_dir_host": outputs,
        "output_ir_host": outputs / "layer3_ir.json",
        "output_ir_container": c_path(outputs / "layer3_ir.json"),
        "yaml_plan_container": c_path(ws_root / yaml_plan.name),
        "event_log_container": c_path(ws_event_log),
        "full_log_container": c_path(ws_full_log) if ws_full_log else "",
        "report_container": c_path(ws_report),
        "test_output_container": c_path(ws_test_output),
        "layer2_ir_container": c_path(ws_layer2_ir),
        "event_log_host": event_log,
        "report_host": report,
    }


# Global lock to serialize interleaved writes to stdout from multiple workers.
# Without this, partial lines from parallel subprocesses can be interleaved
# mid-line, making the output unreadable.
_STDOUT_LOCK = threading.Lock()

# Registry of active children we spawned with a pty, used by the SIGWINCH handler
# to propagate resize events. Each entry is { "pid": (master_fd, instance_id) }.
_ACTIVE_CHILDREN_LOCK = threading.Lock()
_ACTIVE_CHILDREN: dict[int, tuple[int, str]] = {}

# Set from main(): fixed overhead per streamed line ("[<longest_id>] ").
# The SIGWINCH handler uses this to compute each child's new usable width.
_PREFIX_PAD = 30
_STREAM_LOGS_ENABLED = True
_MIN_CHILD_COLUMNS = 60


def _set_pty_size(fd: int, rows: int, cols: int) -> None:
    """ioctl(TIOCSWINSZ) on a pty fd. Safe to call after close."""
    try:
        size = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except Exception:
        pass  # child may have exited / fd may be stale


def _winch_handler(signum, frame):
    """SIGWINCH fires when the parent's terminal is resized. Re-read the parent's
    size and push it to every active child's pty (plus SIGWINCH to the child's
    pgrp) so Rich / tqdm / etc. re-check their terminal size and redraw at the
    new width."""
    try:
        term = shutil.get_terminal_size(fallback=(120, 40))
    except Exception:
        return
    child_cols = max(_MIN_CHILD_COLUMNS,
                     (term.columns - _PREFIX_PAD) if _STREAM_LOGS_ENABLED else term.columns)
    with _ACTIVE_CHILDREN_LOCK:
        active = list(_ACTIVE_CHILDREN.items())
    for pid, (master_fd, _inst) in active:
        _set_pty_size(master_fd, term.lines, child_cols)
        try:
            # Forward SIGWINCH to the child's process group (we used
            # start_new_session=True so the child is its own pgrp leader).
            os.killpg(pid, signal.SIGWINCH)
        except (ProcessLookupError, PermissionError):
            pass


def _install_winch_handler_once() -> None:
    try:
        signal.signal(signal.SIGWINCH, _winch_handler)
    except (ValueError, AttributeError, OSError):
        # not Unix, or called from a non-main thread
        pass


def _spawn_with_pty(cmd_argv: list[str], cwd: str, env: dict[str, str],
                    rows: int, cols: int) -> tuple[subprocess.Popen, int]:
    """Spawn a child whose stdout/stderr is attached to a pty we control.
    Sets the initial window size. Caller is responsible for closing master_fd
    and removing the child from _ACTIVE_CHILDREN when done."""
    master_fd, slave_fd = pty.openpty()
    _set_pty_size(slave_fd, rows, cols)
    # Make master non-blocking so we can read partial chunks without deadlock.
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    proc = subprocess.Popen(
        cmd_argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        start_new_session=True,  # its own pgrp, safe for killpg + SIGWINCH
    )
    os.close(slave_fd)  # parent only needs master
    return proc, master_fd


def _read_pty_stream(master_fd: int, instance_id: str,
                     stream_to_stdout: bool, tail_lines: int = 80
                     ) -> tuple[list[str], list[str]]:
    """Drain the pty master until the child closes it (EIO). Split into lines;
    echo each (prefixed) to stdout if requested; return (all_lines, tail)."""
    all_lines: list[str] = []
    buffer = b""

    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except BlockingIOError:
            # No data yet; wait briefly for either more data or child exit.
            time.sleep(0.05)
            continue
        except OSError as e:
            if e.errno in (errno.EIO, errno.EBADF):
                break
            raise
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line_bytes, buffer = buffer.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
            all_lines.append(line)
            if stream_to_stdout:
                with _STDOUT_LOCK:
                    sys.stdout.write(f"[{instance_id}] {line}\n")
                    sys.stdout.flush()

    if buffer:
        tail_line = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
        if tail_line:
            all_lines.append(tail_line)
            if stream_to_stdout:
                with _STDOUT_LOCK:
                    sys.stdout.write(f"[{instance_id}] {tail_line}\n")
                    sys.stdout.flush()

    return all_lines, all_lines[-tail_lines:]


# Directory-layout constants are shared with step 3's driver (`run_plan_evolve.py`)
# via staging_paths.py so the two pipelines cannot drift.
from staging_paths import (  # noqa: E402
    LEAN_GENERATED_SUBDIR as _LEAN_GENERATED_SUBDIR,
    LEAN_REPL_SUBDIR as _LEAN_REPL_SUBDIR,
    lean_repl_staging_path as _lean_repl_staging_path,
)

_GITIGNORE_TEMPLATE = "# Auto-generated by leanagent/codegen/agent_evolve/run_agent_evolve.py\n*\n!.gitignore\n"


def _ir_missing_seeds(ir_path: Path, trace_index_path: Path) -> list[str]:
    """Return the list of variable names that SHOULD be in the IR's exec_state
    (workflow parameters + observed tools from the trace) but are missing.
    Empty list means the IR is fully seeded."""
    if not ir_path.exists() or not trace_index_path.exists():
        return []
    try:
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        trace_index = json.loads(trace_index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    present = {row[0] for row in (ir.get("exec_state") or []) if isinstance(row, (list, tuple)) and row}
    need: list[str] = []
    for p in ir.get("workflow", {}).get("parameters", []) or []:
        nm = p.get("name", "")
        if nm and nm not in present:
            need.append(nm)
    for t in trace_index.get("observed_tools", []) or []:
        if t and t not in present:
            need.append(t)
    return need


def _augment_ir_exec_state(ir_path: Path, trace_index_path: Path) -> list[str]:
    """Merge missing parameter/tool seeds into the IR's exec_state in-place.
    Existing entries (including LLM-populated evidence variables) are
    preserved. Returns the list of variable names that were added."""
    from layer3_ir_init import compute_seed_exec_state  # local import to avoid
                                                        # hard dependency at load time
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    trace_index = json.loads(trace_index_path.read_text(encoding="utf-8"))
    seeds = compute_seed_exec_state(
        ir.get("workflow", {}),
        trace_index.get("workflow_parameters", {}) or {},
        trace_index.get("observed_tools", []) or [],
    )
    present = {row[0] for row in (ir.get("exec_state") or []) if isinstance(row, (list, tuple)) and row}
    added: list[str] = []
    # Insert seeds at the FRONT so the IR reads parameters → tools → evidence,
    # matching the hand-authored reference layout.
    new_rows = []
    for row in seeds:
        name = row[0]
        if name not in present:
            new_rows.append(row)
            added.append(name)
            present.add(name)
    if not new_rows:
        return added
    ir["exec_state"] = new_rows + (ir.get("exec_state") or [])
    ir_path.write_text(json.dumps(ir, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


def _query_is_complete(path: Path) -> bool:
    """Return True iff the layer3_query.json at `path` represents a fully-completed
    lean_query run (no errors, at least one per_node_result)."""
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if d.get("errors"):
        return False
    return len(d.get("per_node_results", [])) > 0


def _detect_resume_artifacts(results_dir: Path, staging_root: Path, plan_name: str,
                             instance_ids: list[str]) -> dict[str, dict[str, bool]]:
    """Return per-instance dict of which stages already have artifacts on disk.
    Checks both the durable results_dir copy AND the staging mirror so a run
    whose results_dir was cleared can still be resumed from staging."""
    out: dict[str, dict[str, bool]] = {}
    for inst in instance_ids:
        base = results_dir / f"{plan_name}_{inst}"
        ir = (base / "layer3_ir.json").exists()
        lean = (base / "per_step.lean").exists()
        query_results = _query_is_complete(base / "layer3_query.json")
        query_staging = _query_is_complete(
            _lean_repl_staging_path(staging_root, plan_name, inst))
        query = query_results or query_staging
        out[inst] = {"ir": ir, "lean": lean, "query": query,
                     "query_staging_only": query_staging and not query_results,
                     "any": ir or lean or query}
    return out


def _sanitize_for_lean_module(s: str) -> str:
    """Convert 'django__django-14140' -> 'django_django_14140' so it's a valid
    Lean module-name component."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return re.sub(r"_+", "_", out).strip("_")


def _run_pty_streamed(cmd_argv: list[str], cwd: str, env: dict[str, str],
                      instance_id: str, stream_to_stdout: bool,
                      rows: int, cols: int, timeout: int
                      ) -> tuple[int, list[str]]:
    """Spawn `cmd_argv` with a pty so its size/colors match the parent's, stream
    its output (prefixed with [instance_id]) to stdout if requested, and return
    (returncode, all_lines). Respects the SIGWINCH forwarding registry."""
    proc, master_fd = _spawn_with_pty(cmd_argv, cwd=cwd, env=env, rows=rows, cols=cols)
    with _ACTIVE_CHILDREN_LOCK:
        _ACTIVE_CHILDREN[proc.pid] = (master_fd, instance_id)
    try:
        all_lines, _ = _read_pty_stream(master_fd, instance_id, stream_to_stdout)
    finally:
        with _ACTIVE_CHILDREN_LOCK:
            _ACTIVE_CHILDREN.pop(proc.pid, None)
        try:
            os.close(master_fd)
        except OSError:
            pass
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return -1, all_lines + ["[timeout]"]
    return proc.returncode, all_lines


def _run_lean_pipeline(instance_id: str, plan_name: str,
                       final_ir_path: Path, final_lean_path: Path,
                       staging_root: Path, verifier_dir: Path,
                       results_instance_dir: Path,
                       stream_logs: bool, child_columns: int, child_lines: int,
                       lean_timeout: int) -> dict:
    """Emit the generated .lean to <staging_root>/lean_files/, also copy it
    into the Verifier tree under VerificationExamples/<_LEAN_GENERATED_SUBDIR>/
    (so `lake build` finds it), then build the olean and run lean_query."""
    out: dict = {
        "lean_file_staging": None,
        "lean_file_verifier": None,
        "lean_module": None,
        "lean_build_returncode": None,
        "lean_build_log": None,
        "lean_query_returncode": None,
        "lean_query_json": None,           # durable copy under results_dir
        "lean_query_json_staging": None,   # mirror copy under <staging_root>/lean_repl/
        "lean_query_log": None,
        "lean_error": None,
    }

    try:
        ir_raw = json.loads(final_ir_path.read_text(encoding="utf-8"))
        prefix = ir_raw.get("prefix") or ""
        suffix = ir_raw.get("suffix") or ""
        if not prefix:
            raise ValueError("IR missing 'prefix'")
    except Exception as e:
        out["lean_error"] = f"failed to read IR for lean config: {e}"
        return out

    # Primary location (user-visible, inside the staging workspace).
    lean_files_dir = staging_root / "lean_files"
    lean_files_dir.mkdir(parents=True, exist_ok=True)
    base_name = _sanitize_for_lean_module(f"{plan_name}_{instance_id}_per_step")
    staging_lean = lean_files_dir / f"{base_name}.lean"
    shutil.copy2(final_lean_path, staging_lean)
    out["lean_file_staging"] = str(staging_lean)

    # Verifier-tree copy (must be inside a lean_lib glob for lake to build it).
    verifier_subdir = verifier_dir / "VerificationExamples" / _LEAN_GENERATED_SUBDIR
    verifier_subdir.mkdir(parents=True, exist_ok=True)
    gitignore_path = verifier_subdir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_GITIGNORE_TEMPLATE, encoding="utf-8")
    verifier_lean = verifier_subdir / f"{base_name}.lean"
    shutil.copy2(final_lean_path, verifier_lean)
    out["lean_file_verifier"] = str(verifier_lean)
    module_name = f"VerificationExamples.{_LEAN_GENERATED_SUBDIR}.{base_name}"
    out["lean_module"] = module_name

    # Build env: force colour + drop any inherited COLUMNS/LINES so Rich/tqdm in
    # the child use os.get_terminal_size(PTY_fd), which is updated on resize by
    # our SIGWINCH handler (_set_pty_size). Pinning COLUMNS would let
    # shutil.get_terminal_size() short-circuit before reading the live PTY size.
    build_env = os.environ.copy()
    build_env.pop("COLUMNS", None)
    build_env.pop("LINES", None)
    build_env.setdefault("FORCE_COLOR", "1")
    build_env.setdefault("CLICOLOR_FORCE", "1")
    # lean_query lives under leanagent/; expose it so `python -m lean_query.cli`
    # resolves even though we run with cwd=FormalAgentLib (the Lean project).
    build_env["PYTHONPATH"] = f"{REPO_ROOT / 'leanagent'}{os.pathsep}{build_env.get('PYTHONPATH', '')}"

    # --- lake build ---
    with _STDOUT_LOCK:
        print(f"[{instance_id}] lake build {module_name} ...", flush=True)
    rc, lines = _run_pty_streamed(
        ["lake", "build", module_name],
        cwd=str(verifier_dir), env=build_env,
        instance_id=instance_id, stream_to_stdout=stream_logs,
        rows=child_lines or 40, cols=child_columns or 120,
        timeout=lean_timeout,
    )
    build_log_path = results_instance_dir / "lake_build.log"
    build_log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out["lean_build_log"] = str(build_log_path)
    out["lean_build_returncode"] = rc
    if rc != 0:
        out["lean_error"] = f"lake build failed (exit {rc})"
        return out

    # --- lean_query (structured JSON from the olean we just built) ---
    config_yaml = results_instance_dir / "lean_query_config.yaml"
    config_yaml.write_text(
        "\n".join([
            f"lean_project_path: {verifier_dir}",
            f"target_file: VerificationExamples/{_LEAN_GENERATED_SUBDIR}/{base_name}.lean",
            f"layer: 3",
            f"workflow_graph: {prefix}Graph",
            f"semantic_graph: {prefix}SemanticGraph",
            f"goal_spec: {prefix}_goalSpec",
            f"dynamic_graph: dynamicGraph{suffix}",
            f"step_id_map: stepIdMap{suffix}",
            f"llm_injections: llmInjections{suffix}",
            f"exec_state: execState{suffix}",
            f"report_path_var: reportPath{suffix}",
            f"event_log_path_var: eventLogPath{suffix}",
            f"timeout_seconds: {lean_timeout}",
            "pretty_print: true",
        ]) + "\n",
        encoding="utf-8",
    )

    query_json = results_instance_dir / "layer3_query.json"
    query_log = results_instance_dir / "lean_query.log"

    # Mirror location: <staging_root>/lean_repl/<plan>_<instance>.json. Kept in
    # lockstep with `query_json` so either side can serve as the canonical source
    # for resume detection (see _lean_repl_staging_path).
    lean_repl_dir = staging_root / "lean_repl"
    lean_repl_dir.mkdir(parents=True, exist_ok=True)
    lean_repl_json = _lean_repl_staging_path(staging_root, plan_name, instance_id)
    out["lean_query_json_staging"] = str(lean_repl_json)

    with _STDOUT_LOCK:
        print(f"[{instance_id}] lean_query on {module_name} ...", flush=True)
    try:
        qp = subprocess.run(
            [sys.executable, "-m", "lean_query.cli",
             "--config", str(config_yaml),
             "--timeout", str(lean_timeout),
             # Runner.py honours --output (writes via Path.write_text) — in
             # addition we capture stdout so the CLI banner is written to the
             # per-instance log for debugging.
             "--output", str(query_json)],
            cwd=str(verifier_dir),
            capture_output=True, text=True,
            timeout=lean_timeout + 30,
            env=build_env,
        )
    except subprocess.TimeoutExpired:
        out["lean_query_returncode"] = -1
        out["lean_error"] = f"lean_query timed out after {lean_timeout}s"
        return out

    # If the runner failed before writing --output (e.g. Lean compilation error),
    # fall back to the captured stdout so we still get a JSON-shaped record on
    # disk. This is the pre-fix behaviour.
    if not query_json.exists() and qp.stdout:
        query_json.write_text(qp.stdout, encoding="utf-8")
    query_log.write_text(qp.stderr or "", encoding="utf-8")

    # Mirror to <staging_root>/lean_repl/ for aggregated inspection.
    if query_json.exists():
        shutil.copy2(query_json, lean_repl_json)
    out["lean_query_returncode"] = qp.returncode
    out["lean_query_json"] = str(query_json)
    out["lean_query_log"] = str(query_log)

    if qp.returncode != 0:
        out["lean_error"] = f"lean_query failed (exit {qp.returncode}); see {query_log}"
        return out

    try:
        d = json.loads(qp.stdout)
        verdicts = [
            ((n.get("layer3") or {}).get("step_composite") or {}).get("verdict", "?")
            for n in d.get("per_node_results", [])
        ]
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v] = counts.get(v, 0) + 1
        with _STDOUT_LOCK:
            print(f"[{instance_id}] lean_query ok -- composite verdicts: {counts}",
                  flush=True)
    except Exception:
        pass

    return out


def run_instance(instance_id: str,
                 outputs_root: Path,
                 eval_root: Path,
                 layer2_ir: Path,
                 plan_name: str,
                 results_dir: Path,
                 workspace_root: Path,
                 staging_root: Path,
                 yaml_plan: Path,
                 conda_env: str,
                 dry_run: bool,
                 stream_logs: bool = True,
                 child_columns: int = 0,
                 child_lines: int = 0,
                 run_lean: bool = True,
                 verifier_dir: Path | None = None,
                 lean_timeout: int = 600,
                 resume: bool = False) -> dict:
    event_log = outputs_root / f"{instance_id}_agent_events.log"
    full_log = outputs_root / f"{instance_id}_full.log"
    eval_dir = eval_root / instance_id
    report = eval_dir / "report.json"
    test_output = eval_dir / "test_output.txt"

    inst_outputs = results_dir / f"{plan_name}_{instance_id}"
    inst_outputs.mkdir(parents=True, exist_ok=True)
    final_ir_path = inst_outputs / "layer3_ir.json"
    final_lean_path = inst_outputs / "per_step.lean"
    final_query_path = inst_outputs / "layer3_query.json"

    result: dict = {
        "instance_id": instance_id,
        "status": "unknown",
        "event_log": str(event_log),
        "report": str(report),
        "ir": str(final_ir_path),
        "lean": str(final_lean_path),
        "yaml_returncode": None,
        "ir_to_lean_returncode": None,
        "error": None,
        "resume_actions": [],
    }

    for required in (event_log, report, test_output, layer2_ir):
        if not required.exists():
            result["status"] = "skipped_missing_input"
            result["error"] = f"missing: {required}"
            return result

    # ------------------------------------------------------------------
    # Resume logic. Detect per-stage completion; skip what's already done.
    # Stages (A–D):
    #   A  AgentSPEX         -> writes layer3_ir.json
    #   B  ir_to_lean        -> writes per_step.lean
    #   C  lake build        -> writes VerificationExamples/.../olean
    #   D  lean_query        -> writes layer3_query.json (with per_node_results)
    # If layer3_query.json is already complete -> short-circuit (nothing to do).
    # Otherwise run only the missing suffix of stages.
    # ------------------------------------------------------------------
    reuse_ir = False
    reuse_lean = False
    reuse_query = False
    if resume:
        # --- Step 1: inventory existing artifacts on disk ---
        if final_ir_path.exists():
            reuse_ir = True
        # Migrate a YAML-staged IR to the durable results_dir if needed.
        staged_ir = staging_root / "outputs" / instance_id / "layer3_ir.json"
        if not reuse_ir and staged_ir.exists():
            shutil.copy2(staged_ir, final_ir_path)
            reuse_ir = True
            result["resume_actions"].append(f"migrated staged IR: {staged_ir} -> {final_ir_path}")
        if final_lean_path.exists():
            reuse_lean = True

        # --- Step 2: UPGRADE CHECK (runs BEFORE query short-circuit). ---
        # If a resumed IR exists but doesn't have its workflow parameters /
        # observed tools pre-seeded in exec_state, augment it here. We do this
        # before checking the query cache so out-of-date `layer3_query.json`
        # files (from prior buggy runs) are correctly invalidated.
        if reuse_ir:
            trace_index_path = staging_root / "staging" / instance_id / "trace_index.json"
            # Re-run the segmenter if the trace index is missing or predates the
            # current segmenter (which now emits workflow_parameters + observed_tools).
            needs_reseg = not trace_index_path.exists()
            if trace_index_path.exists():
                try:
                    ti = json.loads(trace_index_path.read_text(encoding="utf-8"))
                    needs_reseg = "workflow_parameters" not in ti or "observed_tools" not in ti
                except Exception:
                    needs_reseg = True
            if needs_reseg:
                pkg_dir = staging_root / "package"
                segmenter = (pkg_dir / "trace_segmenter.py") if (pkg_dir / "trace_segmenter.py").exists() else (HERE / "trace_segmenter.py")
                seg_cmd = [
                    sys.executable, str(segmenter),
                    "--event_log", str(event_log),
                    "--staging_dir", str(staging_root / "staging" / instance_id),
                    "--instance_id", instance_id,
                ]
                if full_log.exists():
                    seg_cmd += ["--full_log", str(full_log)]
                seg_proc = subprocess.run(seg_cmd, capture_output=True, text=True)
                if seg_proc.returncode != 0:
                    result["resume_actions"].append(
                        f"WARN: could not re-run trace_segmenter to upgrade IR: {seg_proc.stderr[-200:]}")
                else:
                    result["resume_actions"].append(
                        "re-ran trace_segmenter to emit workflow_parameters + observed_tools")

            missing = _ir_missing_seeds(final_ir_path, trace_index_path)
            if missing:
                added = _augment_ir_exec_state(final_ir_path, trace_index_path)
                result["resume_actions"].append(
                    f"upgraded IR exec_state with {len(added)} missing seed(s): {added}")
                # Force B/C/D to re-run so downstream artifacts reflect the fix.
                reuse_lean = False
                for stale in (final_lean_path, final_query_path,
                              _lean_repl_staging_path(staging_root, plan_name, instance_id)):
                    try:
                        if stale.exists():
                            stale.unlink()
                    except OSError:
                        pass
                with _STDOUT_LOCK:
                    print(f"[{instance_id}] resume: IR was missing {len(added)} "
                          f"exec_state seeds ({', '.join(added)}); "
                          f"augmented + re-running stages B/C/D",
                          flush=True)

        # --- Step 3: check query cache AFTER the upgrade step. ---
        if _query_is_complete(final_query_path):
            reuse_query = True
        else:
            staged_query = _lean_repl_staging_path(staging_root, plan_name, instance_id)
            if _query_is_complete(staged_query):
                shutil.copy2(staged_query, final_query_path)
                reuse_query = True
                result["resume_actions"].append(
                    f"migrated staged lean_repl JSON: {staged_query} -> {final_query_path}")

    if dry_run:
        # In dry-run mode, we don't actually do anything; but report the detected
        # resume state so the user can preview what would be skipped.
        if reuse_query:
            result["status"] = "dry_run_would_skip_complete"
        elif reuse_lean:
            result["status"] = "dry_run_would_resume_from_lean_query"
        elif reuse_ir:
            result["status"] = "dry_run_would_resume_from_ir_to_lean"
        else:
            result["status"] = "dry_run"
        result["command"] = "(see earlier --dry_run output)"
        return result

    if reuse_query:
        result["status"] = "resumed_complete"
        result["resume_actions"].append("layer3_query.json already populated; skipped all stages")
        with _STDOUT_LOCK:
            print(f"[{instance_id}] already complete (layer3_query.json present) — skipping.",
                  flush=True)
        return result

    if reuse_ir:
        with _STDOUT_LOCK:
            print(f"[{instance_id}] resume: IR already present, skipping AgentSPEX",
                  flush=True)
        result["resume_actions"].append("skipped AgentSPEX (IR already present)")
    if reuse_lean:
        with _STDOUT_LOCK:
            print(f"[{instance_id}] resume: .lean already present, skipping ir_to_lean",
                  flush=True)
        result["resume_actions"].append("skipped ir_to_lean (.lean already present)")

    # Skip the heavy workspace staging if we're not going to run AgentSPEX.
    stage: dict = {}
    if not reuse_ir:
        stage = stage_workspace(
            workspace_root, staging_root, instance_id, event_log,
            full_log if full_log.exists() else None,
            report, test_output, layer2_ir, yaml_plan,
        )

    # --------- Stage A: AgentSPEX (produces layer3_ir.json) ---------
    if not reuse_ir:
        env = os.environ.copy()
        # Disable per-step workspace-manifest snapshots for this Stage A
        # subprocess. With HOST_WORKSPACE set, the AgentSPEX scans the
        # entire <workspace_root> after every step and copies every file
        # >1 MB to <workspace_backup_path>. Under concurrent runs (10
        # parallel annotate workers sharing the same /workspace mount),
        # this thrashes NFS I/O and causes OSError(EIO) on the next LLM
        # call — especially lethal for local vLLM endpoints (Gemma4)
        # where the httpx socket lives on the same box. Stage A's
        # durable outputs (layer3_ir.json, layer3_query.json) are saved
        # explicitly into stage["output_ir_container"] — we don't need
        # the manifest snapshot mechanism.
        #
        # NOTE: HOST_WORKSPACE itself is re-exported by `source config/
        # host.env` inside scripts/run_agent.sh (with `set -a`), so
        # simply clearing it here is not enough. We also flip the
        # DISABLE_WORKSPACE_MANIFEST switch that agent.py reads from
        # the process environment; host.env does not mention that var,
        # so the source call cannot overwrite it.
        #
        # For OPENAI_API_KEY / VLLM_API_BASE / MODEL_NAME (and the other
        # provider keys) the situation is the opposite: scripts/run_agent.
        # sh now snapshots any caller-exported value before sourcing vm.
        # env/host.env and restores it afterwards, so whatever the user
        # exported (e.g. via `source experiments/SWE_bench_verified/
        # <model>_config.env`) reaches the inner `python -m agent.run`
        # intact.
        env["HOST_WORKSPACE"] = ""
        env["DISABLE_WORKSPACE_MANIFEST"] = "1"
        env.update({
            "INSTANCE_ID": instance_id,
            "PLAN_NAME": plan_name,
            "EVENT_LOG_PATH": stage["event_log_container"],
            "FULL_LOG_PATH": stage["full_log_container"],
            "REPORT_PATH": stage["report_container"],
            "TEST_OUTPUT_PATH": stage["test_output_container"],
            "LAYER2_IR_PATH": stage["layer2_ir_container"],
            "STAGING_DIR": stage["staging_dir_container"],
            "OUTPUT_IR_PATH": stage["output_ir_container"],
            "PACKAGE_DIR": stage["package_dir_container"],
            "HOST_EVENT_LOG_PATH": str(stage["event_log_host"]),
            "HOST_REPORT_PATH": str(stage["report_host"]),
            "PREFIX": "",
            "SUFFIX": "",
            "BANNER_TITLE": f"PER-STEP MOVE ANALYSIS — {instance_id}",
            "BANNER_SUBTITLE": "Layer 3 auto-annotated from agent_evolve",
        })
        # Drop any inherited COLUMNS/LINES so Rich in the child reads the live
        # PTY size via os.get_terminal_size(fd) and picks up SIGWINCH updates.
        env.pop("COLUMNS", None)
        env.pop("LINES", None)
        env.setdefault("FORCE_COLOR", "1")
        env.setdefault("CLICOLOR_FORCE", "1")

        run_agent = REPO_ROOT / "scripts" / "run_agent.sh"
        if not run_agent.exists():
            result["status"] = "error"
            result["error"] = f"scripts/run_agent.sh not found at {run_agent}"
            return result

        agent_output_dir = stage["ws_root_host"] / "runtime" / instance_id
        agent_output_dir.mkdir(parents=True, exist_ok=True)

        # Resume the inner AgentSPEX from its own checkpoint when one exists.
        # Without this, scripts/run_agent.sh rotates checkpoint.json out of
        # the way and starts from step 1 — wasting LLM calls from a run that
        # was interrupted partway through. We only opt in when the runtime
        # dir already has a checkpoint.json (so fresh instances are unaffected).
        inner_resume_args = ""
        checkpoint_path = agent_output_dir / "checkpoint.json"
        if resume and checkpoint_path.exists():
            inner_resume_args = " --resume"
            result["resume_actions"].append(
                f"inner agent --resume from existing checkpoint: {checkpoint_path}")

        cmd_parts = [
            f"source {shlex.quote(str(REPO_ROOT))}/config/host.env >/dev/null 2>&1 || true",
            'source "$(conda info --base)/etc/profile.d/conda.sh"',
            f"conda activate {shlex.quote(conda_env)}",
            f"export PYTHONPATH={shlex.quote(str(REPO_ROOT / 'engine' / 'src'))}:${{PYTHONPATH:-}}",
            ("bash "
             f"{shlex.quote(str(run_agent))} "
             f"{shlex.quote(str(yaml_plan))} "
             f"--no_dashboard "
             f"--output_dir {shlex.quote(str(agent_output_dir))}"
             f"{inner_resume_args}"),
        ]
        cmd_str = " && ".join(cmd_parts)

        driver_log_path = agent_output_dir / "driver.log"
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
        result["agent_output_dir"] = str(agent_output_dir)

        ws_ir = stage["output_ir_host"]
        if not ws_ir.exists():
            result["status"] = "yaml_failed"
            result["error"] = f"YAML exit={proc.returncode}; IR not produced in workspace"
            return result
        shutil.copy2(ws_ir, final_ir_path)
    else:
        # Resumed IR already at final_ir_path; mirror the YAML fields with "skipped".
        result["yaml_returncode"] = 0
        result["yaml_runtime_sec"] = 0

    # --------- Stage B: ir_to_lean (produces per_step.lean) ---------
    if not reuse_lean:
        lean_cmd = [sys.executable, str(HERE / "ir_to_lean.py"),
                    "--ir", str(final_ir_path), "--out", str(final_lean_path)]
        t0 = time.time()
        lean_proc = subprocess.run(lean_cmd, capture_output=True, text=True)
        result["ir_to_lean_runtime_sec"] = round(time.time() - t0, 2)
        result["ir_to_lean_returncode"] = lean_proc.returncode
        result["ir_to_lean_stderr_tail"] = "\n".join(lean_proc.stderr.splitlines()[-20:])
        if lean_proc.returncode != 0 or not final_lean_path.exists():
            result["status"] = "lean_gen_failed"
            result["error"] = (f"ir_to_lean exit={lean_proc.returncode}; "
                               f"lean exists={final_lean_path.exists()}")
            return result
    else:
        result["ir_to_lean_returncode"] = 0
        result["ir_to_lean_runtime_sec"] = 0

    result["status"] = "ok"

    if run_lean and verifier_dir is not None:
        lean_out = _run_lean_pipeline(
            instance_id=instance_id, plan_name=plan_name,
            final_ir_path=final_ir_path, final_lean_path=final_lean_path,
            staging_root=staging_root, verifier_dir=verifier_dir,
            results_instance_dir=inst_outputs,
            stream_logs=stream_logs,
            child_columns=child_columns, child_lines=child_lines,
            lean_timeout=lean_timeout,
        )
        result.update(lean_out)
        if lean_out.get("lean_error"):
            if lean_out.get("lean_build_returncode") not in (None, 0):
                result["status"] = "lean_build_failed"
            elif lean_out.get("lean_query_returncode") not in (None, 0):
                result["status"] = "lean_query_failed"
            else:
                result["status"] = "lean_failed"
            result["error"] = lean_out["lean_error"]

    return result


def main():
    p = argparse.ArgumentParser(description="Batch runner for agent_evolve Layer 3 pipeline.")
    p.add_argument("--outputs_root", required=True)
    p.add_argument("--eval_root", required=True)
    p.add_argument("--layer2_ir", required=True)
    p.add_argument("--plan_name", default="passed_workflow_1")
    p.add_argument("--results_dir", required=True)
    p.add_argument("--workspace_root",
                   default="workspace",
                   help="Host path to the workspace dir that the sandbox mounts as /workspace")
    p.add_argument("--staging_root",
                   default="",
                   help=("Per-run base dir that contains package/, inputs/, staging/, outputs/, runtime/ "
                         "subdirs. Must be inside --workspace_root. Default: <workspace_root>/agent_evolve_run. "
                         "Pass a custom value to isolate parallel or per-model runs."))
    p.add_argument("--yaml_plan", default=str(HERE / "annotate_layer3.yaml"))
    p.add_argument("--conda_env", default="agent_env",
                   help="Conda env with AgentSPEX deps (default: agent_env)")
    p.add_argument("--single_instance", default="")
    p.add_argument("--instance_ids", default="",
                   help="Comma-separated whitelist of instance IDs to process "
                        "(e.g. django__django-14140,matplotlib__matplotlib-25775). "
                        "Overrides --limit ordering. Takes effect after "
                        "--skip_resolved filters out already-solved ones.")
    p.add_argument("--skip_resolved", action="store_true")
    p.add_argument("--limit", type=int, default=0,
                   help="If >0, process at most this many instances (after sorting & skip_resolved).")
    p.add_argument("--max_parallel", type=int, default=1,
                   help="Run up to N instances concurrently via ThreadPoolExecutor. "
                        "1 = sequential (default). Be mindful of OpenAI rate limits and the shared MCP server.")
    p.add_argument("--stream_logs", action="store_true", default=True,
                   help="Stream each worker's AgentSPEX stdout (prefixed with "
                        "[<instance_id>]) to this process's stdout in real time "
                        "(default: on).")
    p.add_argument("--no_stream_logs", dest="stream_logs", action="store_false",
                   help="Suppress real-time per-instance streaming. The full output is "
                        "still saved to <staging_root>/runtime/<instance_id>/driver.log.")
    p.add_argument("--run_lean", action="store_true", default=True,
                   help="After each .lean is generated, run `lake build` + `lean_query` "
                        "on the host to produce a structured JSON verdict "
                        "(default: on). Lean files live at "
                        "<staging_root>/lean_files/<plan>_<instance>_per_step.lean.")
    p.add_argument("--no_run_lean", dest="run_lean", action="store_false",
                   help="Skip the lake build + lean_query post-processing step.")
    p.add_argument("--verifier_dir", default="",
                   help="Host path to the Verifier project (has lakefile.toml). "
                        "Default: <repo>/FormalAgentLib.")
    p.add_argument("--lean_timeout", type=int, default=600,
                   help="Per-instance timeout (seconds) for lake build and lean_query "
                        "(default: 600).")
    p.add_argument("--resume", action="store_true",
                   help="Resume from prior runs. Per-instance, skip any stage whose "
                        "artifact already exists under <results_dir>/<plan>_<instance>/: "
                        "layer3_ir.json (stage A), per_step.lean (stage B), "
                        "layer3_query.json with populated per_node_results (stages C+D). "
                        "If no prior artifacts are found anywhere, prints a warning and "
                        "proceeds as a fresh run.")
    p.add_argument("--summary", default="")
    p.add_argument("--dry_run", action="store_true")
    args = p.parse_args()

    outputs_root = Path(args.outputs_root).resolve()
    eval_root = Path(args.eval_root).resolve()
    layer2_ir = Path(args.layer2_ir).resolve()
    results_dir = Path(args.results_dir).resolve()
    workspace_root = Path(args.workspace_root).resolve()
    yaml_plan = Path(args.yaml_plan).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    if not workspace_root.exists():
        print(f"ERROR: workspace_root not found: {workspace_root}", file=sys.stderr)
        sys.exit(1)

    if args.staging_root:
        staging_root = Path(args.staging_root).resolve()
    else:
        staging_root = workspace_root / "agent_evolve_run"
    try:
        staging_root.relative_to(workspace_root)
    except ValueError:
        print(f"ERROR: --staging_root ({staging_root}) must be inside --workspace_root "
              f"({workspace_root}) so the sandbox Docker can see it under /workspace/.",
              file=sys.stderr)
        sys.exit(1)
    staging_root.mkdir(parents=True, exist_ok=True)

    verifier_dir = Path(args.verifier_dir).resolve() if args.verifier_dir \
                   else (REPO_ROOT / "FormalAgentLib").resolve()
    if args.run_lean:
        if not (verifier_dir / "lakefile.toml").is_file():
            print(f"ERROR: --verifier_dir has no lakefile.toml: {verifier_dir}. "
                  f"Pass --no_run_lean to skip the lake build + lean_query step.",
                  file=sys.stderr)
            sys.exit(1)

    if args.single_instance:
        instances = [args.single_instance]
    elif args.instance_ids:
        requested = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        available = set(find_instances(outputs_root))
        missing = [i for i in requested if i not in available]
        if missing:
            print(f"WARNING: {len(missing)} requested instance(s) not found under "
                  f"{outputs_root}: {missing}", flush=True)
        instances = [i for i in requested if i in available]
    else:
        instances = find_instances(outputs_root)
    if not instances:
        print(f"ERROR: no instances found under {outputs_root}", file=sys.stderr)
        sys.exit(1)

    # Pre-filter: resolved-skip (cheap, sequential) + --limit cap, so the parallel
    # pool only ever receives instances we actually intend to process.
    summary: list[dict] = []
    to_process: list[tuple[int, int, str]] = []  # (idx, total, instance_id)
    total = len(instances)
    selected = 0
    for idx, inst in enumerate(instances, 1):
        if args.limit and selected >= args.limit:
            print(f"[limit] reached --limit={args.limit}; stopping "
                  f"after selecting {selected} (out of {total} found).", flush=True)
            break
        if args.skip_resolved:
            resolved = is_resolved(eval_root / inst / "report.json", inst)
            if resolved is True:
                summary.append({"instance_id": inst, "status": "skipped_resolved"})
                print(f"[{idx}/{total}] {inst} -> skipped_resolved", flush=True)
                continue
        to_process.append((idx, total, inst))
        selected += 1

    if not to_process:
        print("No instances to process.", flush=True)
    else:
        print(f"\n{len(to_process)} instance(s) queued "
              f"(max_parallel={args.max_parallel}, dry_run={args.dry_run}, "
              f"resume={args.resume})",
              flush=True)

        # Resume-mode status report: per-stage artifact detection + fresh-run warn.
        if args.resume:
            inst_ids = [x[2] for x in to_process]
            # Backfill the staging lean_repl/ mirror from any pre-existing
            # results_dir/<…>/layer3_query.json so both sides stay in sync.
            lean_repl_dir = staging_root / _LEAN_REPL_SUBDIR
            lean_repl_dir.mkdir(parents=True, exist_ok=True)
            for inst in inst_ids:
                durable = results_dir / f"{args.plan_name}_{inst}" / "layer3_query.json"
                mirror = _lean_repl_staging_path(staging_root, args.plan_name, inst)
                if durable.exists() and not mirror.exists():
                    try:
                        shutil.copy2(durable, mirror)
                    except Exception:
                        pass
            arts = _detect_resume_artifacts(results_dir, staging_root,
                                            args.plan_name, inst_ids)
            counts = {"complete": 0, "complete_staging_only": 0,
                      "have_lean": 0, "have_ir": 0, "fresh": 0}
            for inst in inst_ids:
                a = arts[inst]
                if a["query"]:
                    counts["complete"] += 1
                    if a.get("query_staging_only"):
                        counts["complete_staging_only"] += 1
                elif a["lean"]:
                    counts["have_lean"] += 1
                elif a["ir"]:
                    counts["have_ir"] += 1
                else:
                    counts["fresh"] += 1
            print(f"  [resume] stages detected: "
                  f"complete={counts['complete']} "
                  f"(staging_only={counts['complete_staging_only']}), "
                  f"have_lean={counts['have_lean']}, "
                  f"have_ir={counts['have_ir']}, "
                  f"fresh={counts['fresh']}", flush=True)
            if counts["complete"] + counts["have_lean"] + counts["have_ir"] == 0:
                print("  [resume] WARNING: --resume was passed but no prior artifacts "
                      "were found for any selected instance. Proceeding as a fresh run.",
                      flush=True)

        if not args.dry_run:
            stage_shared(staging_root, yaml_plan)

    # Figure out how wide each child's Rich/term-aware output should be rendered.
    # We prefix every streamed line with "[<instance_id>] ", so the child's usable
    # width is the parent's terminal width minus that prefix. Use the longest
    # instance_id in the queue so the widest prefix fits.
    try:
        term_cols, term_lines = shutil.get_terminal_size(fallback=(120, 40))
    except Exception:
        term_cols, term_lines = 120, 40
    longest_inst = max((len(x[2]) for x in to_process), default=0)
    prefix_pad = longest_inst + 3  # "[" + id + "] "
    if args.stream_logs:
        child_columns = max(_MIN_CHILD_COLUMNS, term_cols - prefix_pad)
    else:
        child_columns = max(120, term_cols)
    child_lines = term_lines

    # Publish prefix_pad / stream_logs to module globals so the SIGWINCH handler
    # can recompute each active child's width when the parent terminal is resized.
    global _PREFIX_PAD, _STREAM_LOGS_ENABLED
    _PREFIX_PAD = prefix_pad
    _STREAM_LOGS_ENABLED = bool(args.stream_logs)
    if not args.dry_run:
        _install_winch_handler_once()

    summary_lock = threading.Lock()

    def _work(item: tuple[int, int, str]) -> dict:
        idx, tot, inst = item
        with _STDOUT_LOCK:
            print(f"[{idx}/{tot}] {inst} -> starting", flush=True)
        r = run_instance(inst, outputs_root, eval_root, layer2_ir,
                         args.plan_name, results_dir, workspace_root,
                         staging_root, yaml_plan, args.conda_env,
                         args.dry_run, stream_logs=args.stream_logs,
                         child_columns=child_columns, child_lines=child_lines,
                         run_lean=args.run_lean and not args.dry_run,
                         verifier_dir=verifier_dir,
                         lean_timeout=args.lean_timeout,
                         resume=args.resume)
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
                    r = {"instance_id": inst, "status": "error", "error": f"{type(e).__name__}: {e}"}
                    print(f"[{inst}] unexpected exception: {e}", flush=True)
                with summary_lock:
                    summary.append(r)
    else:
        for item in to_process:
            r = _work(item)
            summary.append(r)

    summary_path = Path(args.summary) if args.summary else (results_dir / "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    totals: dict[str, int] = {}
    for r in summary:
        totals[r["status"]] = totals.get(r["status"], 0) + 1
    print(f"\nSUMMARY -> {summary_path}")
    for k, v in sorted(totals.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
