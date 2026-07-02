"""
Tools:
  - execute_python_code
  - execute_python_script
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import textwrap
import time
from pathlib import Path
from typing import List, Optional

from fastmcp import Context

from sandbox_vm.tools.session_management import MANAGER
from sandbox_vm.tools.utils import _err

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    name = (name or "").strip()
    name = name.replace("/", "_").replace("\\", "_")
    name = _SAFE_NAME_RE.sub("_", name)
    return name or "script.py"


def _clamp_timeout(t: int, low: int = 1, high: int = 300) -> int:
    try:
        n = int(t)
    except Exception:
        n = 30
    return max(low, min(high, n))


async def execute_python_code(
    ctx: Context,
    code: str,
    timeout: int = 30,
    *,
    parent: Optional[str] = None,
    filename: Optional[str] = None,
    save_to_file: bool = False,
) -> dict:
    """
    Execute Python code. Saves the script to a file if save_to_file is True and a parent and filename are provided.

    Returns: { stdout, stderr, return_code, execution_time, file_path?, error? }
    """
    sid = getattr(ctx, "session_id", None)
    if not sid:
        return _err("session_id_REQUIRED", message="ctx.session_id is missing")

    rt = MANAGER.get(sid)
    env = rt.minimal_env()
    tout = _clamp_timeout(timeout)

    try:
        base_dir = (
            (rt.root / parent.lstrip("/")) if parent else (rt.root / "tmp" / "code")
        ).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return _err(type(e).__name__, message=str(e))

    clean_code = textwrap.dedent(code or "").strip() + "\n"

    temp_file_path: Optional[str] = None
    persisted = False
    result = {
        "stdout": "",
        "stderr": "",
        "return_code": -1,
        "execution_time": 0.0,
    }

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=base_dir, delete=False
        ) as tf:
            tf.write(clean_code)
            temp_file_path = tf.name
        # tempfile.NamedTemporaryFile creates files with 0600 (mkstemp);
        # relax to 0644 so the host process can read them for backups.
        os.chmod(temp_file_path, 0o644)

        if save_to_file:
            final_name = _sanitize_filename(
                filename or f"code_{Path(temp_file_path).name}"
            )
            final_path = Path(base_dir) / final_name
            os.replace(temp_file_path, final_path)
            temp_file_path = str(final_path)
            persisted = True
            result["file_path"] = str(final_path)

        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            "python3",
            temp_file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(base_dir),
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=tout)
            result["execution_time"] = time.time() - start
            result["return_code"] = proc.returncode

            result["stdout"] = rt.redact(
                (stdout or b"").decode("utf-8", errors="replace")
            )
            result["stderr"] = rt.redact(
                (stderr or b"").decode("utf-8", errors="replace")
            )

            if proc.returncode != 0:
                result["error"] = f"Code exited with return code {proc.returncode}"

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["error"] = f"Code execution timed out after {tout} seconds"

    except Exception as e:
        result["error"] = f"Failed to execute code: {e}"

    finally:
        if temp_file_path and not persisted:
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        rt.touch()

    return result


async def execute_python_script(
    ctx: Context,
    script_path: str,
    args: Optional[List[str]] = None,
    timeout: int = 30,
    *,
    cwd_path: Optional[str] = None,  # defaults to script's parent
) -> dict:
    """
    Execute an existing Python script
    """
    sid = getattr(ctx, "session_id", None)
    if not sid:
        return _err("session_id_REQUIRED", message="ctx.session_id is missing")

    rt = MANAGER.get(sid)
    env = rt.minimal_env()
    tout = _clamp_timeout(timeout)

    try:
        sp = (rt.root / script_path.lstrip("/")).resolve()
        if not sp.exists():
            return _err(
                "FILE_NOT_FOUND", message=f"Script does not exist: {script_path}"
            )
        if sp.suffix.lower() != ".py":
            return _err(
                "INVALID_ARGUMENT", message=f"File must be a .py script: {sp.name}"
            )

        cwd = (rt.root / cwd_path.lstrip("/")).resolve() if cwd_path else sp.parent

        cmd = ["python3", str(sp)]
        if args:
            cmd.extend([str(a) for a in args])

        result = {
            "stdout": "",
            "stderr": "",
            "return_code": -1,
            "execution_time": 0.0,
            "script_path": script_path,
        }

        start = time.time()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=tout)
            result["execution_time"] = time.time() - start
            result["return_code"] = proc.returncode

            result["stdout"] = rt.redact(
                (stdout or b"").decode("utf-8", errors="replace")
            )
            result["stderr"] = rt.redact(
                (stderr or b"").decode("utf-8", errors="replace")
            )

            if proc.returncode != 0:
                result["error"] = f"Script exited with return code {proc.returncode}"

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["error"] = f"Script execution timed out after {tout} seconds"

    except Exception as e:
        return _err(type(e).__name__, message=str(e))

    finally:
        rt.touch()

    return result
