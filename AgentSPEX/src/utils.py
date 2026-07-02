import copy
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Union


def truncate_message(msg: Dict[str, Any], max_value_len=80) -> Dict[str, Any]:
    if max_value_len <= 3:
        max_value_len = 3
    return (
        str(msg)
        if len(str(msg)) <= max_value_len
        else str(msg)[: max_value_len - 3] + "...[truncated]"
    )


def shorten_values(msg: Union[List[Any], Dict[str, Any]], max_value_len=80):
    def _process(data):
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    result[k] = _process(v)
                else:
                    result[k] = truncate_message(v, max_value_len)
            return result
        elif isinstance(data, list):
            return [_process(item) for item in data]
        else:
            return truncate_message(data, max_value_len)

    return _process(copy.deepcopy(msg))


def json_default(obj: Any):
    try:
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
    except Exception:
        pass
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def print_messages(
    messages: List[Dict[str, Any]], max_value_len=80, num_indents: int = 0
):
    msg = shorten_values(messages, max_value_len)
    print(json.dumps(msg, indent=num_indents, ensure_ascii=False, default=json_default))
    return
