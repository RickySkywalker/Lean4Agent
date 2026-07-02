# Slack Integration

Slack integration allows you to interact with the AI agent directly from Slack. The bot responds to @mentions, direct messages, thread follow-ups, and slash commands.

---

## Quick Start

1. **Run the setup wizard** (creates the Slack app, sets OAuth scopes, saves tokens):
   ```bash
   agentspex setup slack
   ```
   The wizard lets you choose a custom bot name — useful when multiple users share a workspace.

2. **Start the listener**:
   ```bash
   agentspex listen slack
   ```

---

## Usage

### @mentions

Mention the bot in any channel it has been invited to:
```
@YourBotName can you help me find recent papers in the field of machine learning?
```

The bot replies in a thread.

### Direct messages

Send a DM to the bot directly — no mention needed.

### Thread follow-ups

Once the bot has replied in a thread, you can continue the conversation there without mentioning it again. The bot checks whether it has previously participated before responding.

### Slash command

The slash command name is derived from the bot name you chose during setup (e.g. "Sandbox Agent" → `/sandbox-agent`):
```
/sandbox-agent what's the latest on LLM benchmarks?
/sandbox-agent run deep_research
```

### Running a named workflow

Include a workflow name anywhere in your message:
```
@YourBotName run deep_research
@YourBotName start quickstart
```

The listener pattern-matches against all YAML files in `workflows/`. The named plan runs in the background and notifies the thread when done.

---

## Workflows

The default workflow (`workflows/slack_templates/default.yaml`) handles general conversations. It fetches thread history for context, processes the request, and replies in the thread.

### Custom workflows

Create a YAML file anywhere under `workflows/` (avoid the `modules/` subdirectory):

```yaml
name: "my_slack_task"
goal: "What this task does"

config:
  model: "gpt-5.4"
  max_iterations: 5

parameters:
  slack_channel: "${SLACK_CHANNEL}"
  slack_thread_ts: "${SLACK_THREAD_TS}"
  user_message: "${SLACK_MESSAGE_TEXT}"

workflow:
  - step:
      name: "handle"
      instruction: |
        Process the user's request and reply using the slack_reply tool.
        Channel: ${SLACK_CHANNEL}  Thread: ${SLACK_THREAD_TS}
        Message: "${SLACK_MESSAGE_TEXT}"
```

Trigger it with: `@YourBotName run my_slack_task`

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `slack_send_message` | Send a message to a channel or thread |
| `slack_reply` | Reply in a thread (convenience wrapper) |
| `slack_add_reaction` | Add an emoji reaction to a message |
| `slack_get_thread` | Get formatted conversation history from a thread |

---

## Listener Options

```bash
agentspex listen slack --with_dashboard   # enable real-time dashboard
agentspex listen slack --debug            # verbose logging
```
