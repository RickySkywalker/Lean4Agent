"""Serialization and tool utilities.

This module provides utility functions for JSON serialization and tool
name extraction that are used throughout the framework.
"""

import json
from pathlib import Path
from typing import Any, Optional


def get_tool_name(tool: Any) -> Optional[str]:
    """Extract the tool name from a tool definition.

    Handles various tool definition formats including:
    - OpenAI function format: {'function': {'name': 'tool_name'}}
    - Simple dict format: {'name': 'tool_name'}
    - Object with name attribute

    Args:
        tool: A tool definition in any supported format

    Returns:
        The tool name as a string, or None if not found

    Example:
        >>> get_tool_name({'function': {'name': 'shell_run'}})
        'shell_run'
        >>> get_tool_name({'name': 'fs_read'})
        'fs_read'
    """
    if isinstance(tool, dict):
        fn = tool.get("function")
        if isinstance(fn, dict):
            return fn.get("name")
        name = getattr(fn, "name", None)
        if isinstance(name, str):
            return name
        mock_name = getattr(fn, "_mock_name", None)
        if mock_name:
            return mock_name
        return name or tool.get("name")
    return getattr(tool, "name", None)


def safe_json_dumps(data: Any, indent: int = 4) -> str:
    """Serialize data to JSON with support for complex types.

    Handles serialization of:
    - Dataclasses (converted to dict)
    - Sets and tuples (converted to list)
    - Path objects (converted to string)
    - Objects with __dict__ (converted to dict)
    - Any other type (converted to string)

    Args:
        data: The data to serialize
        indent: Number of spaces for indentation (default: 4)

    Returns:
        JSON string representation of the data

    Example:
        >>> from dataclasses import dataclass
        >>> @dataclass
        ... class Config:
        ...     name: str
        >>> safe_json_dumps(Config(name='test'))
        '{\\n    "name": "test"\\n}'
    """

    def _default(obj):
        try:
            import dataclasses

            if dataclasses.is_dataclass(obj):
                return dataclasses.asdict(obj)
        except Exception:
            pass
        if isinstance(obj, (set, tuple)):
            return list(obj)
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    return json.dumps(data, indent=indent, default=_default)


def json_default(obj: Any) -> Any:
    """Default JSON serializer for complex types.

    Can be used as the `default` argument to `json.dumps()`.
    Handles:
    - Dataclasses (converted to dict)
    - Sets and tuples (converted to list)
    - Path objects (converted to string)
    - Objects with __dict__ (converted to dict)
    - Any other type (converted to string)

    Args:
        obj: Object to serialize

    Returns:
        Serializable version of the object
    """
    try:
        import dataclasses

        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
    except Exception:
        pass
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def truncate_message(msg: Any, max_value_len: int = 80) -> str:
    """Truncate a message to a maximum length.

    Converts the message to string and truncates if too long,
    appending '...[truncated]' to indicate truncation.

    Args:
        msg: Message to truncate (will be converted to string)
        max_value_len: Maximum length for the output (minimum 3)

    Returns:
        Original string if within limit, or truncated with suffix
    """
    if max_value_len <= 3:
        max_value_len = 3
    msg_str = str(msg)
    if len(msg_str) <= max_value_len:
        return msg_str
    return msg_str[: max_value_len - 3] + "...[truncated]"
