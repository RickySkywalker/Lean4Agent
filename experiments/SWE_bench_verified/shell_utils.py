from typing import TYPE_CHECKING, Any, Dict, Optional

from mcp_client.logger import Logger

__all__ = ["execute_command_via_shell_run", "Logger"]

if TYPE_CHECKING:
    from mcp_client.client import MCPClient


def execute_command_via_shell_run(
    mcp_client: "MCPClient",
    cmd: str,
    *,
    description: Optional[str] = None,
    logger: Optional[Logger] = None,
    allow_failure: bool = False,
    log_output: bool = True,
    conda_env: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a shell command in the sandbox and return output with exit code.

    Args:
        mcp_client: MCP client for invoking sandbox commands
        cmd: Command to execute
        description: Optional description to log
        logger: Optional logger instance
        allow_failure: If False, raises RuntimeError on non-zero exit code
        log_output: Whether to log command output
        conda_env: Optional conda environment name to run command in

    Returns:
        Dictionary with 'output', 'exit_code', and optionally 'error' keys
    """
    if description and logger:
        logger(f"  {description}")
    if logger:
        env_info = f" (in conda env: {conda_env})" if conda_env else ""
        logger(f"  Running{env_info}: {cmd}")

    # When using conda_env, micromamba run handles the shell setup
    if conda_env:
        wrapped_cmd = f"{cmd}; echo __EXIT_CODE__=$?"
    else:
        escaped_cmd = (
            cmd.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        wrapped_cmd = f'bash -lc "{escaped_cmd}"; echo __EXIT_CODE__=$?'

    # Build MCP invocation parameters
    params = {"text": wrapped_cmd}
    if conda_env:
        params["conda_env"] = conda_env

    result = mcp_client.invoke("shell_run", params)

    output_text = result.get("output", "")
    exit_code = 0

    # Extract exit code from wrapped command output
    if "__EXIT_CODE__=" in output_text:
        for line in output_text.split("\n"):
            if "__EXIT_CODE__=" in line:
                try:
                    exit_code = int(line.split("=")[1].strip())
                except (ValueError, IndexError):
                    exit_code = -1
                output_text = output_text.replace(line, "").strip()
                break

    if log_output and output_text and logger:
        logger(output_text)

    result_dict = {
        "output": output_text,
        "exit_code": exit_code,
    }

    if exit_code != 0:
        error_message = f"Command exited with code {exit_code}"
        result_dict["error"] = error_message
        if logger:
            logger(f"  {error_message}")
        if not allow_failure:
            raise RuntimeError(error_message)

    return result_dict
