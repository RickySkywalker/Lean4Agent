"""Interactive REPL for AgentSPEX.

Launch with `agentspex` (no subcommand). Uses arrow-key menus via InquirerPy.
Config is persisted at ~/.agentspex/config.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import dotenv_values
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS_DIR = _PROJECT_ROOT / "workflows"
_DEMO_DIR = _PROJECT_ROOT / "demo"
_DOCS_DIR = _PROJECT_ROOT / "docs"
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
_CONFIG_PATH = Path.home() / ".agentspex" / "config.json"

_VM_EPHEMERAL = "ephemeral"
_VM_PERSISTENT = "persistent"

_MODEL_COMPLETIONS_FALLBACK = [
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-5",
    "o3",
    "o4-mini",
]

_MODEL_COMPLETIONS: list[str] | None = None


def _get_model_completions() -> list[str]:
    global _MODEL_COMPLETIONS
    if _MODEL_COMPLETIONS is not None:
        return _MODEL_COMPLETIONS
    try:
        import litellm

        provider_map = getattr(litellm, "models_by_provider", {})
        anthropic = sorted(provider_map.get("anthropic", []))
        openai_all = sorted(provider_map.get("openai", []))
        # Filter OpenAI to chat/text models only (exclude image, audio, embedding)
        openai = [
            m
            for m in openai_all
            if m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-4o"))
            and not any(x in m for x in ("audio", "vision", "instruct", "dall-e"))
        ]
        _MODEL_COMPLETIONS = anthropic + openai
    except Exception:
        _MODEL_COMPLETIONS = _MODEL_COMPLETIONS_FALLBACK
    return _MODEL_COMPLETIONS


_DOC_DESCRIPTIONS = {
    "workflow-language.md": "Full workflow syntax — step types, variables, control flow",
    "computer-use-tools.md": "Visual browser automation with Set-of-Marks mode",
    "integration-slack.md": "Slack bot integration setup and usage",
    "integration-discord.md": "Discord bot integration setup and usage",
}

console = Console()


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "vm_mode": _VM_EPHEMERAL,
        "default_model": None,
        "docker_image": "agentspex-sandbox:latest",
    }


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def _read_yaml_meta(path: Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "workflow" not in data:
            return {}
        return {"name": data.get("name", path.stem), "goal": data.get("goal", "")}
    except (OSError, yaml.YAMLError):
        return {}


def _collect_workflows() -> list[dict]:
    """Scan workflows/ and demo/*/ for runnable YAML workflows."""
    results = []

    if _WORKFLOWS_DIR.exists():
        for p in sorted(_WORKFLOWS_DIR.glob("*.yaml")):
            meta = _read_yaml_meta(p)
            if meta:
                results.append({**meta, "path": p, "source": "workflows/"})

    if _DEMO_DIR.exists():
        for demo_dir in sorted(d for d in _DEMO_DIR.iterdir() if d.is_dir()):
            for p in sorted(demo_dir.glob("*.yaml")):
                meta = _read_yaml_meta(p)
                if meta:
                    results.append(
                        {**meta, "path": p, "source": f"demo/{demo_dir.name}/"}
                    )

    return results


def _persistent_mcp_url() -> str:
    env = dotenv_values(_PROJECT_ROOT / "config" / "vm.env")
    port = env.get("MCP_PORT", "7002")
    basepath = env.get("MCP_BASEPATH", "/mcp")
    return f"http://localhost:{port}{basepath}"


def _is_vm_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", "sandbox"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _exec_script(script_name: str, *args: str) -> None:
    os.execv(
        sys.executable, [sys.executable, str(_SCRIPTS_DIR / script_name)] + list(args)
    )


def _run_workflow_flow(cfg: dict) -> None:
    workflows = _collect_workflows()
    if not workflows:
        console.print(
            "[yellow]No workflow YAML files found in workflows/ or demo/.[/yellow]"
        )
        return

    choices = [
        Choice(
            name=f"[{w['source']}] {w['name']}  —  {w['goal'][:70]}{'…' if len(w.get('goal', '')) > 70 else ''}",
            value=w,
        )
        for w in workflows
    ]
    choices.append(Choice(name="← Back", value=None))

    selected = inquirer.select("Select a workflow:", choices=choices).execute()
    if not selected:
        return

    console.print(f"\n  [bold]{selected['name']}[/bold]")
    if selected.get("goal"):
        console.print(f"  [dim]{selected['goal']}[/dim]\n")

    model = inquirer.fuzzy(
        "Model override (default: workflow model) — choose a non-deprecated model:",
        choices=["", *_get_model_completions()],
        default=cfg.get("default_model") or "",
        max_height=5,
        mandatory=False,
    ).execute()
    if model is None:
        return

    resume = inquirer.confirm(
        "Resume from existing checkpoint?", default=False
    ).execute()
    if resume is None:
        return

    vm_mode = cfg.get("vm_mode", _VM_EPHEMERAL)
    console.print(f"\n[green]Starting in {vm_mode} mode…[/green]\n")

    if vm_mode == _VM_EPHEMERAL:
        from harness.ephemeral.runner import run_ephemeral

        run_ephemeral(
            workflow_file=str(selected["path"]),
            model=model or None,
            image=cfg.get("docker_image", "agentspex-sandbox:latest"),
            resume=resume,
        )
    else:
        if not _is_vm_running():
            start = inquirer.confirm(
                "Sandbox VM is not running. Start it now?", default=True
            ).execute()
            if not start:
                return
            console.print("[yellow]Starting sandbox VM…[/yellow]")
            subprocess.run(
                ["bash", str(_SCRIPTS_DIR / "run_vm.sh"), "start"], check=True
            )

        from dotenv import find_dotenv, load_dotenv

        from harness.agent import AgentSPEX
        from harness.ephemeral.runner import build_agent_args

        load_dotenv(find_dotenv(), override=True)
        mcp_url = _persistent_mcp_url()
        args = build_agent_args(
            workflow_file=str(selected["path"]),
            model=model or None,
            mcp_url=mcp_url,
            resume=resume,
        )
        AgentSPEX(mcp_url=mcp_url).run(args)


_TASK_PLAN_GUIDE = """\
# Writing a Task Plan

Workflows are YAML files saved in `workflows/`. A minimal example:

```yaml
name: my_task
goal: Describe what this workflow accomplishes

config:
  model: gpt-4.1-mini   # optional — this is the default

workflow:
  - task:
      name: main
      instruction: |
        Your instruction to the agent here.
```

## Step types

- **task** — stateless; fresh context each run. Use for one-shot instructions.
- **step** — stateful; persists `conversation_history` across turns. Use for multi-turn dialogue.

## Common patterns

```yaml
# Save output to a variable
  - task:
      name: research
      instruction: "Research {{topic}} and summarize findings."
      save_as: summary

# Loop over a list
  - for_each:
      name: process_items
      items: "{{item_list}}"
      as: item
      steps:
        - task:
            name: handle
            instruction: "Process this item: {{item}}"

# Conditional
  - conditional:
      name: check_result
      condition: "{{score}} > 0.8"
      if_true:
        - task:
            name: pass
            instruction: "Report success."
      if_false:
        - task:
            name: fail
            instruction: "Report failure."
```

## Template variables

Use `{{variable_name}}` anywhere in instructions. Dotted access works: `{{result.status.code}}`.

## Full reference

See `docs/workflow-language.md` for the complete syntax (View docs → workflow-language.md).
"""


def _write_task_plan_flow() -> None:
    console.print(Markdown(_TASK_PLAN_GUIDE))


def _view_docs_flow() -> None:
    docs = sorted(_DOCS_DIR.glob("*.md")) if _DOCS_DIR.exists() else []
    if not docs:
        console.print("[yellow]No docs found in docs/.[/yellow]")
        return

    choices = [
        Choice(name=f"{p.name}  —  {_DOC_DESCRIPTIONS.get(p.name, '')}", value=p)
        for p in docs
    ]
    choices.append(Choice(name="← Back", value=None))

    selected = inquirer.select("Select a document:", choices=choices).execute()
    if not selected:
        return

    try:
        content = selected.read_text()
    except OSError as e:
        console.print(f"[red]Could not read file: {e}[/red]")
        return

    console.print(Markdown(content))


def _integrations_flow() -> None:
    dispatch = {
        "Setup Slack": lambda: _exec_script("setup_slack.py"),
        "Setup Discord": lambda: _exec_script("setup_discord.py"),
        "Listen on Slack": lambda: _exec_script(
            "slack_listener.py",
            *(
                ["--with-dashboard"]
                if inquirer.confirm("Enable live dashboard?", default=False).execute()
                else []
            ),
        ),
        "Listen on Discord": lambda: _exec_script(
            "discord_listener.py",
            *(
                ["--with-dashboard"]
                if inquirer.confirm("Enable live dashboard?", default=False).execute()
                else []
            ),
        ),
    }

    while True:
        choice = inquirer.select(
            "Integrations:",
            choices=[*dispatch.keys(), "← Back"],
        ).execute()

        if choice == "← Back" or choice is None:
            break
        dispatch[choice]()


def _vm_flow() -> None:
    while True:
        try:
            is_running = _is_vm_running()
        except FileNotFoundError:
            console.print("[yellow]Docker not found — is it installed?[/yellow]")
            return

        status = "[green]running[/green]" if is_running else "[red]stopped[/red]"
        console.print(f"\n  Sandbox VM: {status}")

        choice = inquirer.select(
            "Sandbox VM:",
            choices=(
                ["Stop VM", "Rebuild sandbox", "← Back"]
                if is_running
                else ["Start VM", "Rebuild sandbox", "← Back"]
            ),
        ).execute()

        if choice == "Start VM":
            console.print("[yellow]Starting sandbox VM…[/yellow]")
            subprocess.run(["bash", str(_SCRIPTS_DIR / "run_vm.sh"), "start"])
        elif choice == "Stop VM":
            if inquirer.confirm(
                "Stop and remove the sandbox VM?", default=False
            ).execute():
                subprocess.run(["bash", str(_SCRIPTS_DIR / "run_vm.sh"), "stop"])
        elif choice == "Rebuild sandbox":
            console.print("[yellow]Rebuilding sandbox image…[/yellow]")
            subprocess.run(
                [
                    "docker",
                    "build",
                    "-t",
                    "agentspex-sandbox:latest",
                    "-f",
                    "config/Dockerfile",
                    ".",
                ]
            )
        elif choice == "← Back" or choice is None:
            break


def _settings_flow(cfg: dict) -> None:
    while True:
        vm_mode = cfg.get("vm_mode", _VM_EPHEMERAL)
        model_label = cfg.get("default_model") or "(workflow default)"
        image = cfg.get("docker_image", "agentspex-sandbox:latest")

        choice = inquirer.select(
            "Settings:",
            choices=[
                Choice(name=f"VM mode          {vm_mode}", value="vm_mode"),
                Choice(name=f"Default model    {model_label}", value="default_model"),
                Choice(name=f"Docker image     {image}", value="docker_image"),
                Choice(name="← Back", value=None),
            ],
        ).execute()

        if choice is None:
            break
        elif choice == "vm_mode":
            new_mode = inquirer.select(
                "VM mode:",
                choices=[
                    Choice(
                        name="ephemeral  — spin up/down a container per run",
                        value=_VM_EPHEMERAL,
                    ),
                    Choice(
                        name="persistent — connect to a long-lived container",
                        value=_VM_PERSISTENT,
                    ),
                ],
            ).execute()
            if new_mode:
                cfg["vm_mode"] = new_mode
                _save_config(cfg)
        elif choice == "default_model":
            new_model = inquirer.text(
                "Default model (blank = use each workflow's default):",
                default=cfg.get("default_model") or "",
            ).execute()
            if new_model is not None:
                cfg["default_model"] = new_model or None
                _save_config(cfg)
        elif choice == "docker_image":
            new_image = inquirer.text("Docker image:", default=image).execute()
            if new_image:
                cfg["docker_image"] = new_image
                _save_config(cfg)


def _run_agent_flow(cfg: dict) -> None:
    model = inquirer.fuzzy(
        "Model override (default: claude-sonnet-4-5) — choose a non-deprecated model:",
        choices=["", *_get_model_completions()],
        default=cfg.get("default_model") or "",
        max_height=5,
        mandatory=False,
    ).execute()
    if model is None:
        return

    vm_mode = cfg.get("vm_mode", _VM_EPHEMERAL)
    console.print(f"\n[green]Starting agent in {vm_mode} mode…[/green]")
    console.print("[dim]Type your tasks at the prompt.[/dim]\n")

    if vm_mode == _VM_EPHEMERAL:
        from harness.ephemeral.runner import run_ephemeral_loop

        run_ephemeral_loop(
            model=model or None,
            image=cfg.get("docker_image", "agentspex-sandbox:latest"),
        )
    else:
        if not _is_vm_running():
            start = inquirer.confirm(
                "Sandbox VM is not running. Start it now?", default=True
            ).execute()
            if not start:
                return
            console.print("[yellow]Starting sandbox VM…[/yellow]")
            subprocess.run(
                ["bash", str(_SCRIPTS_DIR / "run_vm.sh"), "start"], check=True
            )

        from harness.agentic_loop.run_loop import run_loop

        run_loop(
            model=model or "claude-sonnet-4-5",
            mcp_url=_persistent_mcp_url(),
        )


def _dashboard_flow(_cfg: dict) -> None:
    console.print("\n[green]Starting dashboard…[/green]")
    console.print("[dim]The dashboard will open in your browser automatically.[/dim]")
    console.print(
        "[dim]Press [bold]Ctrl-C[/bold] in this terminal to stop the dashboard and return to the menu.[/dim]\n"
    )
    try:
        subprocess.run(
            [sys.executable, str(_SCRIPTS_DIR / "dashboard.py")],
        )
    except KeyboardInterrupt:
        pass


_MENU_DISPATCH = {
    "Run a workflow": _run_workflow_flow,
    "Start agent": _run_agent_flow,
    "Write a task plan": lambda _: _write_task_plan_flow(),
    "Set up an integration": lambda _: _integrations_flow(),
    "Manage sandbox": lambda _: _vm_flow(),
    "View dashboard": _dashboard_flow,
    "Settings": _settings_flow,
}


def launch_repl() -> None:
    cfg = _load_config()

    console.print(
        Panel(
            "[bold cyan]AgentSPEX[/bold cyan]  —  Declarative AI workflow platform\n"
            "[dim]Arrow keys to navigate · Enter to select · Ctrl-C to quit[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    while True:
        try:
            console.print(f"[dim]VM: {cfg.get('vm_mode', _VM_EPHEMERAL)}[/dim]")
            choice = inquirer.select(
                "What would you like to do?",
                choices=[*_MENU_DISPATCH.keys(), "Quit"],
            ).execute()
        except KeyboardInterrupt:
            break

        if choice is None or choice == "Quit":
            break

        try:
            _MENU_DISPATCH[choice](cfg)
        except KeyboardInterrupt:
            pass

    console.print("\n[dim]Goodbye.[/dim]")
