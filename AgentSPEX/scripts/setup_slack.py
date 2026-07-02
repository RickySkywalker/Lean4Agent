"""
Interactive Slack setup wizard.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
VM_ENV_PATH = PROJECT_ROOT / "config" / "vm.env"
MANIFEST_PATH = PROJECT_ROOT / "config" / "slack_manifest.json"


def print_box(lines: list[str], title: str = "", width: int = 80 - 4):
    print("┌" + "─" * width + "┐")
    if title:
        print(f"│  {title:<{width-4}}  │")
        print("├" + "─" * width + "┤")
    for line in lines:
        for subline in line.split("\n"):
            print(f"│  {subline:<{width-4}}  │")
    print("└" + "─" * width + "┘")


def print_success(text: str):
    """Print success message."""
    print(f"  ✓ {text}")


def print_error(text: str):
    """Print error message."""
    print(f"  ✗ {text}")


def print_info(text: str):
    """Print info message."""
    print(f"  → {text}")


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using pyperclip."""
    import pyperclip

    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException:
        return False


def validate_bot_name(name: str) -> tuple[bool, str]:
    """Validate bot name for Slack app naming constraints."""
    if len(name) < 2:
        return False, "Name must be at least 2 characters"
    if len(name) > 35:
        return False, "Name must be 35 characters or fewer (Slack limit)"
    invalid_chars = set("<>&\"'`")
    found = [c for c in name if c in invalid_chars]
    if found:
        return False, f"Name contains invalid characters: {' '.join(found)}"
    return True, ""


def make_bot_display_name(name: str) -> str:
    """Convert a bot name to a display name (spaces to hyphens)."""
    return name.strip().replace(" ", "-")


def make_slash_command(display_name: str) -> str:
    """Derive a slash command from the display name. e.g. 'Sandbox-Agent' -> '/sandbox-agent'."""
    cmd = re.sub(r"[^a-z0-9-]", "", display_name.lower().replace(" ", "-"))
    return f"/{cmd}"


def get_existing_bot_name() -> str | None:
    """Read SLACK_BOT_NAME from vm.env if it exists."""
    if not VM_ENV_PATH.exists():
        return None
    with open(VM_ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SLACK_BOT_NAME="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value if value else None
    return None


def customize_manifest(
    manifest_str: str, app_name: str, display_name: str, slash_command: str
) -> str:
    """Customize the manifest template with the chosen bot name and command."""
    manifest = json.loads(manifest_str)
    manifest["display_information"]["name"] = app_name
    manifest["features"]["bot_user"]["display_name"] = display_name
    for cmd in manifest.get("features", {}).get("slash_commands", []):
        if cmd.get("command") == "/agent":
            cmd["command"] = slash_command
    return json.dumps(manifest, indent=2)


def validate_bot_token(token: str) -> tuple[bool, str]:
    """Validate bot token by calling auth.test API."""
    if not token.startswith("xoxb-"):
        return False, "Token must start with 'xoxb-'"

    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    try:
        response = WebClient(token=token).auth_test()
        team = response.get("team", "Unknown")
        user = response.get("user", "Unknown")
        return True, f"Workspace: {team}, Bot: @{user}"
    except SlackApiError as e:
        return False, e.response["error"]
    except Exception as e:
        return False, str(e)


def update_vm_env(
    bot_token: str, app_token: str, bot_name: str = "", slash_command: str = ""
) -> bool:
    """Update config/vm.env with Slack tokens, bot name, and slash command."""
    try:
        # Read existing content
        if VM_ENV_PATH.exists():
            with open(VM_ENV_PATH, "r") as f:
                content = f.read()
        else:
            content = ""

        # Update or add SLACK_BOT_TOKEN
        if "SLACK_BOT_TOKEN=" in content:
            content = re.sub(
                r"SLACK_BOT_TOKEN=.*",
                f"SLACK_BOT_TOKEN={bot_token}",
                content,
            )
        else:
            content += f"\nSLACK_BOT_TOKEN={bot_token}"

        # Update or add SLACK_APP_TOKEN
        if "SLACK_APP_TOKEN=" in content:
            content = re.sub(
                r"SLACK_APP_TOKEN=.*",
                f"SLACK_APP_TOKEN={app_token}",
                content,
            )
        else:
            content += f"\nSLACK_APP_TOKEN={app_token}"

        # Update or add SLACK_BOT_NAME
        if bot_name:
            if "SLACK_BOT_NAME=" in content:
                content = re.sub(
                    r"SLACK_BOT_NAME=.*",
                    f"SLACK_BOT_NAME={bot_name}",
                    content,
                )
            else:
                content += f"\nSLACK_BOT_NAME={bot_name}"

        # Update or add SLACK_SLASH_COMMAND
        if slash_command:
            if "SLACK_SLASH_COMMAND=" in content:
                content = re.sub(
                    r"SLACK_SLASH_COMMAND=.*",
                    f"SLACK_SLASH_COMMAND={slash_command}",
                    content,
                )
            else:
                content += f"\nSLACK_SLASH_COMMAND={slash_command}"

        # Write back
        with open(VM_ENV_PATH, "w") as f:
            f.write(content)

        return True

    except Exception as e:
        print_error(f"Failed to update {VM_ENV_PATH}: {e}")
        return False


def main():
    print("\n" + "=" * 80)
    print("  Slack Integration Setup for AgentSPEX")
    print("=" * 80)

    # Step 1: Name your bot
    print("\n[1/6] Name Your Bot...")

    existing_name = get_existing_bot_name()
    default_name = existing_name or "Sandbox Agent"

    print_box(
        [
            "Choose a name for your Slack bot.",
            "",
            "If multiple people add this bot to the same workspace,",
            "each person should pick a unique name to avoid conflicts.",
            "",
            f"Current default: {default_name}",
        ],
        title="Bot Naming",
    )

    while True:
        bot_app_name = input(f"\n  Bot name [{default_name}]: ").strip()
        if not bot_app_name:
            bot_app_name = default_name

        valid, error = validate_bot_name(bot_app_name)
        if valid:
            break
        print_error(error)

    bot_display_name = make_bot_display_name(bot_app_name)
    slash_command = make_slash_command(bot_display_name)
    print_success(f"App name: {bot_app_name}")
    print_success(f"Display name: @{bot_display_name}")
    print_success(f"Slash command: {slash_command}")

    if existing_name and bot_app_name != existing_name:
        print_info(
            "Name changed — you'll need to create a new Slack app or rename the existing one."
        )

    # Step 2: Show Slack app creation guide
    print("\n[2/6] Create Slack App...")

    # Load manifest template and customize with chosen name
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r") as f:
            manifest_template = f.read()
    else:
        print_error(f"Manifest not found: {MANIFEST_PATH}")
        sys.exit(1)

    manifest = customize_manifest(
        manifest_template, bot_app_name, bot_display_name, slash_command
    )

    print_box(
        [
            "To create your Slack app:",
            "",
            "1. Go to: https://api.slack.com/apps",
            "2. Click 'Create New App' → 'From manifest'",
            "3. Select your workspace",
            "4. Paste the manifest (JSON format)",
            "5. Click 'Create'",
            "6. Install the app to your workspace",
        ],
        title="Slack App Setup",
    )

    input("\n  Press Enter to copy the manifest to clipboard...")

    if copy_to_clipboard(manifest):
        print_success(f'Manifest copied (app name: "{bot_app_name}")!')
        print_info("Paste it into the Slack app creation page")
    else:
        print_info("Could not copy to clipboard. Manifest content:")
        print("-" * 40)
        print(manifest)
        print("-" * 40)

    input("\n  Press Enter when you've created and installed the app...")

    # Step 3: Get Bot Token
    print("\n[3/6] Get Bot Token...")
    print_box(
        [
            "Find your Bot Token:",
            "",
            "1. Go to your app at https://api.slack.com/apps",
            "2. Click 'OAuth & Permissions' in the sidebar",
            "3. Click 'Install to Workspace' and authorize the app",
            "4. Copy the 'Bot User OAuth Token' (starts with xoxb-)",
        ],
        title="Bot Token",
    )

    while True:
        bot_token = input("\n  Enter Bot Token (xoxb-...): ").strip()
        if not bot_token:
            print_error("Token is required")
            continue

        valid, message = validate_bot_token(bot_token)
        if valid:
            print_success(f"Bot token validated ({message})")
            break
        else:
            print_error(f"Invalid token: {message}")
            retry = input("  Try again? [Y/n]: ").strip().lower()
            if retry == "n":
                print_info("Continuing with unvalidated token...")
                break

    # Step 4: Get App Token
    print("\n[4/6] Get App Token...")
    print_box(
        [
            "Generate an App-Level Token:",
            "",
            "1. Go to your app at https://api.slack.com/apps",
            "2. Click 'Basic Information' in the sidebar",
            "3. Scroll to 'App-Level Tokens'",
            "4. Click 'Generate Token and Scopes'",
            "5. Name it (e.g., 'socket-mode')",
            "6. Add the 'connections:write' scope",
            "7. Click 'Generate' and copy the token (xapp-...)",
        ],
        title="App Token",
    )

    while True:
        app_token = input("\n  Enter App Token (xapp-...): ").strip()
        if not app_token:
            print_error("Token is required")
            continue

        if not app_token.startswith("xapp-"):
            print_error("Token must start with 'xapp-'")
        elif len(app_token) < 50:
            print_error("Token appears too short")
        else:
            print_success("App token format valid")
            break

    # Step 5: Save tokens and bot name
    print("\n[5/6] Saving configuration...")

    if update_vm_env(
        bot_token, app_token, bot_name=bot_app_name, slash_command=slash_command
    ):
        print_success(f"Tokens saved to {VM_ENV_PATH}")
    else:
        print_error("Failed to save tokens")
        print_info(f"Manually add to {VM_ENV_PATH}:")
        print(f"    SLACK_BOT_TOKEN={bot_token}")
        print(f"    SLACK_APP_TOKEN={app_token}")

    # Step 6: Restart Docker VM
    print("\n[6/6] Restart Docker VM...")
    print_info("The Docker VM needs to be restarted to pick up the new tokens.")

    restart = input("\n  Restart Docker VM now? [Y/n]: ").strip().lower()
    if restart != "n":
        run_vm_script = PROJECT_ROOT / "scripts" / "run_vm.sh"
        print_info("Stopping Docker VM...")
        stop_result = subprocess.run(
            ["bash", str(run_vm_script), "stop"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if (
            stop_result.returncode != 0
            and "not running" not in stop_result.stderr.lower()
        ):
            print_info("VM was not running, starting fresh...")

        print_info("Starting Docker VM...")
        start_result = subprocess.run(
            ["bash", str(run_vm_script), "start"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if start_result.returncode == 0:
            print_success("Docker VM restarted successfully!")
        else:
            print_error("Failed to start Docker VM")
            print_info(f"Error: {start_result.stderr}")
            print_info("Try manually: ./scripts/run_vm.sh start")
    else:
        print_box(
            [
                "Remember to restart the VM before using the Slack bot:",
                "",
                "  ./scripts/run_vm.sh stop",
                "  ./scripts/run_vm.sh start",
            ],
            title="Manual Restart",
        )

    # Offer to start listener
    print("\n" + "=" * 80)
    print("  Setup Complete!")
    print("=" * 80)

    print_box(
        [
            "Your Slack integration is ready!",
            "",
            "To start the listener:",
            "  python scripts/slack_listener.py",
            "",
            "The bot will respond to:",
            "  • @mentions in channels",
            "  • Direct messages",
            f"  • {slash_command} slash command",
            "",
            "Don't forget to invite the bot to channels:",
            f"  /invite @{bot_display_name}",
        ],
        title="Next Steps",
    )

    response = input("\n  Start Slack listener now? [Y/n]: ").strip().lower()
    if response != "n":
        print("\n  Starting Slack listener...\n")
        listener_path = SCRIPT_DIR / "slack_listener.py"
        os.execv(sys.executable, [sys.executable, str(listener_path)])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.")
        sys.exit(0)
