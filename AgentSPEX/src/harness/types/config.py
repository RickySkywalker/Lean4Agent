"""Execution configuration types.

This module provides the EffectiveArgs dataclass for managing execution
configuration in a thread-safe, immutable manner.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class EffectiveArgs:
    """
    Thread-safe immutable wrapper for execution arguments with per-file config support.

    This class provides a way to pass execution configuration (model, tokens, etc.)
    through the workflow execution chain while allowing submodules to override
    specific settings without modifying the parent's configuration.

    The immutable pattern ensures thread-safety for parallel execution.

    Attributes:
        model: The LLM model to use (e.g., 'gpt-4o', 'openai/gpt-4o', 'anthropic/claude-3-opus')
        api_base: Base URL for API calls (for vLLM, custom endpoints). If None, uses provider default.
        max_tokens_per_step: Maximum tokens allowed per workflow step
        max_tool_calls_per_step: Maximum tool calls allowed per step
        temperature: LLM temperature setting
        plan_revision_max_steps: Maximum steps for plan revision
        workflow_file: Path to the workflow YAML file

    Example:
        # Create from CLI args
        args = EffectiveArgs.from_args(parsed_args)

        # Override with YAML config
        submodule_args = args.with_yaml_config({'model': 'gpt-4o'})

        # Use local vLLM server
        args = EffectiveArgs(
            model='hosted_vllm/meta-llama/Llama-3.1-8B-Instruct',
            api_base='http://localhost:8000'
        )
    """

    model: str = "gpt-4.1-mini"
    api_base: Optional[str] = None
    max_tokens_per_step: int = 100000
    max_tool_calls_per_step: int = 10
    max_tool_calls: Optional[int] = None
    temperature: float = 0.2
    model_kwargs: Dict[str, Any] = field(default_factory=dict)
    context_threshold: float = 0.6
    plan_revision_max_steps: int = 0
    workflow_file: Optional[str] = None

    # Store original args reference for any other attributes
    _original_args: Any = field(default=None, repr=False)

    @classmethod
    def from_args(cls, args) -> "EffectiveArgs":
        """
        Create EffectiveArgs from an argparse namespace or similar object.

        Args:
            args: The original args object (typically from argparse)

        Returns:
            New EffectiveArgs instance with values from args
        """
        return cls(
            model=getattr(args, "model", "gpt-4.1-mini"),
            api_base=getattr(args, "api_base", None),
            max_tokens_per_step=getattr(args, "max_tokens_per_step", 100000),
            max_tool_calls_per_step=getattr(args, "max_tool_calls_per_step", 10),
            max_tool_calls=getattr(args, "max_tool_calls", None),
            temperature=getattr(args, "temperature", 0.2),
            model_kwargs=getattr(args, "model_kwargs", None) or {},
            context_threshold=getattr(args, "context_threshold", 0.6),
            plan_revision_max_steps=getattr(args, "plan_revision_max_steps", 0),
            workflow_file=getattr(args, "workflow_file", None),
            _original_args=args,
        )

    def with_yaml_config(self, yaml_config: Dict[str, Any]) -> "EffectiveArgs":
        """
        Create a NEW EffectiveArgs with YAML config overrides (immutable pattern).

        This method does not modify the current instance. Instead, it returns
        a new instance with the YAML config values applied as overrides.

        Args:
            yaml_config: Dictionary from YAML 'config' section

        Returns:
            New EffectiveArgs instance with config values applied
        """
        model_kwargs_override = yaml_config.get("model_kwargs")
        if model_kwargs_override is None:
            merged_model_kwargs = dict(self.model_kwargs)
        elif isinstance(model_kwargs_override, dict):
            merged_model_kwargs = {**self.model_kwargs, **model_kwargs_override}
        else:
            raise ValueError("config.model_kwargs must be a mapping/dict if provided.")

        # Allow temperature in top-level config, model_kwargs, or model_kwargs.thinking
        temperature = yaml_config.get("temperature")
        if temperature is None:
            temperature = merged_model_kwargs.pop("temperature", None)
        else:
            merged_model_kwargs.pop("temperature", None)
        if temperature is None:
            thinking = merged_model_kwargs.get("thinking")
            if isinstance(thinking, dict) and "temperature" in thinking:
                temperature = thinking.pop("temperature")
        if temperature is None:
            temperature = self.temperature

        return EffectiveArgs(
            model=yaml_config.get("model", yaml_config.get("model_name", self.model)),
            api_base=yaml_config.get("api_base", self.api_base),
            max_tokens_per_step=yaml_config.get(
                "max_tokens_per_step", self.max_tokens_per_step
            ),
            max_tool_calls_per_step=yaml_config.get(
                "max_tool_calls_per_step", self.max_tool_calls_per_step
            ),
            max_tool_calls=self.max_tool_calls if self.max_tool_calls is not None else yaml_config.get("max_tool_calls"),
            temperature=temperature,
            model_kwargs=merged_model_kwargs,
            context_threshold=yaml_config.get(
                "context_threshold", self.context_threshold
            ),
            plan_revision_max_steps=yaml_config.get(
                "plan_revision_max_steps", self.plan_revision_max_steps
            ),
            workflow_file=self.workflow_file,
            _original_args=self._original_args,
        )

    def __getattr__(self, name):
        """Fallback to original args for any unhandled attributes."""
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        if self._original_args is not None and hasattr(self._original_args, name):
            return getattr(self._original_args, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )
