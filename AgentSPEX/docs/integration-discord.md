# Discord Integration

Discord integration allows you to interact with the AI agent from Discord. The bot responds to @mentions, direct messages, thread follow-ups, and a `/agent` slash command (name is configurable).

---

## Quick Start

1. **Run the setup wizard** (creates the bot, validates the token, generates an invite URL):
   ```bash
   agentspex setup discord
   ```

2. **Invite the bot to your server** using the URL printed by the wizard.

3. **Start the listener**:
   ```bash
   agentspex listen discord
   ```

---

## Usage

### @mentions

Mention the bot in any server channel it can read:
```
@YourBot can you summarise this week's news in AI?
```

### Direct messages

Send a DM to the bot directly.

### Thread follow-ups

If the bot has previously sent a message in a Discord Thread, it monitors that thread for follow-up messages and responds automatically.

### Slash command

```
/agent what's the weather in San Francisco?
/agent run deep_research
```

The slash command name defaults to `agent` and is configurable via `DISCORD_SLASH_COMMAND` in `config/vm.env`.

### Running a named workflow

Include a trigger keyword and a workflow name in your message:
```
@YourBot run deep_research
/agent start quickstart
```

The named plan runs in the background; when it finishes the bot posts a completion notice referencing your original message.

---

## Workflows

The default workflow handles general conversations: it fetches recent channel history for context and replies using `discord_reply`. Point the listener at any workflow YAML under `workflows/`.

### Custom workflows

```yaml
name: "my_discord_task"
goal: "What this task does"

config:
  model: "gpt-4o"
  max_iterations: 5

parameters:
  discord_channel_id: "${DISCORD_CHANNEL_ID}"
  discord_message_id: "${DISCORD_MESSAGE_ID}"
  user_message: "${DISCORD_MESSAGE_TEXT}"

workflow:
  - step:
      name: "handle"
      instruction: |
        Process the user's request and reply using the discord_reply tool.
        Channel: ${DISCORD_CHANNEL_ID}  Message: ${DISCORD_MESSAGE_ID}
        Message: "${DISCORD_MESSAGE_TEXT}"
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `discord_send_message` | Send a message to a channel (optionally as a reply) |
| `discord_reply` | Reply to a specific message |
| `discord_add_reaction` | Add an emoji reaction to a message |
| `discord_get_channel_history` | Get recent message history from a channel or thread |

Discord messages have a 2000 character limit. For longer responses, call `discord_send_message` multiple times.

---

## Listener Options

```bash
agentspex listen discord --with_dashboard   # enable real-time dashboard
agentspex listen discord --debug            # verbose logging
```
