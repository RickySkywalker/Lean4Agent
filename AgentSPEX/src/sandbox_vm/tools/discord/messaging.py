"""
Discord messaging tools for MCP server.
Provides functions to send messages, reply to messages, add reactions, and read channel history.
Uses the Discord REST API directly (no gateway connection required).
"""

import os
import urllib.parse
from typing import Optional

import requests

DISCORD_API_BASE = "https://discord.com/api/v10"


def _get_headers() -> dict:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError(
            "DISCORD_BOT_TOKEN not set. "
            "Add to config/vm.env or run: python scripts/setup_discord.py"
        )
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}


def _handle_response(response: requests.Response) -> dict:
    if response.status_code in (200, 201, 204):
        return response.json() if response.content else {}
    try:
        error_body = response.json()
        message = error_body.get("message", response.text)
        code = error_body.get("code", response.status_code)
        return {"error": f"Discord API error {code}: {message}"}
    except Exception:
        return {"error": f"Discord API error {response.status_code}: {response.text}"}


async def discord_send_message(
    channel_id: str,
    text: str,
    reference_message_id: Optional[str] = None,
) -> dict:
    """
    Send a message to a Discord channel.

    Args:
        channel_id: The channel ID to send the message to
        text: Message content (up to 2000 characters; supports Discord markdown)
        reference_message_id: Optional message ID to reply to (shows as a reply in Discord)

    Returns:
        dict: {"id": str (message ID), "channel_id": str} on success,
              or {"error": str} on failure

    Examples:
        discord_send_message(channel_id="123456789", text="Hello!")
        discord_send_message(channel_id="123456789", text="Got it!", reference_message_id="987654321")
    """
    try:
        payload: dict = {"content": text}
        if reference_message_id:
            payload["message_reference"] = {"message_id": reference_message_id}

        response = requests.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=_get_headers(),
            json=payload,
        )
        result = _handle_response(response)
        if "error" in result:
            return result
        return {"id": result.get("id"), "channel_id": result.get("channel_id")}

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


async def discord_reply(
    channel_id: str,
    message_id: str,
    text: str,
) -> dict:
    """
    Reply to a specific message in a Discord channel.

    Args:
        channel_id: Channel ID where the original message exists
        message_id: ID of the message to reply to
        text: Reply content (supports Discord markdown)

    Returns:
        dict: {"id": str (reply message ID), "channel_id": str} on success,
              or {"error": str} on failure

    Examples:
        discord_reply(channel_id="123456789", message_id="987654321", text="Thanks!")
    """
    return await discord_send_message(
        channel_id=channel_id,
        text=text,
        reference_message_id=message_id,
    )


async def discord_add_reaction(
    channel_id: str,
    message_id: str,
    emoji: str,
) -> dict:
    """
    Add a reaction to a Discord message.

    Args:
        channel_id: Channel ID where the message exists
        message_id: ID of the message to react to
        emoji: Emoji to react with. Use Unicode emoji directly (e.g. "👍") or
               custom emoji in the format "name:id" (e.g. "my_emoji:123456789")

    Returns:
        dict: {} on success, or {"error": str} on failure

    Examples:
        discord_add_reaction(channel_id="123456789", message_id="987654321", emoji="👍")
        discord_add_reaction(channel_id="123456789", message_id="987654321", emoji="✅")
    """
    try:
        encoded_emoji = urllib.parse.quote(emoji)
        response = requests.put(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me",
            headers=_get_headers(),
        )
        result = _handle_response(response)
        return result if "error" in result else {}

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


async def discord_get_channel_history(
    channel_id: str,
    limit: int = 50,
    before_message_id: Optional[str] = None,
) -> dict:
    """
    Get recent message history from a Discord channel or thread.

    For threads, pass the thread's channel ID directly — Discord threads are
    themselves channels with a unique ID.

    Args:
        channel_id: Channel or thread ID to fetch messages from
        limit: Number of messages to retrieve (1–100, default 50)
        before_message_id: If set, only returns messages sent before this message ID

    Returns:
        dict: {
            "conversation": str (formatted conversation for easy reading),
            "messages": [{"id": str, "author": str, "content": str, ...}, ...]
        } on success, or {"error": str} on failure

    The "conversation" field contains a human-readable format like:
        User (Jerry): Hello, can you help me?
        Agent: Of course! What do you need?

    Examples:
        discord_get_channel_history(channel_id="123456789")
        discord_get_channel_history(channel_id="123456789", limit=25)
    """
    try:
        limit = max(1, min(limit, 100))
        params: dict = {"limit": limit}
        if before_message_id:
            params["before"] = before_message_id

        response = requests.get(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=_get_headers(),
            params=params,
        )
        result = _handle_response(response)
        if "error" in result:
            return result

        # API returns messages newest-first; reverse for chronological order
        raw_messages = list(reversed(result)) if isinstance(result, list) else []

        # Fetch bot's own user ID to label agent messages
        bot_user_id = _get_bot_user_id()

        messages = []
        formatted_lines = []
        for msg in raw_messages:
            author = msg.get("author", {})
            author_id = author.get("id", "")
            username = author.get("global_name") or author.get("username", author_id)
            is_bot = author.get("bot", False)
            content = msg.get("content", "")

            if not content.strip():
                continue

            messages.append(
                {
                    "id": msg.get("id"),
                    "author_id": author_id,
                    "author": username,
                    "content": content,
                    "timestamp": msg.get("timestamp"),
                    "is_bot": is_bot,
                }
            )

            if author_id == bot_user_id or is_bot:
                speaker = "Agent"
            else:
                speaker = f"User ({username})"
            formatted_lines.append(f"{speaker}: {content}")

        return {
            "conversation": "\n".join(formatted_lines),
            "messages": messages,
        }

    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


def _get_bot_user_id() -> str:
    """Fetch the bot's own user ID from the Discord API."""
    try:
        response = requests.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers=_get_headers(),
        )
        if response.status_code == 200:
            return response.json().get("id", "")
    except Exception:
        pass
    return ""
