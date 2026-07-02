"""Core data types for the agent framework.

This package contains foundational data types used throughout the framework:
- EffectiveArgs: Immutable execution configuration
- ContextKeys: Standard keys for workflow context dictionaries
- Tokens: Special tokens for agent communication
- Serialization utilities: safe_json_dumps, get_tool_name
"""

from .config import EffectiveArgs
from .context import (CHECKPOINT_KIND, CHECKPOINT_SCHEMA_VERSION, ContextKeys,
                      Tokens)
from .serialization import get_tool_name, safe_json_dumps

__all__ = [
    # Configuration
    "EffectiveArgs",
    # Context
    "ContextKeys",
    "Tokens",
    "CHECKPOINT_KIND",
    "CHECKPOINT_SCHEMA_VERSION",
    # Serialization
    "safe_json_dumps",
    "get_tool_name",
]
