"""Configuration and argument parsing for ELAIPBench benchmark."""

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["ELAIPBenchResult", "parse_args"]

_BENCHMARK_DIR = Path(__file__).parent
_DEFAULT_WORKFLOW = _BENCHMARK_DIR / "elaipbench_agent.yaml"
_DEFAULT_OUTPUT_DIR = f"outputs/elaipbench_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class ELAIPBenchResult:
    """Result of processing a single ELAIPBench question."""

    question_id: int
    question: str
    question_type: str  # SA-MCQ or MA-MCQ
    correct_answer: str  # e.g. "B" or "ABC"
    paper_id: int = 0
    status: str = "completed"  # completed | failed
    response: str = ""  # Full agent response
    parsed_answer: Optional[str] = None  # Extracted answer letters
    is_correct: bool = False
    error: Optional[str] = None


def parse_args():
    parser = argparse.ArgumentParser(description="Run ELAIPBench benchmark")
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
        help="Limit number of questions to process",
    )
    parser.add_argument(
        "--question-ids",
        type=int,
        nargs="+",
        help="Specific question indices to run",
    )
    parser.add_argument(
        "--question-type",
        type=str,
        choices=["SA-MCQ", "MA-MCQ"],
        default=None,
        help="Filter by question type (default: run all)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation after running queries",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help=(
            "Path to a local dataset (directory containing test.parquet, or a "
            "parquet file). If omitted, the full ELAIPBench is fetched from "
            "HuggingFace."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume a previous run: skip questions whose runs/<id>.json already "
            "exists with status='completed'. Failed/incomplete questions are "
            "re-run."
        ),
    )
    return parser.parse_args()
