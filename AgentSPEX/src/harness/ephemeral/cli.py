import os
import sys
from pathlib import Path

import fire

from harness.ephemeral.runner import run_ephemeral  # noqa: F401 (used by fire)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"


def _exec_script(script_name: str, *args: str):
    """Replace the current process with a script from scripts/."""
    os.execv(
        sys.executable, [sys.executable, str(_SCRIPTS_DIR / script_name)] + list(args)
    )


def run(
    workflow,
    model=None,
    output_dir=None,
    image="agentspex-sandbox:latest",
    mcp_timeout=90,
    resume=False,
    workspace_dir=None,
):
    """Run a YAML workflow in an ephemeral sandbox container.

    Args:
        workflow: Path to the YAML workflow file.
        model: LLM model override (e.g. gpt-4o). Defaults to value in YAML or gpt-4.1-mini.
        output_dir: Output directory. Defaults to outputs/<task_name>.
        image: Docker image name. Defaults to agentspex-sandbox:latest.
        mcp_timeout: Seconds to wait for sandbox MCP server to start. Defaults to 90.
        resume: Resume from an existing checkpoint.
        workspace_dir: Host directory mounted as /workspace in the container. Defaults to ./workspace.
    """
    run_ephemeral(
        workflow_file=workflow,
        model=model,
        output_dir=output_dir,
        image=image,
        mcp_timeout=mcp_timeout,
        resume=resume,
        workspace_dir=workspace_dir,
    )


# ── setup ─────────────────────────────────────────────────────────────────────


def _setup_slack():
    """Interactive setup wizard for the Slack integration."""
    _exec_script("setup_slack.py")


def _setup_discord():
    """Interactive setup wizard for the Discord integration."""
    _exec_script("setup_discord.py")


# ── listen ────────────────────────────────────────────────────────────────────


def _listen_slack(with_dashboard=False, debug=False):
    """Start the Slack Socket Mode listener.

    Args:
        with_dashboard: Enable the real-time dashboard (default: off).
        debug: Enable verbose logging.
    """
    args = []
    if with_dashboard:
        args.append("--with-dashboard")
    if debug:
        args.append("--debug")
    _exec_script("slack_listener.py", *args)


def _listen_discord(with_dashboard=False, debug=False):
    """Start the Discord bot listener.

    Args:
        with_dashboard: Enable the real-time dashboard (default: off).
        debug: Enable verbose logging.
    """
    args = []
    if with_dashboard:
        args.append("--with-dashboard")
    if debug:
        args.append("--debug")
    _exec_script("discord_listener.py", *args)


# ── entry point ───────────────────────────────────────────────────────────────


def cli(
    model="claude-sonnet-4-5",
    mcp_url="http://localhost:7002/mcp",
    output_dir="outputs/agentic_loop",
    temperature=0.2,
):
    """Run the agentic loop against a running sandbox VM.

    Args:
        model: LLM model to use. Defaults to claude-sonnet-4-5.
        mcp_url: MCP server URL. Defaults to http://localhost:7002/mcp.
        output_dir: Output directory. Defaults to outputs/agentic_loop.
        temperature: LLM sampling temperature. Defaults to 0.2.
    """
    from harness.agentic_loop.run_loop import run_loop

    run_loop(
        model=model,
        mcp_url=mcp_url,
        output_dir=output_dir,
        temperature=temperature,
    )


def main():
    if len(sys.argv) == 1:
        from harness.ephemeral.repl import launch_repl

        launch_repl()
        return

    fire.Fire(
        {
            "run": run,
            "cli": cli,
            "setup": {
                "slack": _setup_slack,
                "discord": _setup_discord,
            },
            "listen": {
                "slack": _listen_slack,
                "discord": _listen_discord,
            },
        }
    )


if __name__ == "__main__":
    main()
