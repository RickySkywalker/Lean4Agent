"""Session state management for the agentic loop."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LoopConfig:
    """Configuration for agentic loop sessions."""

    model: str = "claude-opus-4-5"
    mcp_url: str = "http://localhost:7002/mcp"
    max_turns: int = 200
    max_tool_calls_per_turn: int = 10
    temperature: float = 0.2
    output_dir: str = "outputs/agentic_loop"
    max_tool_result_chars: int = 30000
    model_kwargs: dict = field(default_factory=dict)
    plan_generator_model: str = "gpt-5"
    plan_executor_model: str = "claude-sonnet-4-6"


class Session:
    """Manages orchestrator conversation history and usage tracking."""

    def __init__(self, config: LoopConfig):
        self.config = config
        self.messages: list[dict[str, Any]] = []
        self.turn_count: int = 0
        self.total_tokens: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0

    def add_system_message(self, content: str) -> None:
        """Set the system message (called once at start)."""
        # Replace any existing system message
        self.messages = [m for m in self.messages if m.get("role") != "system"]
        self.messages.insert(0, {"role": "system", "content": content})

    def add_user_message(self, content: str) -> None:
        """Add user message to history."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self, content: str, tool_calls: Optional[list] = None
    ) -> None:
        """Add assistant message, optionally with tool calls."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_results(self, results: list[dict]) -> None:
        """Add tool result messages to history."""
        for result in results:
            self.messages.append(result)

    def track_usage(self, usage: dict[str, int]) -> None:
        """Accumulate token usage from an LLM response."""
        self.total_tokens += usage.get("total_tokens", 0)
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)

    def get_usage_summary(self) -> dict[str, Any]:
        """Return a summary of token usage."""
        return {
            "turns": self.turn_count,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }
