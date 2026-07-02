"""SWE-Bench-Verified benchmark runner package.

This package provides tools for running AI agents on SWE-Bench software engineering tasks.

Modules:
    config: Configuration, constants, and argument parsing
    instance: Instance processing and patch extraction
    shell_utils: Shell execution and logging utilities
    run: Main entry point and orchestration
"""

from .config import (AgentArgs, InstanceResult,
                                                  load_excluded_instances,
                                                  parse_args)
from .instance import (prepare_yaml_for_instance,
                                                    run_instance,
                                                    save_patch_to_jsonl)
from .shell_utils import (
    Logger, execute_command_via_shell_run)

__all__ = [
    # Config
    "AgentArgs",
    "InstanceResult",
    "parse_args",
    "load_excluded_instances",
    # Instance
    "run_instance",
    "save_patch_to_jsonl",
    "prepare_yaml_for_instance",
    # Utils
    "execute_command_via_shell_run",
    "Logger",
]
