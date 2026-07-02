"""
Slack messaging tools for MCP server.
Provides functions to send messages, reply in threads, add reactions, and read threads.
"""

import os
import re
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def _get_slack_client() -> WebClient:
    """Get a configured Slack WebClient."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise ValueError(
            "SLACK_BOT_TOKEN not set. "
            "Run: python scripts/setup_slack.py or manually add to config/vm.env"
        )
    return WebClient(token=token)


async def slack_send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
) -> dict:
    """
    Send a message to a Slack channel.

    Args:
        channel: Channel ID (e.g., C1234567890) or channel name (e.g., #general)
        text: Message text to send (supports Slack mrkdwn formatting)
        thread_ts: Optional thread timestamp to reply in a thread

    Returns:
        dict: {"ts": str (message timestamp), "channel": str} on success,
              or {"error": str} on failure

    Examples:
        slack_send_message(channel="C1234567890", text="Hello, world!")
        slack_send_message(channel="#general", text="Hello!", thread_ts="1234567890.123456")
    """
    try:
        client = _get_slack_client()

        kwargs = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = client.chat_postMessage(**kwargs)

        return {
            "ts": response["ts"],
            "channel": response["channel"],
            "message": response.get("message", {}),
        }

    except SlackApiError as e:
        return {
            "error": f"Slack API error: {e.response['error']}",
            "details": str(e),
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


async def slack_reply(
    channel: str,
    thread_ts: str,
    text: str,
) -> dict:
    """
    Reply to a message in a Slack thread.

    This is a convenience wrapper around slack_send_message that requires thread_ts.

    Args:
        channel: Channel ID where the thread exists
        thread_ts: Timestamp of the parent message (thread root)
        text: Reply message text (supports Slack mrkdwn formatting)

    Returns:
        dict: {"ts": str (reply timestamp), "channel": str} on success,
              or {"error": str} on failure

    Examples:
        slack_reply(channel="C1234567890", thread_ts="1234567890.123456", text="Thanks!")
    """
    if not thread_ts:
        return {"error": "thread_ts is required for slack_reply"}

    return await slack_send_message(channel=channel, text=text, thread_ts=thread_ts)


async def slack_add_reaction(
    channel: str,
    timestamp: str,
    emoji: str,
) -> dict:
    """
    Add an emoji reaction to a Slack message.

    Args:
        channel: Channel ID where the message exists
        timestamp: Timestamp of the message to react to
        emoji: Emoji name without colons (e.g., "thumbsup", "white_check_mark", "thinking_face")

    Returns:
        dict: {} on success, or {"error": str} on failure

    Examples:
        slack_add_reaction(channel="C1234567890", timestamp="1234567890.123456", emoji="thumbsup")
        slack_add_reaction(channel="C1234567890", timestamp="1234567890.123456", emoji="white_check_mark")
    """
    try:
        client = _get_slack_client()

        # Remove colons if user accidentally included them
        emoji_name = emoji.strip(":")

        response = client.reactions_add(
            channel=channel,
            timestamp=timestamp,
            name=emoji_name,
        )

        return {}

    except SlackApiError as e:
        error_code = e.response.get("error", "")
        # "already_reacted" is not really an error for our purposes
        if error_code == "already_reacted":
            return {"note": "Reaction already exists"}
        return {
            "error": f"Slack API error: {error_code}",
            "details": str(e),
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}


def _get_user_display_name(client: WebClient, user_id: str, cache: dict) -> str:
    """Get a user's display name, with caching to avoid repeated API calls."""
    if user_id in cache:
        return cache[user_id]

    try:
        response = client.users_info(user=user_id)
        user_info = response.get("user", {})
        profile = user_info.get("profile", {})

        # Try display_name first, then real_name, then fallback to user ID
        display_name = (
            profile.get("display_name")
            or profile.get("real_name")
            or user_info.get("real_name")
            or user_id
        )

        # Check if this is a bot
        if user_info.get("is_bot"):
            display_name = f"{display_name} (Bot)"

        cache[user_id] = display_name
        return display_name

    except SlackApiError:
        cache[user_id] = user_id
        return user_id


def _format_conversation(messages: list, client: WebClient, bot_user_id: str) -> str:
    """
    Format thread messages as a natural language conversation.

    Returns a string like:
        User (Jerry): Hello, can you help me?
        Agent: Of course! What do you need help with?
        User (Jerry): I need to search for something
    """
    user_cache = {}
    formatted_lines = []

    for msg in messages:
        user_id = msg.get("user", "")
        text = msg.get("text", "")

        # Skip empty messages
        if not text.strip():
            continue

        # Determine if this is the bot or a user
        if user_id == bot_user_id:
            speaker = "Agent"
        else:
            display_name = _get_user_display_name(client, user_id, user_cache)
            speaker = f"User ({display_name})"

        # Clean up the text (remove bot mentions for readability)
        text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        formatted_lines.append(f"{speaker}: {text}")

    return "\n".join(formatted_lines)


async def slack_get_thread(
    channel: str,
    thread_ts: str,
    limit: int = 100,
) -> dict:
    """
    Get all messages in a Slack thread.

    Args:
        channel: Channel ID where the thread exists
        thread_ts: Timestamp of the parent message (thread root)
        limit: Maximum number of messages to retrieve (default 100, max 1000)

    Returns:
        dict: {
            "conversation": str (formatted conversation for easy reading),
            "messages": [{"user": str, "text": str, "ts": str, ...}, ...],
            "has_more": bool
        } on success, or {"error": str} on failure

    The "conversation" field contains a human-readable format like:
        User (Jerry): Hello, can you help?
        Agent: Of course! What do you need?
        User (Jerry): I need to search for X

    Examples:
        slack_get_thread(channel="C1234567890", thread_ts="1234567890.123456")
        slack_get_thread(channel="C1234567890", thread_ts="1234567890.123456", limit=50)
    """
    try:
        client = _get_slack_client()

        # Clamp limit to valid range
        limit = max(1, min(limit, 1000))

        response = client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=limit,
        )

        # Get bot's user ID to identify agent messages
        try:
            auth_response = client.auth_test()
            bot_user_id = auth_response.get("user_id", "")
        except SlackApiError:
            bot_user_id = ""

        # Extract relevant fields from messages
        messages = []
        for msg in response.get("messages", []):
            messages.append(
                {
                    "user": msg.get("user", ""),
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts", ""),
                    "thread_ts": msg.get("thread_ts", ""),
                    "reply_count": msg.get("reply_count", 0),
                    "reactions": msg.get("reactions", []),
                }
            )

        # Format as natural language conversation
        conversation = _format_conversation(messages, client, bot_user_id)

        return {
            "conversation": conversation,
            "messages": messages,
            "has_more": response.get("has_more", False),
        }

    except SlackApiError as e:
        return {
            "error": f"Slack API error: {e.response['error']}",
            "details": str(e),
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}
