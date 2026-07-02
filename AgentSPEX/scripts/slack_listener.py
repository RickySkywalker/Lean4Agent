"""
Slack Socket Mode listener for AgentSPEX.

Usage:
    python scripts/slack_listener.py
"""

import argparse
import logging
import os
import re
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import certifi
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
WORKFLOWS_ROOT = PROJECT_ROOT / "workflows"
SLACK_TEMPLATES_DIR = WORKFLOWS_ROOT / "slack_templates"
DEFAULT_WORKFLOW = SLACK_TEMPLATES_DIR / "default.yaml"

EXCLUDED_DIRS = {"modules", "__pycache__", ".git"}
slack_client = None


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

    with open(env_path, "r") as f:
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


def get_slack_tokens():
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if not bot_token or not app_token:
        vm_env = load_env_file(PROJECT_ROOT / "config" / "vm.env")
        host_env = load_env_file(PROJECT_ROOT / "config" / "host.env")

        if not bot_token:
            bot_token = vm_env.get("SLACK_BOT_TOKEN") or host_env.get("SLACK_BOT_TOKEN")
        if not app_token:
            app_token = vm_env.get("SLACK_APP_TOKEN") or host_env.get("SLACK_APP_TOKEN")

    return bot_token, app_token


def validate_tokens(bot_token: str, app_token: str) -> bool:
    errors = []

    if not bot_token:
        errors.append(
            "SLACK_BOT_TOKEN not set\n"
            "  → Run: python scripts/setup_slack.py\n"
            "  → Or manually add to config/vm.env"
        )
    elif not bot_token.startswith("xoxb-"):
        errors.append(
            f"SLACK_BOT_TOKEN has invalid format (expected xoxb-...)\n"
            f"  → Check token at: https://api.slack.com/apps"
        )

    if not app_token:
        errors.append(
            "SLACK_APP_TOKEN not set\n"
            "  → Run: python scripts/setup_slack.py\n"
            "  → Or manually add to config/vm.env"
        )
    elif not app_token.startswith("xapp-"):
        errors.append(
            f"SLACK_APP_TOKEN has invalid format (expected xapp-...)\n"
            f"  → Generate at: https://api.slack.com/apps → Basic Information → App-Level Tokens"
        )

    if errors:
        for error in errors:
            logger.error(f"ERROR: {error}")
        return False

    return True


def extract_message_text(event: dict, bot_user_id: str) -> str:
    text = event.get("text", "")
    return re.sub(rf"<@{bot_user_id}>\s*", "", text).strip()


def get_available_workflows() -> list[str]:
    return sorted(str(f.relative_to(WORKFLOWS_ROOT)) for f in _iter_workflow_files())


def resolve_workflow(name: str) -> Path | None:
    name_normalized = name.lower().strip().replace("-", "_")
    partial_match = None

    for yaml_file in _iter_workflow_files():
        rel = str(yaml_file.relative_to(WORKFLOWS_ROOT))
        stem = yaml_file.stem.lower().replace("-", "_")
        if stem == name_normalized or rel.lower().replace("-", "_") == name_normalized:
            return yaml_file
        if partial_match is None and name_normalized in stem:
            partial_match = yaml_file

    return partial_match


def parse_run_workflow_request(message: str) -> str | None:
    """Return the workflow name if the message is a run request, else None."""
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
    channel: str,
    thread_ts: str,
    log_dir: str | None = None,
):
    global slack_client

    try:
        stdout, _ = process.communicate()
        return_code = process.returncode
        if stdout:
            logger.info(f"Agent output:\n{stdout.decode(errors='replace')[-2000:]}")

        if slack_client is None:
            logger.warning("Slack client not available for completion notification")
            return

        if return_code != 0:
            message = f":x: *{task_name}* failed (exit code: {return_code})"
        elif log_dir:
            message = (
                f":white_check_mark: Workflow *{task_name}* completed successfully.\n"
                f"Results and logs: `{log_dir}/`"
            )
        else:
            # Default workflow — no completion message
            logger.info(f"Task {task_name} completed with code {return_code}")
            return

        slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=message,
        )
        logger.info(f"Task {task_name} completed with code {return_code}")

    except Exception as e:
        logger.error(f"Error in wait_and_notify: {e}")


def run_agent(
    channel: str,
    thread_ts: str,
    user_id: str,
    message_text: str,
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
    env["SLACK_CHANNEL"] = channel
    env["SLACK_THREAD_TS"] = thread_ts
    env["SLACK_USER_ID"] = user_id
    env["SLACK_MESSAGE_TEXT"] = message_text
    env["AVAILABLE_WORKFLOWS"] = ", ".join(get_available_workflows())
    env["WORKFLOWS_DIR"] = str(WORKFLOWS_ROOT)

    task_name = plan.stem
    log_dir = f"outputs/{task_name}" if workflow else None

    logger.info(f"Running agent with plan: {plan.name}")
    logger.info(f"  Channel: {channel}, Thread: {thread_ts}, User: {user_id}")
    logger.info(f"  Message: {message_text[:100]}...")

    process = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    thread = threading.Thread(
        target=wait_and_notify,
        args=(process, task_name, channel, thread_ts, log_dir),
        daemon=True,
    )
    thread.start()

    return process


def create_slack_app(bot_token: str, no_dashboard: bool):
    global slack_client

    slack_client = WebClient(token=bot_token, ssl=SSL_CONTEXT)
    app = App(token=bot_token, client=slack_client)

    bot_info = app.client.auth_test()
    bot_user_id = bot_info["user_id"]
    workspace = bot_info.get("team", "workspace")

    vm_env = load_env_file(PROJECT_ROOT / "config" / "vm.env")

    configured_name = os.environ.get("SLACK_BOT_NAME") or vm_env.get("SLACK_BOT_NAME")
    bot_name = configured_name or bot_info.get("user", "bot")

    slash_command = (
        os.environ.get("SLACK_SLASH_COMMAND")
        or vm_env.get("SLACK_SLASH_COMMAND")
        or "/agent"
    )

    logger.info(f"Connected as @{bot_name} in {workspace}")
    logger.info(f"Slash command: {slash_command}")

    def handle_request(message_text, channel, thread_ts, user_id, error_callback=None):
        plan_name = parse_run_workflow_request(message_text)
        if plan_name:
            plan_path = resolve_workflow(plan_name)
            if plan_path:
                try:
                    proc = run_agent(
                        channel=channel,
                        thread_ts=thread_ts,
                        user_id=user_id,
                        message_text=message_text,
                        no_dashboard=no_dashboard,
                        workflow=plan_path,
                    )
                    logger.info(
                        f"Workflow agent started in background (PID: {proc.pid})"
                    )
                except Exception as e:
                    logger.error(f"Error running workflow: {e}")

        try:
            process = run_agent(
                channel=channel,
                thread_ts=thread_ts,
                user_id=user_id,
                message_text=message_text,
                no_dashboard=no_dashboard,
            )
            logger.info(f"Agent started (PID: {process.pid})")
        except Exception as e:
            logger.error(f"Error running agent: {e}")
            if error_callback:
                error_callback(str(e)[:200])

    @app.event("app_mention")
    def handle_mention(event, say):
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        user_id = event.get("user")
        message_text = extract_message_text(event, bot_user_id)

        logger.info(f"Mention from <@{user_id}> in {channel}: {message_text[:50]}...")
        handle_request(
            message_text,
            channel,
            thread_ts,
            user_id,
            error_callback=lambda msg: say(text=f"Error: {msg}", thread_ts=thread_ts),
        )

    def bot_participated_in_thread(channel: str, thread_ts: str) -> bool:
        try:
            response = app.client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=100,
            )
            return any(
                msg.get("user") == bot_user_id for msg in response.get("messages", [])
            )
        except Exception as e:
            logger.debug(f"Error checking thread participation: {e}")
            return False

    @app.event("message")
    def handle_message(event, say):
        if event.get("bot_id") or event.get("subtype"):
            return

        channel = event.get("channel")
        channel_type = event.get("channel_type")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts")
        user_id = event.get("user")
        message_text = event.get("text", "")

        if f"<@{bot_user_id}>" in message_text:
            return

        if channel_type == "im":
            logger.info(f"DM from <@{user_id}>: {message_text[:50]}...")
            effective_thread_ts = thread_ts or message_ts

        elif thread_ts:
            if thread_ts == message_ts:
                return

            if not bot_participated_in_thread(channel, thread_ts):
                return

            logger.info(
                f"Thread follow-up from <@{user_id}> in {channel}: {message_text[:50]}..."
            )
            effective_thread_ts = thread_ts

        else:
            return

        handle_request(
            message_text,
            channel,
            effective_thread_ts,
            user_id,
            error_callback=lambda msg: say(
                text=f"Error: {msg}", thread_ts=effective_thread_ts
            ),
        )

    @app.command(slash_command)
    def handle_agent_command(ack, command, respond):
        ack()

        channel = command.get("channel_id")
        user_id = command.get("user_id")
        message_text = command.get("text", "")

        logger.info(
            f"{slash_command} from <@{user_id}> in {channel}: {message_text[:50]}..."
        )

        try:
            response = app.client.chat_postMessage(
                channel=channel,
                text=f"<@{user_id}> used `{slash_command}`",
            )
            thread_ts = response["ts"]
            handle_request(
                message_text,
                channel,
                thread_ts,
                user_id,
                error_callback=lambda msg: respond(f"Error: {msg}"),
            )
        except Exception as e:
            logger.error(f"Error running agent: {e}")
            respond(f"Error: {str(e)[:200]}")

    return app


def main():
    parser = argparse.ArgumentParser(
        description="Slack Socket Mode listener for AgentSPEX"
    )
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Enable dashboard for agent runs (default: disabled)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    bot_token, app_token = get_slack_tokens()
    if not validate_tokens(bot_token, app_token):
        sys.exit(1)

    if not DEFAULT_WORKFLOW.exists():
        logger.error(f"Default workflow not found: {DEFAULT_WORKFLOW}")
        logger.info("Create one at workflows/slack_templates/default.yaml")
        sys.exit(1)

    logger.info(f"Default workflow: {DEFAULT_WORKFLOW}")

    app = create_slack_app(
        bot_token=bot_token,
        no_dashboard=not args.with_dashboard,
    )

    logger.info("Starting Slack Socket Mode listener...")
    logger.info("Press Ctrl+C to stop")

    handler = SocketModeHandler(app, app_token)

    try:
        handler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Socket Mode error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
