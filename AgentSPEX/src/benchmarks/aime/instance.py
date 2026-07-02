"""Per-problem instance processing for AIME benchmark."""

import json
from pathlib import Path

from benchmarks.aime.config import AIMEResult


def save_result(result: AIMEResult, output_dir: Path) -> None:
    """Save an AIME result as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{result.problem_id}.json"

    data = {
        "problem_id": result.problem_id,
        "problem": result.problem,
        "correct_answer": result.correct_answer,
        "dataset": result.dataset,
        "status": result.status,
        "response": result.response,
        "parsed_answer": result.parsed_answer,
        "is_correct": result.is_correct,
    }
    if result.error:
        data["error"] = result.error

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
