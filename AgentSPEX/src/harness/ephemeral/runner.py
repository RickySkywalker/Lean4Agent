import os
import socket
import subprocess
import time
import types
from pathlib import Path

import requests
from dotenv import dotenv_values, find_dotenv, load_dotenv

from harness.agent import AgentSPEX
from harness.run import apply_yaml_config_fallback, load_yaml_config

_PROJECT_ROOT = Path(__file__).parents[3]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _ensure_image(image: str, dockerfile: Path) -> None:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"Image '{image}' not found. Building from {dockerfile} ...")
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                image,
                "-f",
                str(dockerfile),
                str(dockerfile.parent.parent),
            ],
            check=True,
        )


def _wait_for_mcp(
    url: str, container_name: str, timeout: int = 90, poll_interval: float = 1.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            requests.get(url, timeout=2)
            return  # any HTTP response means the server is up
        except requests.exceptions.ConnectionError:
            time.sleep(poll_interval)
    raise TimeoutError(
        f"MCP server at {url} did not become ready within {timeout}s.\n"
        f"Run: docker logs {container_name} to check for startup errors."
    )


class EphemeralSandbox:
    def __init__(
        self,
        image: str = "agentspex-sandbox:latest",
        env_file: Path | None = None,
        dockerfile: Path | None = None,
        workspace_dir: Path | None = None,
        mcp_timeout: int = 90,
    ):
        self.image = image
        self.env_file = env_file or _PROJECT_ROOT / "config" / "vm.env"
        self.dockerfile = dockerfile or _PROJECT_ROOT / "config" / "Dockerfile"
        self.workspace_dir = workspace_dir or Path.cwd() / "workspace"
        self.mcp_timeout = mcp_timeout
        self._container_name = f"sandbox-ephemeral-{os.getpid()}"
        self._host_port: int | None = None
        self.mcp_url: str | None = None

    def __enter__(self) -> "EphemeralSandbox":
        _ensure_image(self.image, self.dockerfile)

        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._host_port = _find_free_port()

        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self._container_name,
            "--hostname",
            "sandbox",
            "-v",
            f"{self.workspace_dir.resolve()}:/workspace:rw",
            "--env-file",
            str(self.env_file),
            "-p",
            f"{self._host_port}:7002",
        ]

        # Forward all keys defined in .env (with their current environment values)
        dotenv_path = find_dotenv()
        for key in dotenv_values(dotenv_path):
            value = os.environ.get(key)
            if value:
                cmd += ["-e", f"{key}={value}"]

        cmd.append(self.image)
        subprocess.run(cmd, check=True)

        self.mcp_url = f"http://localhost:{self._host_port}/mcp"
        print(f"Waiting for sandbox to start on {self.mcp_url} ...")
        _wait_for_mcp(self.mcp_url, self._container_name, self.mcp_timeout)
        print("Sandbox ready.")
        return self

    def __exit__(self, *_) -> None:
        print("Stopping sandbox container ...")
        subprocess.run(
            ["docker", "stop", self._container_name],
            capture_output=True,  # best-effort, don't surface errors
        )


def build_agent_args(
    workflow_file: str,
    model: str | None = None,
    output_dir: str | None = None,
    mcp_url: str | None = None,
    resume: bool = False,
) -> types.SimpleNamespace:
    """Build a standard agent args namespace with YAML config fallback applied."""
    yaml_config = load_yaml_config(workflow_file)
    args = types.SimpleNamespace(
        workflow_file=workflow_file,
        mode="simple",
        model=model,
        max_tokens_per_step=None,
        max_tool_calls_per_step=None,
        temperature=None,
        plan_revision_max_steps=None,
        model_kwargs=None,
        output_dir=output_dir,
        resume=resume,
        checkpoint_path=None,
        trace_path=None,
        replay_trace=None,
        mcp_url=mcp_url,
    )
    apply_yaml_config_fallback(args, yaml_config)
    return args


def run_ephemeral(
    workflow_file: str,
    model: str | None = None,
    output_dir: str | None = None,
    image: str = "agentspex-sandbox:latest",
    mcp_timeout: int = 90,
    resume: bool = False,
    workspace_dir: str | None = None,
) -> None:
    load_dotenv(find_dotenv(), override=True)

    workspace = Path(workspace_dir) if workspace_dir else None

    yaml_config = load_yaml_config(workflow_file)

    args = types.SimpleNamespace(
        workflow_file=workflow_file,
        mode="simple",
        model=model,
        max_tokens_per_step=None,
        max_tool_calls_per_step=None,
        temperature=None,
        plan_revision_max_steps=None,
        model_kwargs=None,
        output_dir=output_dir,
        resume=resume,
        checkpoint_path=None,
        trace_path=None,
        replay_trace=None,
        mcp_url=None,  # filled in below
    )
    apply_yaml_config_fallback(args, yaml_config)

    with EphemeralSandbox(
        image=image, mcp_timeout=mcp_timeout, workspace_dir=workspace
    ) as sandbox:
        args.mcp_url = sandbox.mcp_url
        agent = AgentSPEX(mcp_url=args.mcp_url)
        agent.run(args)


def run_ephemeral_loop(
    model: str | None = None,
    output_dir: str | None = None,
    image: str = "agentspex-sandbox:latest",
    mcp_timeout: int = 90,
    workspace_dir: str | None = None,
) -> None:
    """Run the interactive agentic loop in an ephemeral sandbox container."""
    from harness.agentic_loop.run_loop import run_loop

    load_dotenv(find_dotenv(), override=True)
    workspace = Path(workspace_dir) if workspace_dir else None

    with EphemeralSandbox(
        image=image, mcp_timeout=mcp_timeout, workspace_dir=workspace
    ) as sandbox:
        run_loop(
            model=model or "claude-sonnet-4-5",
            mcp_url=sandbox.mcp_url,
            output_dir=output_dir or "outputs/agentic_loop",
        )
