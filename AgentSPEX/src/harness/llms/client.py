"""LLM Client abstraction using LiteLLM for multi-provider support."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import litellm

from .tokens import extract_token_usage

litellm.suppress_debug_info = True

DEFAULT_TIMEOUT: int = int(
    os.environ.get("LLM_TIMEOUT", os.environ.get("TIMEOUT", "300"))
)
DEFAULT_RETRIES: int = int(os.environ.get("LLM_RETRIES", "5"))


@dataclass
class LLMConfig:
    """Configuration for LLM client."""

    api_base: Optional[str] = None
    api_key: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT
    num_retries: int = DEFAULT_RETRIES
    temperature: Optional[float] = None
    drop_params: bool = True
    _env_keys: Dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        env_mappings = {
            "OPENAI_API_KEY": "openai",
            "ANTHROPIC_API_KEY": "anthropic",
            "GOOGLE_API_KEY": "google",
            "COHERE_API_KEY": "cohere",
            "MISTRAL_API_KEY": "mistral",
            "AZURE_API_KEY": "azure",
            "HOSTED_VLLM_API_KEY": "hosted_vllm",
            "VLLM_API_KEY": "hosted_vllm",
        }
        for env_var, provider in env_mappings.items():
            value = os.environ.get(env_var)
            if value:
                self._env_keys[provider] = value

        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY")

        if not self.api_base:
            self.api_base = os.environ.get("VLLM_API_BASE") or os.environ.get(
                "HOSTED_VLLM_API_BASE"
            )


def normalize_model_name(model: str) -> str:
    """Normalize model name to LiteLLM format (provider/model)."""
    if "/" in model:
        return model

    model_lower = model.lower()

    if model_lower.startswith(
        ("gpt-", "o1-", "o3-", "text-", "davinci", "curie", "babbage", "ada")
    ):
        return f"openai/{model}"
    if model_lower.startswith("claude"):
        return f"anthropic/{model}"
    if model_lower.startswith(("gemini", "palm")):
        return f"google/{model}"
    if model_lower.startswith(("mistral", "mixtral", "codestral")):
        return f"mistral/{model}"
    if model_lower.startswith(("command", "cohere")):
        return f"cohere/{model}"

    return f"openai/{model}"


def get_provider_from_model(model: str) -> str:
    """Extract provider from model name."""
    return normalize_model_name(model).split("/")[0]


class LLMClient:
    """Unified LLM client using LiteLLM."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        num_retries: Optional[int] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Make a chat completion request with automatic retry."""
        normalized_model = normalize_model_name(model)
        provider = get_provider_from_model(model)

        completion_kwargs: Dict[str, Any] = {
            "model": normalized_model,
            "messages": messages,
            "timeout": timeout or self.config.timeout,
            "num_retries": (
                num_retries if num_retries is not None else self.config.num_retries
            ),
        }

        if tools:
            completion_kwargs["tools"] = tools
        if tool_choice and tools:
            completion_kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            completion_kwargs["temperature"] = temperature
        elif self.config.temperature is not None:
            completion_kwargs["temperature"] = self.config.temperature
        if max_tokens is not None:
            completion_kwargs["max_tokens"] = max_tokens

        effective_api_base = api_base or self.config.api_base
        if effective_api_base:
            completion_kwargs["api_base"] = effective_api_base

        # Prioritize provider-specific API keys, then explicit api_key, then default
        if provider in self.config._env_keys:
            completion_kwargs["api_key"] = self.config._env_keys[provider]
        elif api_key:
            completion_kwargs["api_key"] = api_key
        elif self.config.api_key:
            completion_kwargs["api_key"] = self.config.api_key

        if self.config.drop_params:
            completion_kwargs["drop_params"] = True

        completion_kwargs.update(kwargs)

        return litellm.completion(**completion_kwargs)

    def completion_with_usage(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        **kwargs,
    ) -> Tuple[Any, Dict[str, int]]:
        """Make a completion request and return response with usage stats."""
        response = self.completion(model=model, messages=messages, **kwargs)
        usage = extract_token_usage(response.usage)
        return response, usage


_default_client: Optional[LLMClient] = None


def get_default_client() -> LLMClient:
    """Get or create the default LLM client."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def completion(model: str, messages: List[Dict[str, Any]], **kwargs) -> Any:
    """Module-level completion function using default client."""
    return get_default_client().completion(model=model, messages=messages, **kwargs)
