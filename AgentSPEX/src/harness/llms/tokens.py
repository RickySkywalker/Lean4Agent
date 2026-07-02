import os
from functools import lru_cache
from typing import Any, Dict, List

import litellm
import tiktoken

litellm.suppress_debug_info = True


def extract_token_usage(usage) -> Dict[str, int]:
    if not usage:
        return {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
        }

    reasoning_tokens = int(
        getattr(usage, "reasoning_tokens", 0)
        or getattr(
            getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0
        )
        or getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
        or 0
    )

    return {
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "reasoning_tokens": reasoning_tokens,
    }


# Fallback for models not in LiteLLM's registry (e.g. local/vLLM deployments)
_CONTEXT_LIMITS_FALLBACK = {
    # OpenAI legacy
    "gpt-4-32k": 32_768,
    "o1-mini": 128_000,
    "o1-preview": 128_000,
    # Anthropic legacy
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-5-sonnet-20240620": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    # Google Gemini legacy
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-pro": 32_000,
    # Mistral models
    "mistral-large": 128_000,
    "mistral-medium": 32_000,
    "mistral-small": 32_000,
    "mixtral-8x7b": 32_000,
    "codestral": 32_000,
    # Meta Llama models (common vLLM deployments)
    "llama-3.1-8b-instruct": 128_000,
    "llama-3.1-70b-instruct": 128_000,
    "llama-3.1-405b-instruct": 128_000,
    "llama-3.2-1b-instruct": 128_000,
    "llama-3.2-3b-instruct": 128_000,
    "llama-3.3-70b-instruct": 128_000,
    # Qwen models
    "qwen-2.5-72b-instruct": 128_000,
    "qwen-2.5-32b-instruct": 128_000,
    "qwen-2.5-coder-32b-instruct": 128_000,
    # DeepSeek models
    "deepseek-coder": 64_000,
    "deepseek-r1": 64_000,
}


@lru_cache(maxsize=64)
def get_model_context_limit(model: str) -> int:
    """Return context window size in tokens for a model.

    Tries LiteLLM's model registry first, then falls back to a local dict for models not covered
    (e.g. local/vLLM deployments).
    """
    try:
        info = litellm.get_model_info(model)
        if info.get("max_input_tokens"):
            return info["max_input_tokens"]
    except Exception:
        pass

    # Strip provider prefix for fallback dict lookup (e.g. 'openai/gpt-4o' -> 'gpt-4o')
    lookup = model.split("/", 1)[1] if "/" in model else model

    if lookup in _CONTEXT_LIMITS_FALLBACK:
        return _CONTEXT_LIMITS_FALLBACK[lookup]

    model_lower = lookup.lower()
    for key, value in _CONTEXT_LIMITS_FALLBACK.items():
        if key.lower() == model_lower:
            return value

    return 128_000


def _get_tokenizer(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_message_tokens(messages: List[Dict[str, Any]], model: str) -> int:
    """Count tokens in a message list for the given model.

    Uses litellm.token_counter when available — routes to the correct
    tokenizer per provider (Anthropic, OpenAI, etc.) for accurate counts
    across model families.  Falls back to tiktoken (cl100k_base) which is
    within ~10-20% for non-OpenAI models, acceptable for threshold monitoring.
    """
    if not messages:
        return 0

    # Primary: litellm.token_counter — accurate for all supported providers
    try:
        count = litellm.token_counter(model=model, messages=messages)
        if count and count > 0:
            return count
    except Exception:
        pass

    # Fallback: tiktoken
    try:
        tokenizer = _get_tokenizer(model)
        total = 0
        for message in messages:
            for key, value in message.items():
                if isinstance(value, str):
                    total += len(tokenizer.encode(value))
                elif key == "tool_calls" and value:
                    for tool_call in value:
                        fn = getattr(tool_call, "function", None)
                        if fn:
                            total += len(tokenizer.encode(fn.name))
                            total += len(tokenizer.encode(fn.arguments))
        return total
    except Exception as e:
        if bool(os.environ.get("CS_DEBUG_TOKEN_COUNT")):
            print(f"Token counting failed: {e}")
        return -1
