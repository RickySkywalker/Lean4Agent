"""Argument parsing + plan-directory discovery for the regen runner.

The regen runner is a sibling of `swe_bench_verified` that takes a
directory of evolved task plans (one YAML per instance) and dispatches
each instance to its own plan. The shared bits (`AgentArgs`,
`InstanceResult`, `load_excluded_instances`) are re-exported from the
verified package so callers don't need to import both.
"""

import argparse
import re
from pathlib import Path
from typing import Dict, Optional

from SWE_bench_verified.config import (
    AgentArgs,
    InstanceResult,
    load_excluded_instances,
)

__all__ = [
    "AgentArgs",
    "InstanceResult",
    "load_excluded_instances",
    "parse_args",
    "discover_plans",
    "infer_instance_id",
]


# Filenames look like:
#   passed_workflow_1_django__django-14140_lean.yaml
#   passed_workflow_1_django__django-14140_baseline.yaml
#   <prefix>_<instance_id>_<arm>.yaml
#   <prefix>_<instance_id>.yaml
#
# A SWE-bench instance id is `<repo>__<repo>-<num>` (the `__` separator
# is canonical). The regex below pulls the longest substring that
# matches `<word>__<word>-<word>` between the surrounding underscores.
_INSTANCE_RE = re.compile(
    r"_([A-Za-z0-9.][A-Za-z0-9.\-]*__[A-Za-z0-9.][A-Za-z0-9.\-]*)"
    r"(?:_[A-Za-z0-9_]+)?\.yaml$"
)


def infer_instance_id(yaml_path: Path) -> Optional[str]:
    """Extract the SWE-bench instance id embedded in a plan filename.

    Returns None if the filename doesn't follow the expected
    `<prefix>_<instance_id>[_<arm>].yaml` shape.
    """
    m = _INSTANCE_RE.search(yaml_path.name)
    return m.group(1) if m else None


def discover_plans(plans_dir: Path) -> Dict[str, Path]:
    """Scan a directory of evolved plans, return `{instance_id: yaml_path}`.

    Raises if two YAMLs map to the same instance id (would silently
    pick one, which is a footgun for the smoke-test comparison).
    """
    out: Dict[str, Path] = {}
    for p in sorted(plans_dir.glob("*.yaml")):
        iid = infer_instance_id(p)
        if iid is None:
            continue
        if iid in out:
            raise ValueError(
                f"Multiple plan files map to instance {iid}: "
                f"{out[iid]} and {p}"
            )
        out[iid] = p
    return out


def parse_args():
    """Parse CLI args for the regen runner.

    The arg surface mirrors `swe_bench_verified.parse_args` but
    replaces `--task-plan-file` with `--task-plans-dir` (still
    accepts an optional `--task-plan-file` as a fallback for
    instances that have no per-instance plan).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run SWE-Bench-Verified with per-instance evolved task plans "
            "(one YAML per instance, discovered from --task-plans-dir)."
        )
    )
    parser.add_argument(
        "--task-plans-dir",
        type=str,
        required=True,
        help=(
            "Directory of evolved task plans, one YAML per instance. "
            "Filename must contain the instance id, e.g. "
            "passed_workflow_1_django__django-14140_lean.yaml."
        ),
    )
    parser.add_argument(
        "--task-plan-file",
        type=str,
        default=None,
        help=(
            "Optional fallback YAML used when --task-plans-dir has no "
            "plan for a particular instance. If omitted, instances "
            "without a plan are skipped."
        ),
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="HuggingFace dataset name or local path.",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        help="Dataset split (default: test).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5",
        help="Model id passed to the agent.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Directory to write per-instance logs, diffs, predictions.jsonl.",
    )
    parser.add_argument(
        "--instance-ids",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Optional whitelist of instance ids (space- or "
            "comma-separated). Defaults to all instances with a "
            "matching plan in --task-plans-dir."
        ),
    )
    parser.add_argument("--save-logs", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--dashboard-port", type=int, default=5050)
    parser.add_argument("--dashboard-no-browser", action="store_true")
    parser.add_argument("--dashboard-keep", action="store_true")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Max instances to run in parallel (default: 1, sequential).",
    )
    parser.add_argument(
        "--exclude-file",
        type=str,
        default=str(
            Path(__file__).parent.parent
            / "swe_bench_verified"
            / "excluded_instances.txt"
        ),
        help=(
            "Instance-id exclude list (defaults to the shared list under "
            "swe_bench_verified/)."
        ),
    )
    parser.add_argument("--no-exclude", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of instances processed (after filters).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Skip instances whose `<id>_agent_events.log` already ends "
            "with workflow_end."
        ),
    )
    parser.add_argument(
        "--per-instance-timeout-sec",
        type=int,
        default=10800,
        help=(
            "Per-instance watchdog in seconds (default: 10800 = 3 hours). "
            "If a SWE agent runs longer, its container is closed and a "
            "synthetic workflow_end event is appended to its events log so "
            "downstream parsers see a terminated trace. The instance is "
            "marked success=False with error='timeout_<sec>s'."
        ),
    )
    parser.add_argument(
        "--idle-timeout-sec",
        type=int,
        default=7200,
        help=(
            "Idle-watchdog in seconds (default: 7200 = 2 hours). Fires when "
            "an instance's event log stops growing, regardless of total "
            "runtime. Complements --per-instance-timeout-sec. Pass 0 to "
            "disable."
        ),
    )
    args = parser.parse_args()

    # Accept comma- or space-separated --instance-ids
    if args.instance_ids:
        flat: list = []
        for chunk in args.instance_ids:
            flat.extend(s.strip() for s in chunk.split(",") if s.strip())
        args.instance_ids = flat

    return args
