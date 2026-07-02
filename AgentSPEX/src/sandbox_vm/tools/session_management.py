from __future__ import annotations

import atexit
import hashlib
import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

import pexpect

SESSION_TTL_SECONDS = int(os.environ.get("BROWSER_SESSION_TTL_SECONDS", "300"))
MAX_SESSIONS = int(os.environ.get("BROWSER_MAX_SESSIONS", "100"))


def _default_sessions_dir() -> str:
    vm_ws = os.environ.get("VM_WORKSPACE", "/workspace")
    # Inside Docker /workspace is writable; locally it doesn't exist.
    if os.path.isdir(vm_ws) and os.access(vm_ws, os.W_OK):
        return vm_ws + "/sessions"
    # Fall back to <project>/workspace/sessions (HOST_WORKSPACE) or /tmp
    host_ws = os.environ.get("HOST_WORKSPACE", "")
    if host_ws and os.access(os.path.dirname(host_ws) or ".", os.W_OK):
        return host_ws + "/sessions"
    return os.path.join(os.getcwd(), "workspace", "sessions")


SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", _default_sessions_dir())).resolve()
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

Perm = Literal["r", "w", "rw", "list"]


def session_fs_key(session_id: str) -> str:
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:16]


class PersistentShell:
    def __init__(self, cwd: str, env: dict, history_lines: int = 4000):
        self._pexpect = pexpect
        self.proc = pexpect.spawn(
            "/bin/bash",
            ["-i"],
            cwd=cwd,
            env=env,
            encoding="utf-8",
            echo=False,
        )
        self.proc.delaybeforesend = 0

        from collections import deque

        self._buf = deque(maxlen=int(history_lines))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(
            target=self._drain_loop, name="pexpect-drain", daemon=True
        )
        self._reader.start()
        self.send("export PS1='[vs] '")

    def _drain_loop(self):
        while not self._stop.is_set():
            try:
                chunk = self.proc.read_nonblocking(size=4096, timeout=0.1)
                if chunk:
                    with self._lock:
                        for line in chunk.splitlines(True):
                            self._buf.append(line)
            except self._pexpect.TIMEOUT:
                continue
            except self._pexpect.EOF:
                break
            except Exception:
                continue

    def send(self, text: str) -> None:
        with self._lock:
            self.proc.sendline(text or "")

    def tail(self, lines: int = 200) -> str:
        with self._lock:
            if lines <= 0:
                return ""
            return "".join(list(self._buf)[-int(lines) :])

    def close(self) -> None:
        self._stop.set()
        try:
            if self.proc.isalive():
                try:
                    self.proc.sendline("exit")
                except Exception:
                    pass
                self.proc.close(force=True)
        except Exception:
            pass
        try:
            if self._reader and self._reader.is_alive():
                self._reader.join(timeout=1.0)
        except Exception:
            pass


@dataclass
class HandleRec:
    real_path: Path
    perm: Perm
    is_dir: bool
    expires_at: Optional[float]
    label: str


@dataclass
class SessionRuntime:
    session_id: str
    root: Path
    last_used: float = field(default_factory=time.time)

    pty_shell: Optional[PersistentShell] = None
    browser_worker: Optional[object] = None
    handles: Dict[str, HandleRec] = field(default_factory=dict)

    def ensure_dirs(self):
        (self.root / "url_download").mkdir(parents=True, exist_ok=True)
        (self.root / "shots").mkdir(parents=True, exist_ok=True)
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)

    def touch(self) -> None:
        self.last_used = time.time()

    def minimal_env(self) -> Dict[str, str]:
        keep = {"PATH", "LANG", "LC_ALL", "TZ"}
        base = {k: v for k, v in os.environ.items() if k in keep}
        base.setdefault(
            "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        )
        base.setdefault("LANG", "C.UTF-8")
        base["HOME"] = str(self.root)
        # Drop Python-specific/credentials vars if present
        for k in list(base.keys()):
            if k.upper().startswith(
                ("AWS_", "GOOGLE_", "GCP_", "AZURE_", "OPENAI_", "HUGGINGFACE_")
            ):
                base.pop(k, None)
        return base

    def get_or_create_shell(self, history_lines: int = 500) -> PersistentShell:
        """
        Return a live PersistentShell; create it if missing or dead.
        """
        sh = getattr(self, "pty_shell", None)
        if sh is None or getattr(sh, "proc", None) is None or not sh.proc.isalive():
            self.pty_shell = PersistentShell(
                cwd=str(self.root), env=self.minimal_env(), history_lines=history_lines
            )
        self.touch()
        return self.pty_shell

    def close_shell(self) -> None:
        try:
            sh = getattr(self, "pty_shell", None)
            if sh is not None:
                sh.close()
        except Exception:
            pass
        finally:
            self.pty_shell = None

    def close_sync(self) -> None:
        """Close shell and clean up session directory."""
        self.close_shell()
        try:
            if self.root.exists():
                shutil.rmtree(self.root, ignore_errors=True)
        except Exception:
            pass

    def _new_id(self) -> str:
        return secrets.token_urlsafe(8)

    def publish_path(
        self,
        p: Path,
        perm: Perm = "r",
        label: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        p = p.resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("path outside session root")
        hid = self._new_id()
        rec = HandleRec(
            real_path=p,
            perm=perm,
            is_dir=p.is_dir(),
            expires_at=(time.time() + ttl_seconds) if ttl_seconds else None,
            label=(label or (p.name if p.name else "resource")),
        )
        self.handles[hid] = rec
        return f"sandbox:/{hid}/{rec.label}"

    def revoke(self, handle_uri: str) -> None:
        hid = self._handle_id(handle_uri)
        if hid:
            self.handles.pop(hid, None)

    def _handle_id(self, handle_uri: str) -> Optional[str]:
        if not (handle_uri and handle_uri.startswith("sandbox:/")):
            return None
        parts = handle_uri.split("/", 3)
        if len(parts) < 3 or not parts[2]:
            return None
        return parts[2]

    def resolve(self, handle_uri: str, need: Perm) -> Path:
        hid = self._handle_id(handle_uri)
        if not hid:
            raise ValueError("invalid sandbox handle")
        rec = self.handles.get(hid)
        if not rec:
            raise FileNotFoundError("handle not found or expired")
        if rec.expires_at and time.time() > rec.expires_at:
            self.handles.pop(hid, None)
            raise FileNotFoundError("handle expired")
        # Capability check
        if need == "r" and rec.perm not in ("r", "rw"):
            raise PermissionError("read denied")
        if need == "w" and rec.perm not in ("w", "rw"):
            raise PermissionError("write denied")
        if need == "list" and not rec.is_dir:
            raise NotADirectoryError("not a directory")

        p = rec.real_path.resolve()
        if not str(p).startswith(str(self.root)):
            raise PermissionError("resolved path escapes session root")
        return p

    def redact(self, s: str) -> str:
        r = str(self.root)
        return s.replace(r, "sandbox:/")


class SessionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, SessionRuntime] = {}
        self._stop = threading.Event()
        self._janitor = threading.Thread(
            target=self._run_janitor, daemon=True, name="session-janitor"
        )
        self._janitor.start()
        atexit.register(self.shutdown)

    def get(self, session_id: str) -> SessionRuntime:
        if not session_id:
            raise KeyError("session_id_REQUIRED")
        with self._lock:
            rt = self._sessions.get(session_id)
            if rt:
                return rt
            # Evict LRU if needed
            if len(self._sessions) >= MAX_SESSIONS:
                stalest_sid, stalest_rt = None, None
                for sid, srt in self._sessions.items():
                    if stalest_rt is None or srt.last_used < stalest_rt.last_used:
                        stalest_sid, stalest_rt = sid, srt
                if stalest_sid:
                    self._sessions.pop(stalest_sid, None)
                    try:
                        stalest_rt.close_sync()
                    except Exception:
                        pass
            root = (SESSIONS_DIR / session_fs_key(session_id)).resolve()
            rt = SessionRuntime(session_id=session_id, root=root)
            rt.ensure_dirs()
            self._sessions[session_id] = rt
            return rt

    def touch(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].touch()

    def destroy(self, session_id: str) -> None:
        with self._lock:
            rt = self._sessions.pop(session_id, None)
        if rt:
            rt.close_sync()

    def _run_janitor(self) -> None:
        while not self._stop.is_set():
            time.sleep(10)
            now = time.time()
            expired: list[tuple[str, SessionRuntime]] = []
            with self._lock:
                for sid, rt in list(self._sessions.items()):
                    if now - rt.last_used > SESSION_TTL_SECONDS:
                        expired.append((sid, rt))
                        self._sessions.pop(sid, None)

            for sid, rt in expired:
                try:
                    rt.close_sync()
                except Exception:
                    try:
                        root = (SESSIONS_DIR / session_fs_key(sid)).resolve()
                        shutil.rmtree(root, ignore_errors=True)
                    except Exception:
                        pass

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        for _, rt in sessions:
            try:
                rt.close_sync()
            except Exception:
                pass


MANAGER = SessionManager()
