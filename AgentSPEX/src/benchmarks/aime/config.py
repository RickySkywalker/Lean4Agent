"""Configuration and argument parsing for AIME benchmark."""

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["AIMEResult", "parse_args"]

_BENCHMARK_DIR = Path(__file__).parent
_DEFAULT_WORKFLOW = _BENCHMARK_DIR / "aime_agent.yaml"
_DEFAULT_OUTPUT_DIR = f"outputs/aime_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# Available dataset configurations
DATASETS = {
    # "aime24": {
    #     "hf_path": "Maxwell-Jia/AIME_2024",
    #     "configs": [None],  # Single config, no name needed
    #     "split": "train",
    #     "question_field": "Problem",
    #     "answer_field": "Answer",
    #     "id_field": "ID",
    # },
    "aime25": {
        "hf_path": "opencompass/AIME2025",
        "configs": ["AIME2025-I", "AIME2025-II"],
        "split": "test",
        "question_field": "question",
        "answer_field": "answer",
        "id_field": None,  # No ID field; we generate one
    },
    # "aime26": {
    #     "hf_path": "math-ai/aime26",
    #     "configs": [None],
    #     "split": "test",
    #     "question_field": "problem",
    #     "answer_field": "answer",
    #     "id_field": "id",
    # },
}

DATASET_CHOICES = list(DATASETS.keys()) + ["all"]


@dataclass
class AIMEResult:
    """Result of processing a single AIME problem."""

    problem_id: str
    problem: str
    correct_answer: str
    dataset: str = ""  # e.g. "aime24", "aime25-I"
    status: str = "completed"  # completed | failed
    response: str = ""  # Full agent response
    parsed_answer: Optional[str] = None  # Extracted answer
    is_correct: bool = False
    error: Optional[str] = None


def parse_args():
    parser = argparse.ArgumentParser(description="Run AIME benchmark")
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
        help="Limit number of problems to process",
    )
    parser.add_argument(
        "--problem-ids",
        type=str,
        nargs="+",
        help="Specific problem IDs to run (e.g. 2024-I-1 2025-II-3)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="all",
        choices=DATASET_CHOICES,
        help="Which AIME dataset to run (default: all)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation after running problems",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing output dir, skip completed problems",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Per-problem timeout in seconds (default: 180)",
    )
    return parser.parse_args()
