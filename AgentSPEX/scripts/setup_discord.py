"""
Interactive Discord bot setup wizard.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
VM_ENV_PATH = PROJECT_ROOT / "config" / "vm.env"

DISCORD_API_BASE = "https://discord.com/api/v10"

# Bot permissions needed: View Channels + Send Messages + Read History + Add Reactions
BOT_PERMISSIONS = 68672  # 0x400 | 0x800 | 0x10000 | 0x40


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
    print(f"  ✓ {text}")


def print_error(text: str):
    print(f"  ✗ {text}")


def print_info(text: str):
    print(f"  → {text}")


def validate_bot_token(token: str) -> tuple[bool, str]:
    """Validate bot token by calling the Discord /users/@me endpoint."""
    try:
        response = requests.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            username = data.get("username", "unknown")
            bot_id = data.get("id", "")
            return (
                True,
                f"Bot: {username}#{data.get('discriminator', '0')} (ID: {bot_id}), Application ID: {bot_id}",
            )
        elif response.status_code == 401:
            return False, "Invalid token (401 Unauthorized)"
        else:
            return False, f"Unexpected response: {response.status_code}"
    except requests.RequestException as e:
        return False, f"Network error: {e}"


def get_application_id(token: str) -> str | None:
    """Fetch the application ID from the token (same as bot user ID for bots)."""
    try:
        response = requests.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("id")
    except Exception:
        pass
    return None


def build_invite_url(application_id: str, permissions: int = BOT_PERMISSIONS) -> str:
    return (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={application_id}"
        f"&permissions={permissions}"
        f"&scope=bot%20applications.commands"
    )


def update_vm_env(token: str, slash_command: str = "") -> bool:
    """Update config/vm.env with Discord bot token and optional slash command."""
    try:
        content = VM_ENV_PATH.read_text() if VM_ENV_PATH.exists() else ""

        def upsert(key: str, value: str, text: str) -> str:
            if f"{key}=" in text:
                return re.sub(rf"{key}=.*", f"{key}={value}", text)
            return text + f"\n{key}={value}"

        content = upsert("DISCORD_BOT_TOKEN", token, content)
        if slash_command:
            content = upsert("DISCORD_SLASH_COMMAND", slash_command, content)

        VM_ENV_PATH.write_text(content)
        return True
    except Exception as e:
        print_error(f"Failed to update {VM_ENV_PATH}: {e}")
        return False


def main():
    print("\n" + "=" * 80)
    print("  Discord Bot Setup for AgentSPEX")
    print("=" * 80)

    # Step 1: Create app & bot
    print("\n[1/5] Create a Discord Application & Bot...")
    print_box(
        [
            "1. Go to: https://discord.com/developers/applications",
            "2. Click 'New Application' and give it a name",
            "3. Go to the 'Bot' tab in the sidebar",
            "4. Scroll to 'Privileged Gateway Intents' and enable:",
            "     ✓ MESSAGE CONTENT INTENT  ← REQUIRED or the bot will fail to start",
            "     ✓ SERVER MEMBERS INTENT   ← optional, for display names",
            "5. Click 'Save Changes' — do not skip this or the listener will error",
        ],
        title="Discord Developer Portal",
    )
    input("\n  Press Enter when you've created the bot and enabled the intents...")

    # Step 2: Get bot token
    print("\n[2/5] Get Bot Token...")
    print_box(
        [
            "Copy your bot token:",
            "",
            "1. Go to the 'Bot' tab at https://discord.com/developers/applications",
            "2. Click 'Reset Token' (you may need to confirm with 2FA)",
            "3. Copy the token that appears",
            "",
            "Keep this token secret — it grants full control of your bot.",
        ],
        title="Bot Token",
    )

    bot_token = ""
    application_id = ""
    while True:
        bot_token = input("\n  Enter Bot Token: ").strip()
        if not bot_token:
            print_error("Token is required")
            continue

        valid, message = validate_bot_token(bot_token)
        if valid:
            print_success(f"Token validated — {message}")
            application_id = get_application_id(bot_token) or ""
            break
        else:
            print_error(f"Invalid token: {message}")
            retry = input("  Try again? [Y/n]: ").strip().lower()
            if retry == "n":
                print_info("Continuing with unvalidated token...")
                break

    # Step 3: Slash command name
    print("\n[3/5] Slash Command Name...")
    print_box(
        [
            "Choose a name for the bot's slash command.",
            "",
            "Users will trigger the bot by typing /name in any channel.",
            "For example, the default '/agent' lets users run:",
            "  /agent what's the weather in New York?",
            "  /agent run deep_research",
            "",
            "Must be lowercase letters, numbers, hyphens, or underscores (max 32 chars).",
        ],
        title="Slash Command",
    )
    slash_command = (
        input("\n  Slash command name [agent]: ").strip().lstrip("/") or "agent"
    )
    if not re.match(r"^[a-z0-9_-]{1,32}$", slash_command):
        print_info(
            "Invalid name — defaulting to 'agent' (must be lowercase letters, numbers, _ or -)"
        )
        slash_command = "agent"
    print_success(f"Slash command: /{slash_command}")

    # Step 4: Invite bot to server
    print("\n[4/5] Invite Bot to Your Server...")
    if application_id:
        invite_url = build_invite_url(application_id)
        print_box(
            [
                "Open this URL in your browser to invite the bot:",
                "",
                invite_url,
                "",
                "1. Select the server you want to add the bot to",
                "2. Click 'Authorise' — Discord will ask you to confirm these permissions:",
                "     ✓ View Channels",
                "     ✓ Send Messages",
                "     ✓ Read Message History",
                "     ✓ Add Reactions",
            ],
            title="Server Invite",
        )
    else:
        print_box(
            [
                "Build your invite URL at:",
                "  https://discord.com/developers/applications → OAuth2 → URL Generator",
                "",
                "Select scopes: bot, applications.commands",
                "Select permissions: View Channels, Send Messages,",
                "  Read Message History, Add Reactions",
            ],
            title="Server Invite",
        )
    input("\n  Press Enter after inviting the bot to your server...")

    # Step 5: Save configuration
    print("\n[5/5] Saving configuration...")
    if update_vm_env(bot_token, slash_command):
        print_success(f"Configuration saved to {VM_ENV_PATH}")
    else:
        print_error("Failed to save configuration")
        print_info(f"Manually add to {VM_ENV_PATH}:")
        print(f"    DISCORD_BOT_TOKEN={bot_token}")
        print(f"    DISCORD_SLASH_COMMAND={slash_command}")

    # Offer Docker VM restart
    print_info("The Docker VM needs to be restarted to pick up the new token.")
    restart = input("\n  Restart Docker VM now? [Y/n]: ").strip().lower()
    if restart != "n":
        run_vm = PROJECT_ROOT / "scripts" / "run_vm.sh"
        print_info("Stopping Docker VM...")
        subprocess.run(
            ["bash", str(run_vm), "stop"], cwd=PROJECT_ROOT, capture_output=True
        )
        print_info("Starting Docker VM...")
        result = subprocess.run(
            ["bash", str(run_vm), "start"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print_success("Docker VM restarted successfully!")
        else:
            print_error(
                "Failed to restart VM — try manually: ./scripts/run_vm.sh start"
            )
    else:
        print_box(
            [
                "Remember to restart the VM: ./scripts/run_vm.sh stop && ./scripts/run_vm.sh start"
            ],
            title="Manual Restart",
        )

    # Summary
    print("\n" + "=" * 80)
    print("  Setup Complete!")
    print("=" * 80)
    print_box(
        [
            "Your Discord bot is ready!",
            "",
            "To start the listener:",
            "  python scripts/discord_listener.py",
            "",
            "The bot will respond to:",
            "  • @mentions in channels",
            "  • Direct messages",
            f"  • /{slash_command} slash command",
            "  • Follow-up messages in threads it has participated in",
        ],
        title="Next Steps",
    )

    response = input("\n  Start Discord listener now? [Y/n]: ").strip().lower()
    if response != "n":
        print("\n  Starting Discord listener...\n")
        listener_path = SCRIPT_DIR / "discord_listener.py"
        os.execv(sys.executable, [sys.executable, str(listener_path)])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.")
        sys.exit(0)
