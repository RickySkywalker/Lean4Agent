"""SWE-Bench regen runner package.

Thin wrapper around `benchmarks.swe_bench_verified` that runs each
instance with its own per-instance evolved YAML task plan instead of a
single shared plan.

Public API mirrors the verified package; the only addition is
`discover_plans(plans_dir)` which builds the
`instance_id -> yaml_path` map from a directory of evolved plans.
"""

from .config import (
    AgentArgs,
    InstanceResult,
    discover_plans,
    infer_instance_id,
    load_excluded_instances,
    parse_args,
)

__all__ = [
    "AgentArgs",
    "InstanceResult",
    "parse_args",
    "load_excluded_instances",
    "discover_plans",
    "infer_instance_id",
]
