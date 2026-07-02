import asyncio
import os
import shlex
import subprocess

TMUX_SESSION = os.getenv("TMUX_SESSION", "vs")
TMUX_PANE = "pt." + TMUX_SESSION


def term_send(text: str) -> dict:
    """
    Send text to the terminal tmux pane and presses enter.

    Args:
        text: The literal text to send; special characters are escaped.

    Returns:
        {} on success.
    """
    safe = text.replace("'", "'\\''")
    subprocess.check_call(
        f"tmux send-keys -t {TMUX_SESSION} '{safe}' C-m",
        shell=True,
        executable="/bin/bash",
    )
    return {}


def term_read(lines: int = 200) -> dict:
    """
    Capture and return the last N lines from the terminal tmux pane.

    Args:
        lines: Number of lines to retrieve from the pane history.

    Returns:
        {'output': '<captured text>'}
    """

    out = subprocess.check_output(
        f"tmux capture-pane -t {TMUX_SESSION} -p -S -{lines}",
        shell=True,
        executable="/bin/bash",
        text=True,
    )
    return {"output": out}


async def shell_run(text: str, conda_env: str = None, cwd: str = None) -> dict:
    """
    Execute a shell command with optional conda environment and working directory.

    Args:
        text: Shell command to execute. Can be a simple command or a multi-line script.
        conda_env: Optional conda/micromamba environment name. If provided, the command
            runs inside this environment using 'micromamba run -n <env>'.
        cwd: Optional working directory path. If provided, the command runs from this
            directory by prepending 'cd <cwd> &&'.

    Returns:
        Dictionary with:
            - output (str): Combined stdout and stderr output
            - returncode (int): Exit code of the command (0 for success)
            - error (str): Present when returncode != 0 or an exception occurred
            - warning (str): Present when output is truncated
    """
    try:
        # If cwd is provided, prepend cd command
        if cwd:
            text = f"cd {shlex.quote(cwd)} && {text}"

        # If conda_env is provided, activate the environment
        if conda_env:
            # Use micromamba run which properly sets up the environment
            # This ensures the environment's Python and packages are used
            # We pass the command directly without wrapping in bash -c to avoid
            # nested shell issues that can cause PATH problems
            text = f"micromamba run -n {shlex.quote(conda_env)} /bin/bash -c {shlex.quote(text)}"

        proc = await asyncio.create_subprocess_shell(
            text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash",
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "output": "",
                "error": "Command timed out after 300 seconds",
                "returncode": -1,
            }

        output = (stdout.decode() if stdout else "") + (
            stderr.decode() if stderr else ""
        )
        original_length = len(output)

        # Truncate output if it exceeds 10000 characters
        truncation_warning = None
        if len(output) > 10000:
            first_part = output[:3000]
            last_part = output[-4000:]
            truncated_chars = len(output) - 7000

            output = (
                f"{first_part}\n\n"
                f"{'='*80}\n"
                f"[OUTPUT TRUNCATED: {truncated_chars} characters omitted from the middle]\n"
                f"{'='*80}\n\n"
                f"{last_part}"
            )

            truncation_warning = (
                f"WARNING: Command output was truncated ({original_length} chars total, "
                f"showing first 3000 and last 4000 chars). Consider using a more targeted command "
                f"(e.g., 'grep', 'head', 'tail', filtering, pagination) to reduce output size."
            )

        result_dict = {
            "output": output,
            "returncode": proc.returncode,
        }

        if proc.returncode != 0:
            result_dict["error"] = f"Command exited with code {proc.returncode}"

        if truncation_warning:
            result_dict["warning"] = truncation_warning

        return result_dict

    except Exception as e:
        return {
            "output": "",
            "error": str(e),
            "returncode": -1,
        }
