"""Configuration and argument parsing for WritingBench benchmark."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["WritingResult", "parse_args"]

_BENCHMARK_DIR = Path(__file__).parent
_DEFAULT_WORKFLOW = _BENCHMARK_DIR / "writing_bench_agent.yaml"
_DEFAULT_OUTPUT_DIR = (
    f"outputs/writing_bench_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)

_GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/X-PLUG/WritingBench/main/benchmark_query"
)


@dataclass
class WritingResult:
    """Result of processing a single WritingBench query."""

    index: int
    query: str
    domain1: str = ""
    domain2: str = ""
    lang: str = ""
    status: str = "completed"  # completed | failed
    response: str = ""
    error: Optional[str] = None


def parse_args():
    parser = argparse.ArgumentParser(description="Run WritingBench benchmark")
    parser.add_argument(
        "--workflow-file",
        type=str,
        default=str(_DEFAULT_WORKFLOW),
        help="Path to YAML workflow file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use (overrides workflow config). Defaults to workflow's model.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=_DEFAULT_OUTPUT_DIR,
        help="Directory to save results",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Maximum parallel queries (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of queries to process",
    )
    parser.add_argument(
        "--query-indices",
        type=int,
        nargs="+",
        help="Specific query indices to run",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="claude-sonnet-4-5",
        help="Model for evaluation judging (default: claude-sonnet-4-5)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation after running queries",
    )
    parser.add_argument(
        "--save-logs",
        action="store_true",
        help="Save per-instance agent logs (full log + structured events)",
    )
    parser.add_argument(
        "--max-parallel-eval",
        type=int,
        default=1,
        help="Maximum parallel evaluation judges (default: 1)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress agent logs on terminal (still writes to log files with --save-logs). "
        "Use scripts/dashboard.py to view logs.",
    )
    return parser.parse_args()
