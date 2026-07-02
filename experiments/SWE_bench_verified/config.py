"""Configuration, constants, and argument parsing for SWE-Bench runner."""

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set

__all__ = [
    # Dataclasses
    "AgentArgs",
    "InstanceResult",
    # Functions
    "parse_args",
    "load_excluded_instances",
]


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class AgentArgs:
    """Arguments for the YAML agent."""

    workflow_file: str
    model: str
    problem_statement: str
    temperature: float = 0.7
    max_tool_calls_per_step: int = 200
    max_tokens_per_step: int = 120_000


@dataclass
class InstanceResult:
    """Result of processing a single SWE-Bench instance."""

    instance_id: str
    success: bool
    patch: str = ""
    error: Optional[str] = None


# ============================================================================
# ARGUMENT PARSING
# ============================================================================


def parse_args():
    """Parse command-line arguments for the SWE-Bench runner."""
    # Get the full path to the repo root
    repo_root = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
    default_workflow = (
        repo_root / "experiments/SWE_bench_verified/swe_bench_agent.yaml"
    )

    parser = argparse.ArgumentParser(description="Run SWE-Bench-Verified benchmark")
    parser.add_argument(
        "--dataset",
        type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="HuggingFace dataset to use (default: princeton-nlp/SWE-bench_Verified)",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="test",
        help="Split of the dataset to run (default: test, options: test, verified, lite)",
    )
    parser.add_argument(
        "--workflow-file",
        type=str,
        default=str(default_workflow),
        help="Path to YAML workflow file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5",
        help="Model to use for the agent",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs/swe_bench_results",
        help="Directory to save results and patches",
    )
    parser.add_argument(
        "--instance-ids",
        type=str,
        nargs="+",
        help="List of specific instance IDs to run (e.g., django__django-10880 flask__flask-5063)",
    )
    parser.add_argument(
        "--save-logs",
        action="store_true",
        help="Save all print logs to a file for each instance",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start the dashboard and point it at the output directory",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=5050,
        help="Dashboard port (default: 5050)",
    )
    parser.add_argument(
        "--dashboard-no-browser",
        action="store_true",
        help="Do not auto-open the dashboard in a browser",
    )
    parser.add_argument(
        "--dashboard-keep",
        action="store_true",
        help="Keep the dashboard running after the run completes",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Maximum number of instances to run in parallel (default: 1, sequential)",
    )
    parser.add_argument(
        "--exclude-file",
        type=str,
        default=str(Path(__file__).parent / "excluded_instances.txt"),
        help="Path to file containing instance IDs to exclude (one per line)",
    )
    parser.add_argument(
        "--no-exclude",
        action="store_true",
        help="Ignore the exclude file and run all instances",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of instances to process",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previous run: skip instances whose events log ends with workflow_end",
    )
    parser.add_argument(
        "--per-instance-timeout-sec",
        type=int,
        default=7200,
        help="Hard wall-clock deadline per instance (seconds). When exceeded, "
        "the watchdog tears down the container and writes a synthetic workflow_end; "
        "if the worker stays wedged past WATCHDOG_GRACE_SEC it is abandoned and "
        "recorded as a local timeout failure (the rest of the run keeps going, "
        "--resume can revisit it). Set to 0 to disable. Default: 7200 (2h).",
    )
    parser.add_argument(
        "--idle-timeout-sec",
        type=int,
        default=7200,
        help="Fire the watchdog if an instance's event log stops growing for this "
        "many seconds (catches hangs that the agent thread cannot recover from). "
        "Set to 0 to disable. Default: 7200 (2h).",
    )
    args = parser.parse_args()
    return args


def load_excluded_instances(exclude_file: str) -> Set[str]:
    """
    Load excluded instance IDs from a file.

    Args:
        exclude_file: Path to file containing instance IDs to exclude

    Returns:
        Set of instance IDs to exclude
    """
    excluded = set()
    path = Path(exclude_file)

    if not path.exists():
        return excluded

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            excluded.add(line)

    return excluded
