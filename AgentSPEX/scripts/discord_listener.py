"""
Discord bot listener.

Usage:
    python scripts/discord_listener.py

Setup:
    python scripts/setup_discord.py
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import discord
from discord import app_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
WORKFLOWS_ROOT = PROJECT_ROOT / "workflows"
DISCORD_TEMPLATES_DIR = WORKFLOWS_ROOT / "discord_templates"
DEFAULT_WORKFLOW = DISCORD_TEMPLATES_DIR / "default.yaml"

EXCLUDED_DIRS = {"modules", "__pycache__", ".git"}


def _iter_workflow_files():
    if not WORKFLOWS_ROOT.exists():
        return
    for yaml_file in WORKFLOWS_ROOT.rglob("*.yaml"):
        if any(excluded in yaml_file.parts for excluded in EXCLUDED_DIRS):
            continue
        if yaml_file.stem == "manifest":
            continue
        yield yaml_file


def load_env_file(env_path: Path) -> dict:
    env_vars = {}
    if not env_path.exists():
        return env_vars
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    env_vars[key] = value
    return env_vars


def get_discord_token() -> str | None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        vm_env = load_env_file(PROJECT_ROOT / "config" / "vm.env")
        host_env = load_env_file(PROJECT_ROOT / "config" / "host.env")
        token = vm_env.get("DISCORD_BOT_TOKEN") or host_env.get("DISCORD_BOT_TOKEN")
    return token


def get_slash_command_name() -> str:
    name = os.environ.get("DISCORD_SLASH_COMMAND")
    if not name:
        vm_env = load_env_file(PROJECT_ROOT / "config" / "vm.env")
        name = vm_env.get("DISCORD_SLASH_COMMAND", "agent")
    return name.lstrip("/")


def get_available_workflows() -> list[str]:
    return sorted(str(f.relative_to(WORKFLOWS_ROOT)) for f in _iter_workflow_files())


def resolve_workflow(name: str) -> Path | None:
    name_normalized = name.lower().strip().replace("-", "_")
    partial_match = None
    for yaml_file in _iter_workflow_files():
        stem = yaml_file.stem.lower().replace("-", "_")
        rel = str(yaml_file.relative_to(WORKFLOWS_ROOT))
        if stem == name_normalized or rel.lower().replace("-", "_") == name_normalized:
            return yaml_file
        if partial_match is None and name_normalized in stem:
            partial_match = yaml_file
    return partial_match


def parse_run_workflow_request(message: str) -> str | None:
    msg_lower = message.lower().strip()
    if not any(kw in msg_lower for kw in ("run", "execute", "start", "launch")):
        return None
    for plan_rel_path in get_available_workflows():
        stem = Path(plan_rel_path).stem.lower().replace("-", "_")
        original = Path(plan_rel_path).stem.lower()
        if stem in msg_lower.replace("-", "_") or original in msg_lower:
            return Path(plan_rel_path).stem
    return None


def wait_and_notify(
    process: subprocess.Popen,
    task_name: str,
    client: discord.Client,
    channel_id: str,
    message_id: str,
    log_dir: str | None = None,
):
    """Wait for the agent subprocess to finish and post a completion notice to Discord."""
    try:
        stdout, _ = process.communicate()
        return_code = process.returncode
        if stdout:
            logger.info(f"Agent output:\n{stdout.decode(errors='replace')[-2000:]}")

        if return_code != 0:
            text = f":x: **{task_name}** failed (exit code: {return_code})"
        elif log_dir:
            text = (
                f":white_check_mark: Workflow **{task_name}** completed successfully.\n"
                f"Results and logs: `{log_dir}/`"
            )
        else:
            # Default workflow — no completion message (the agent replies inline)
            logger.info(f"Task {task_name} completed with code {return_code}")
            return

        async def _send():
            try:
                channel = await client.fetch_channel(int(channel_id))
                ref = discord.MessageReference(
                    message_id=int(message_id),
                    channel_id=int(channel_id),
                    fail_if_not_exists=False,
                )
                await channel.send(text, reference=ref)
            except Exception as e:
                logger.error(f"Failed to send Discord completion notice: {e}")

        asyncio.run_coroutine_threadsafe(_send(), client.loop)
        logger.info(f"Task {task_name} completed with code {return_code}")

    except Exception as e:
        logger.error(f"Error in wait_and_notify: {e}")


def run_agent(
    channel_id: str,
    message_id: str,
    user_id: str,
    message_text: str,
    client: discord.Client,
    no_dashboard: bool = True,
    workflow: Path | None = None,
) -> subprocess.Popen:
    plan = workflow or DEFAULT_WORKFLOW
    run_agent_script = SCRIPT_DIR / "run_agent.sh"

    if not run_agent_script.exists():
        raise FileNotFoundError(f"run_agent.sh not found at {run_agent_script}")
    if not plan.exists():
        raise FileNotFoundError(f"Workflow not found at {plan}")

    cmd = [str(run_agent_script), str(plan)]
    if no_dashboard:
        cmd.append("--no_dashboard")

    env = os.environ.copy()
    env["DISCORD_CHANNEL_ID"] = channel_id
    env["DISCORD_MESSAGE_ID"] = message_id
    env["DISCORD_USER_ID"] = user_id
    env["DISCORD_MESSAGE_TEXT"] = message_text
    env["AVAILABLE_WORKFLOWS"] = ", ".join(get_available_workflows())
    env["WORKFLOWS_DIR"] = str(WORKFLOWS_ROOT)

    task_name = plan.stem
    log_dir = f"outputs/{task_name}" if workflow else None

    logger.info(f"Running agent with plan: {plan.name}")
    logger.info(f"  Channel: {channel_id}, Message: {message_id}, User: {user_id}")
    logger.info(f"  Message: {message_text[:100]}...")

    process = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    threading.Thread(
        target=wait_and_notify,
        args=(process, task_name, client, channel_id, message_id, log_dir),
        daemon=True,
    ).start()

    return process


def create_bot(no_dashboard: bool, slash_command_name: str) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready():
        # Sync to each guild immediately (instant), then global sync (up to 1hr)
        synced_guilds = []
        for guild in client.guilds:
            await tree.sync(guild=guild)
            synced_guilds.append(guild.name)
        await tree.sync()
        logger.info(f"Connected as {client.user} (ID: {client.user.id})")
        if synced_guilds:
            logger.info(
                f"Slash command /{slash_command_name} synced instantly to: {', '.join(synced_guilds)}"
            )
        logger.info(
            f"Slash command /{slash_command_name} queued for global sync (up to 1hr)"
        )

    def _handle_request(
        channel_id: str, message_id: str, user_id: str, message_text: str
    ):
        plan_name = parse_run_workflow_request(message_text)
        if plan_name:
            plan_path = resolve_workflow(plan_name)
            if plan_path:
                try:
                    proc = run_agent(
                        channel_id=channel_id,
                        message_id=message_id,
                        user_id=user_id,
                        message_text=message_text,
                        client=client,
                        no_dashboard=no_dashboard,
                        workflow=plan_path,
                    )
                    logger.info(f"Workflow agent started (PID: {proc.pid})")
                except Exception as e:
                    logger.error(f"Error running workflow: {e}")

        try:
            process = run_agent(
                channel_id=channel_id,
                message_id=message_id,
                user_id=user_id,
                message_text=message_text,
                client=client,
                no_dashboard=no_dashboard,
            )
            logger.info(f"Agent started (PID: {process.pid})")
        except Exception as e:
            logger.error(f"Error running agent: {e}")
            asyncio.run_coroutine_threadsafe(
                _send_error(client, channel_id, message_id, str(e)[:200]),
                client.loop,
            )

    async def _send_error(
        client: discord.Client, channel_id: str, message_id: str, error: str
    ):
        try:
            channel = await client.fetch_channel(int(channel_id))
            ref = discord.MessageReference(
                message_id=int(message_id),
                channel_id=int(channel_id),
                fail_if_not_exists=False,
            )
            await channel.send(f":x: Error: {error}", reference=ref)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    @client.event
    async def on_message(message: discord.Message):
        if message.author == client.user:
            return

        channel_id = str(message.channel.id)
        message_id = str(message.id)
        user_id = str(message.author.id)

        # DMs
        if isinstance(message.channel, discord.DMChannel):
            logger.info(f"DM from {message.author}: {message.content[:50]}...")
            _handle_request(channel_id, message_id, user_id, message.content)
            return

        # Mentions in guild channels
        if client.user in message.mentions:
            text = message.content.replace(f"<@{client.user.id}>", "").strip()
            logger.info(
                f"Mention from {message.author} in #{message.channel}: {text[:50]}..."
            )
            _handle_request(channel_id, message_id, user_id, text)
            return

        # Thread follow-ups: respond if the bot has posted in this thread before
        if isinstance(message.channel, discord.Thread):
            async for thread_message in message.channel.history(limit=50):
                if thread_message.author == client.user:
                    logger.info(
                        f"Thread follow-up from {message.author} in thread "
                        f"'{message.channel.name}': {message.content[:50]}..."
                    )
                    _handle_request(channel_id, message_id, user_id, message.content)
                    return

    @tree.command(name=slash_command_name, description="Run an agent task")
    @app_commands.describe(task="What you'd like the agent to do")
    async def agent_command(interaction: discord.Interaction, task: str):
        await interaction.response.defer(ephemeral=False)
        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)

        sent = await interaction.followup.send(
            f"<@{interaction.user.id}> used `/{slash_command_name}`: {task}"
        )
        message_id = str(sent.id)

        logger.info(f"/{slash_command_name} from {interaction.user}: {task[:50]}...")
        _handle_request(channel_id, message_id, user_id, task)

    return client


def main():
    parser = argparse.ArgumentParser(description="Discord bot listener for AgentSPEX")
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Enable dashboard for agent runs (default: disabled)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    token = get_discord_token()
    if not token:
        logger.error(
            "DISCORD_BOT_TOKEN not set.\n"
            "  → Run: python scripts/setup_discord.py\n"
            "  → Or manually add DISCORD_BOT_TOKEN to config/vm.env"
        )
        sys.exit(1)

    if not DEFAULT_WORKFLOW.exists():
        logger.error(f"Default workflow not found: {DEFAULT_WORKFLOW}")
        logger.info("Create one at workflows/discord_templates/default.yaml")
        sys.exit(1)

    slash_command_name = get_slash_command_name()
    logger.info(f"Default workflow: {DEFAULT_WORKFLOW}")
    logger.info("Starting Discord bot...")
    logger.info("Press Ctrl+C to stop")

    bot = create_bot(
        no_dashboard=not args.with_dashboard,
        slash_command_name=slash_command_name,
    )

    try:
        bot.run(token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except discord.errors.DiscordServerError as e:
        logger.error(
            f"Could not connect to Discord ({e}).\n"
            "  This is usually caused by a local proxy intercepting the connection.\n"
            "  → Check if Proxyman, Charles, or another proxy tool is running and\n"
            "    add discord.com / gateway.discord.gg to its exclusion list,\n"
            "    or temporarily disable it and retry."
        )
        sys.exit(1)
    except discord.errors.PrivilegedIntentsRequired:
        logger.error(
            "MESSAGE CONTENT intent is not enabled.\n"
            "  → Go to https://discord.com/developers/applications\n"
            "  → Select your app → Bot → Privileged Gateway Intents\n"
            "  → Enable 'MESSAGE CONTENT INTENT' and click Save Changes\n"
            "  → Then re-run: agentspex listen discord"
        )
        sys.exit(1)
    except discord.LoginFailure:
        logger.error(
            "Invalid DISCORD_BOT_TOKEN — check your token at "
            "https://discord.com/developers/applications"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
