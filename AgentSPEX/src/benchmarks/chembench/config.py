"""Configuration and argument parsing for ChemBench benchmark."""

import argparse
from datetime import datetime
from pathlib import Path

__all__ = ["parse_args"]

_BENCHMARK_DIR = Path(__file__).parent
_DEFAULT_WORKFLOW = _BENCHMARK_DIR / "chembench_agent.yaml"
_DEFAULT_OUTPUT_DIR = f"outputs/chembench_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def parse_args():
    parser = argparse.ArgumentParser(description="Run ChemBench benchmark")
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
        "--topics",
        type=str,
        nargs="+",
        default=None,
        help="Specific topics to evaluate (default: all)",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation after running queries",
    )
    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="List available topics and exit",
    )
    parser.add_argument(
        "--sample-per-topic",
        type=int,
        default=None,
        help="Randomly sample N questions per topic (default: all)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling (default: 42). Use with --sample-per-topic for reproducible runs.",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Maximum number of parallel LLM calls (default: 1)",
    )
    return parser.parse_args()
