"""
MCP server entrypoint that registers terminal, filesystem, and browser control tools
using the FastMCP framework. All functionality is defined in separate modules
and imported here, then registered via mcp.tool() calls.
"""

import importlib
import inspect
import os
import sys
from functools import wraps
from pathlib import Path

import yaml
from fastmcp import FastMCP

from .utils import tool_log


def _format_function_call(name: str, args: tuple, kwargs: dict) -> str:
    def short_repr(x):
        r = repr(x)
        return r if len(r) <= 20 else r[:17] + "..."

    args_str = ", ".join(short_repr(a) for a in args)
    kwargs_str = ", ".join(f"{k}={short_repr(v)}" for k, v in kwargs.items())
    all_args = ", ".join(filter(None, [args_str, kwargs_str]))
    return f"{name}({all_args})"


def _make_wrapper(func, name):
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                tool_log(_format_function_call(name, args, kwargs))
            except Exception:
                pass
            return await func(*args, **kwargs)

    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                tool_log(_format_function_call(name, args, kwargs))
            except Exception:
                pass
            return func(*args, **kwargs)

    wrapper.__annotations__ = func.__annotations__
    wrapper.__doc__ = func.__doc__
    wrapper.__signature__ = inspect.signature(func)
    return wrapper


def register_public_functions_as_tools(
    module_name: str, tool_log=None, tags: list = None
):
    """
    Registers all public functions from a module as MCP tools.
    Preserves sync vs async function type. Does not add `await` if not originally present.
    Optionally logs tool invocations via tool_log(func_call_string).
    """
    if not tags:
        tags = []
    mod = importlib.import_module(module_name)

    for name, func in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("_") or func.__module__ != module_name:
            continue

        if tool_log:
            wrapper = _make_wrapper(func, name)
            mcp.tool(tags=tags)(wrapper)
        else:
            mcp.tool(tags=tags)(func)


if __name__ == "__main__":
    import os

    # pick up host/port from env with fallbacks
    try:
        host = os.environ.get("MCP_HOST")
        port = int(os.environ.get("MCP_PORT"))
        transport = os.environ.get("MCP_TRANSPORT")
        path = os.environ.get("MCP_BASEPATH")
    except KeyError as e:
        print(f"Missing required environment variable: {e.args[0]}", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP(name="Sandbox Control MCP", version="0.3.0", stateless_http=False)
    tool_config_path = (
        Path(__file__).resolve().parent / "../tools/mcp_server_tool_config.yaml"
    )
    with open(tool_config_path) as f:
        config = yaml.safe_load(f)

    # Register all public functions from the tools modules
    def tool_registry_helper(vm_profile: str = "default"):
        tool_entries = []
        enabled_categories = (
            config.get("vm_profiles", {})
            .get(vm_profile, {})
            .get("enabled_categories", [])
        )
        for category, tools in config["tool_mappings"].items():
            if category in enabled_categories:
                for tool, alias in tools.items():
                    tool_entries.append((f"{category}.{tool}", alias))

        prefix = "sandbox_vm.tools"
        for module_path, tag in tool_entries:
            full_path = f"{prefix}.{module_path}"
            register_public_functions_as_tools(full_path, tool_log, tags=[tag])

    ### One may add tools directory as follows
    ### It registers all public functions from the tools from files with appapriate tags
    ###
    ### tool_registry_helper(
    ###    ("app_control.terminal", "terminal"),
    ###    ("app_control.browser", "browser"),
    ###    ("app_control.file", "filesystem"),
    ### )

    tool_registry_helper()

    mcp.run(transport=transport, host=host, port=port, path=path)
