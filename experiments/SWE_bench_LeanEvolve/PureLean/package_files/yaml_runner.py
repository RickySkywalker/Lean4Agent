#!/usr/bin/env python3
"""
yaml_runner.py - Spawn a YAML agent workflow via `scripts/run_agent.sh` over
a PTY so the AgentSPEX's stdout streams to the parent's terminal in real
time (matching the SWE pipeline pattern in
`leanagent/codegen/agent_evolve/run_agent_evolve.py::_spawn_with_pty + _read_pty_stream`).

Each output line is:
  - prefixed with `[<log_label>] ` and serialized via _STDOUT_LOCK so parallel
    workers don't interleave mid-line,
  - tee'd to `<runtime_dir>/driver.log`,
  - kept in memory so the caller can inspect the tail on failure.

Watchdogs:
  * `timeout_sec`        - overall wallclock cap; SIGTERM then SIGKILL.
  * `idle_timeout_sec`   - fires when `agent_events.log` stops growing.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())

# Shared lock so multiple ThreadPool workers can't interleave their lines.
_STDOUT_LOCK = threading.Lock()

# Active children registry, keyed by pid. Used by the SIGWINCH handler to
# propagate parent terminal resizes to every child's pty.
_ACTIVE_CHILDREN_LOCK = threading.Lock()
_ACTIVE_CHILDREN: dict[int, tuple[int, str]] = {}

_PREFIX_PAD = 30
_MIN_CHILD_COLUMNS = 60


def _set_pty_size(fd: int, rows: int, cols: int) -> None:
    try:
        size = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except Exception:
        pass


def _winch_handler(signum, frame):
    try:
        term = shutil.get_terminal_size(fallback=(120, 40))
    except Exception:
        return
    child_cols = max(_MIN_CHILD_COLUMNS, term.columns - _PREFIX_PAD)
    with _ACTIVE_CHILDREN_LOCK:
        active = list(_ACTIVE_CHILDREN.items())
    for pid, (master_fd, _label) in active:
        _set_pty_size(master_fd, term.lines, child_cols)
        try:
            os.killpg(pid, signal.SIGWINCH)
        except (ProcessLookupError, PermissionError):
            pass


_winch_installed = False


def _install_winch_handler_once() -> None:
    global _winch_installed
    if _winch_installed:
        return
    try:
        signal.signal(signal.SIGWINCH, _winch_handler)
        _winch_installed = True
    except (ValueError, AttributeError, OSError):
        pass


def _spawn_with_pty(cmd_argv: list[str], cwd: str, env: dict[str, str],
                    rows: int, cols: int) -> tuple[subprocess.Popen, int]:
    master_fd, slave_fd = pty.openpty()
    _set_pty_size(slave_fd, rows, cols)
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
        start_new_session=True,
    )
    os.close(slave_fd)
    return proc, master_fd


def _read_pty_stream(master_fd: int, label: str, log_handle,
                     stream_to_stdout: bool = True,
                     tail_lines: int = 80) -> list[str]:
    """Drain the pty master, write each line to stdout (prefixed) and to
    the per-instance driver.log. Returns the last `tail_lines` lines."""
    all_lines: list[str] = []
    buffer = b""

    def _emit(line: str) -> None:
        all_lines.append(line)
        prefixed = f"[{label}] {line}\n"
        if stream_to_stdout:
            with _STDOUT_LOCK:
                sys.stdout.write(prefixed)
                sys.stdout.flush()
        try:
            log_handle.write(prefixed.encode("utf-8", errors="replace"))
            log_handle.flush()
        except Exception:
            pass

    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except BlockingIOError:
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
            _emit(line)

    if buffer:
        tail_line = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
        if tail_line:
            _emit(tail_line)

    return all_lines[-tail_lines:]


def run_yaml_agent(
    yaml_path: Path,
    env_overrides: dict[str, str],
    runtime_dir: Path,
    timeout_sec: int = 1800,
    idle_timeout_sec: int = 600,
    conda_env: str = "agent_env",
    resume: bool = True,
    log_label: str = "",
    stream_to_stdout: bool = True,
) -> int:
    """Spawn `scripts/run_agent.sh <yaml_path>` over a PTY so the AgentSPEX's
    output streams to the terminal AND is tee'd to `<runtime_dir>/driver.log`.
    Returns the subprocess returncode."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    run_agent = REPO_ROOT / "AgentSPEX" / "scripts" / "run_agent.sh"
    if not run_agent.exists():
        raise FileNotFoundError(f"AgentSPEX/scripts/run_agent.sh not found at {run_agent}")

    env = os.environ.copy()
    env.update({k: str(v) for k, v in env_overrides.items()})
    env["DISABLE_WORKSPACE_MANIFEST"] = "1"
    env["FORCE_COLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    src_path = str(REPO_ROOT / "AgentSPEX" / "src")
    if src_path not in env.get("PYTHONPATH", ""):
        env["PYTHONPATH"] = f"{src_path}:{env.get('PYTHONPATH', '')}"

    label = log_label or yaml_path.stem

    resume_flag = "--resume " if resume else ""
    inner = (
        f"bash {shlex.quote(str(run_agent))} "
        f"{shlex.quote(str(yaml_path))} "
        f"--no_dashboard {resume_flag}"
        f"--output_dir {shlex.quote(str(runtime_dir))}"
    )
    activation_lines: list[str] = []
    # Locate conda.sh from the active conda installation (no hard-coded home).
    _conda_exe = os.environ.get("CONDA_EXE", "")
    conda_sh = (str(Path(_conda_exe).resolve().parent.parent
                    / "etc" / "profile.d" / "conda.sh") if _conda_exe else "")
    if conda_sh and Path(conda_sh).exists():
        activation_lines.append(f"source {conda_sh}")
        activation_lines.append(f"conda activate {shlex.quote(conda_env)}")
    # `bash -lc` runs `~/.bashrc`, which can hard-`export OPENAI_API_KEY=...`
    # and clobber the caller's per-model key (e.g. AtlasCloud key for Kimi).
    # Re-assert caller-precedence keys here, AFTER login init, so run_agent.sh's
    # snapshot picks up the values the caller actually intended.
    _CALLER_PRECEDENCE_KEYS = (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "VLLM_API_BASE",
        "HOSTED_VLLM_API_BASE", "MODEL_NAME", "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY", "COHERE_API_KEY", "MISTRAL_API_KEY",
        "AZURE_API_KEY", "HOSTED_VLLM_API_KEY", "VLLM_API_KEY",
    )
    for _k in _CALLER_PRECEDENCE_KEYS:
        _v = env.get(_k)
        if _v:
            activation_lines.append(
                f"export {_k}={shlex.quote(_v)}")
    activation_lines.append(inner)
    cmd_str = " && ".join(activation_lines)

    driver_log_path = runtime_dir / "driver.log"
    _install_winch_handler_once()

    try:
        term = shutil.get_terminal_size(fallback=(120, 40))
        rows, cols = term.lines, max(_MIN_CHILD_COLUMNS, term.columns - _PREFIX_PAD)
    except Exception:
        rows, cols = 40, 120

    with driver_log_path.open("ab") as logf:
        header = (f"\n=== run_yaml_agent {label} @ "
                  f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                  f"cwd={REPO_ROOT}\nyaml={yaml_path}\nruntime_dir={runtime_dir}\n"
                  f"env_overrides={env_overrides}\n")
        logf.write(header.encode("utf-8"))
        logf.flush()
        if stream_to_stdout:
            with _STDOUT_LOCK:
                sys.stdout.write(f"[{label}] === starting YAML agent on {yaml_path.name} ===\n")
                sys.stdout.flush()

        # Spawn from AgentSPEX/: run_agent.sh sources `config/vm.env` +
        # `config/host.env` (relative to cwd) BEFORE its own `cd PROJECT_ROOT`,
        # and `config/` lives only under AgentSPEX/. yaml_path and --output_dir
        # are absolute, so the cwd is otherwise free to point at the engine root.
        proc, master_fd = _spawn_with_pty(
            ["bash", "-lc", cmd_str], cwd=str(REPO_ROOT / "AgentSPEX"), env=env,
            rows=rows, cols=cols,
        )
        with _ACTIVE_CHILDREN_LOCK:
            _ACTIVE_CHILDREN[proc.pid] = (master_fd, label)

        watchdog_done = threading.Event()
        watchdog_fired = {"flag": False}

        def _wallclock_watchdog() -> None:
            if timeout_sec <= 0:
                return
            if watchdog_done.wait(timeout=timeout_sec):
                return
            if proc.poll() is None:
                watchdog_fired["flag"] = True
                msg = f"[{label}] === wallclock timeout {timeout_sec}s; SIGTERM ===\n"
                with _STDOUT_LOCK:
                    sys.stdout.write(msg)
                    sys.stdout.flush()
                logf.write(msg.encode("utf-8"))
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                time.sleep(5)
                if proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

        wd_thread = (threading.Thread(target=_wallclock_watchdog, daemon=True)
                     if timeout_sec > 0 else None)
        if wd_thread:
            wd_thread.start()

        # Idle-watchdog: if the AgentSPEX's events log doesn't grow for
        # idle_timeout_sec, force-terminate.
        if idle_timeout_sec > 0:
            evt_log = runtime_dir / "agent_events.log"

            def _idle_watchdog() -> None:
                last_size, last_change = -1, time.time()
                while proc.poll() is None:
                    time.sleep(15)
                    sz = evt_log.stat().st_size if evt_log.exists() else 0
                    if sz != last_size:
                        last_size = sz
                        last_change = time.time()
                    if time.time() - last_change > idle_timeout_sec:
                        watchdog_fired["flag"] = True
                        msg = (f"[{label}] === idle {idle_timeout_sec}s "
                               f"(events log not growing); SIGTERM ===\n")
                        with _STDOUT_LOCK:
                            sys.stdout.write(msg)
                            sys.stdout.flush()
                        logf.write(msg.encode("utf-8"))
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        except (ProcessLookupError, PermissionError):
                            pass
                        time.sleep(5)
                        if proc.poll() is None:
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except (ProcessLookupError, PermissionError):
                                pass
                        break

            threading.Thread(target=_idle_watchdog, daemon=True).start()

        # Drain stdout. This BLOCKS until the child closes the pty.
        try:
            _read_pty_stream(master_fd, label, logf,
                             stream_to_stdout=stream_to_stdout)
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

        rc = proc.wait()
        watchdog_done.set()
        with _ACTIVE_CHILDREN_LOCK:
            _ACTIVE_CHILDREN.pop(proc.pid, None)
        end_msg = f"[{label}] === exited rc={rc} (wallclock_fired={watchdog_fired['flag']}) ===\n"
        if stream_to_stdout:
            with _STDOUT_LOCK:
                sys.stdout.write(end_msg)
                sys.stdout.flush()
        logf.write(end_msg.encode("utf-8"))
    return rc


if __name__ == "__main__":
    print(f"REPO_ROOT={REPO_ROOT}")
    print(f"run_agent.sh exists: {(REPO_ROOT / 'AgentSPEX' / 'scripts' / 'run_agent.sh').exists()}")
