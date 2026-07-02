"""Shared evaluation utilities for ChemBench benchmark.

Computes per-topic and overall statistics from ChemBench report dicts.
Used by both run.py (agent) and run_baseline.py (baseline) to ensure
identical evaluation logic.
"""

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

_MCQ_REGEX = re.compile(
    r"(?:\[ANSWER\]|\[ANS\]|<ANS>|<ANSWER>|<ans>)"
    r"\s*([A-Z](?:,\s*[A-Z])*)\s*"
    r"(?:\..*?|,.*?)?"
    r"(?:\[/?ANSWER\]|\[/ANS\]|</ANS>|</ANSWER>|</ans>)",
    re.DOTALL,
)
_FLOAT_REGEX = re.compile(
    r"\[ANSWER\][\s\n]*(.*?)[\s\n]*\[/?ANSWER\]",
    re.DOTALL,
)


def extract_answer(response: str) -> str | None:
    """Extract the answer from [ANSWER]...[/ANSWER] tags in the response."""
    match = _FLOAT_REGEX.search(response)
    return match.group(1).strip() if match else None


def extract_mcq_answer(response: str) -> list[str]:
    """Extract MCQ letter answer(s) from response using ChemBench's regex.

    Handles formats like [ANSWER]A[/ANSWER], [ANSWER]A, B[/ANSWER],
    [ANSWER]C. some text[/ANSWER] (ignores text after the letter).

    Returns:
        List of uppercase letter strings, e.g. ["A"] or ["A", "B"].
        Empty list if no match.
    """
    match = _MCQ_REGEX.search(response)
    if match:
        letters_str = match.group(1)
        return [l.strip() for l in letters_str.split(",")]
    return []


def score_answer(
    response: str,
    target_scores: dict | None,
    target: str | None,
) -> dict:
    """Score model response against ground truth.

    Uses ChemBench's regex patterns to extract answers:
    - MCQ: extracts letter(s) from [ANSWER]A[/ANSWER] or [ANSWER]A, B[/ANSWER],
      ignoring trailing text like ". some option text"
    - Numeric: extracts content from [ANSWER]...[/ANSWER], parses as float

    Args:
        response: Full model response text (with [ANSWER] tags).
        target_scores: MCQ target scores dict, e.g. {"NaCl": 1, "KCl": 0}.
            None for numeric questions.
        target: Numeric target value as string. None for MCQ questions.

    Returns:
        Metrics dict compatible with is_correct().
    """
    if not response:
        return {"all_correct": 0}

    if target_scores and isinstance(target_scores, dict):
        # MCQ: extract letters using ChemBench's MCQ regex
        keys = list(target_scores.keys())
        scores = list(target_scores.values())
        answer_to_score = {chr(65 + i): scores[i] for i in range(len(keys))}
        correct_letters = {k for k, v in answer_to_score.items() if v == 1}

        found_letters = set(extract_mcq_answer(response))

        missed = len(correct_letters - found_letters)
        extra = len(found_letters - correct_letters)
        hamming = (missed + extra) / len(correct_letters) if correct_letters else 1
        return {"all_correct": 1 if hamming == 0 else 0, "hamming": hamming}
    else:
        # Numeric: extract content from [ANSWER] tags, parse as float
        answer = extract_answer(response)
        if not answer:
            return {"all_correct": 0}

        target = target or ""
        try:
            target_val = float(target)
            answer_val = float(answer)
            mae_val = abs(answer_val - target_val)
            tolerance = 0.01 * abs(target_val) if target_val != 0 else 1e-8
            return {
                "all_correct": 1 if mae_val <= tolerance else 0,
                "mae": mae_val,
            }
        except (ValueError, TypeError):
            return {"all_correct": 1 if answer.strip() == str(target).strip() else 0}


def extract_metrics(report: dict[str, Any]) -> dict[str, Any]:
    """Extract metrics dict from a ChemBench report dict.

    Args:
        report: A single question's report dict (from prompter.report().model_dump()
                or from benchmark.bench() results).

    Returns:
        Metrics dict, or empty dict if not found.
    """
    results = report.get("results", [])
    if results and isinstance(results[0], dict):
        return results[0].get("metrics", {})
    return {}


def is_correct(report: dict[str, Any]) -> bool:
    """Check if a question was answered correctly.

    Reads all_correct from metrics (computed by score_answer).

    Args:
        report: A single question's report dict.

    Returns:
        True if the answer is correct.
    """
    metrics = extract_metrics(report)
    return metrics.get("all_correct", 0) == 1


def compute_topic_stats(
    results: list[dict[str, Any]],
    topic_key: str = "topic",
) -> dict[str, dict[str, Any]]:
    """Compute per-topic accuracy statistics.

    Args:
        results: List of result dicts, each must have `topic_key` and either
                 a "report" sub-dict or top-level "results" with metrics.
        topic_key: Key name for the topic field in each result dict.

    Returns:
        Dict mapping topic name -> {correct, total, accuracy}.
    """
    topic_stats: dict[str, dict[str, Any]] = {}

    for r in results:
        tn = r.get(topic_key, "unknown")
        if tn not in topic_stats:
            topic_stats[tn] = {"correct": 0, "total": 0}
        topic_stats[tn]["total"] += 1

        report = r.get("report", r)
        if is_correct(report):
            topic_stats[tn]["correct"] += 1

    for ts in topic_stats.values():
        ts["accuracy"] = round(ts["correct"] / ts["total"], 4) if ts["total"] > 0 else 0

    return topic_stats


def compute_overall_stats(
    topic_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute overall accuracy from per-topic stats.

    Args:
        topic_stats: Output of compute_topic_stats().

    Returns:
        Dict with total_completed, correct, accuracy.
    """
    total_correct = sum(ts["correct"] for ts in topic_stats.values())
    total_completed = sum(ts["total"] for ts in topic_stats.values())
    accuracy = total_correct / total_completed if total_completed > 0 else 0

    return {
        "total_completed": total_completed,
        "correct": total_correct,
        "accuracy": round(accuracy, 4),
    }


def compute_detailed_topic_metrics(
    results: list[dict[str, Any]],
    topic_key: str = "topic",
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute detailed per-topic metric aggregations (mean, std, count).

    Mirrors chembench.metrics.calculate_topic_metrics but works on our
    result format.

    Args:
        results: List of result dicts.
        topic_key: Key name for the topic field.

    Returns:
        Dict mapping topic -> metric_name -> {mean, std, count}.
    """
    from collections import defaultdict

    topic_metrics: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for r in results:
        tn = r.get(topic_key, "unknown")
        report = r.get("report", r)
        metrics = extract_metrics(report)

        if not metrics:
            topic_metrics[tn]["all_correct"].append(0)
        else:
            for name, value in metrics.items():
                if isinstance(value, bool):
                    topic_metrics[tn][name].append(int(value))
                elif isinstance(value, (int, float)) and not math.isnan(value):
                    topic_metrics[tn][name].append(value)

    result_metrics = {}
    for tn, metrics_dict in topic_metrics.items():
        result_metrics[tn] = {}
        for metric_name, values in metrics_dict.items():
            valid = [v for v in values if not math.isnan(v)]
            if valid:
                result_metrics[tn][metric_name] = {
                    "mean": float(np.mean(valid)),
                    "std": float(np.std(valid)) if len(valid) > 1 else 0.0,
                    "count": len(valid),
                }

    return result_metrics


def build_eval_summary(
    results: list[dict[str, Any]],
    mode: str,
    model: str,
    topic_key: str = "topic",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete evaluation summary dict.

    Args:
        results: List of result dicts.
        mode: "baseline" or "agent".
        model: Model name string.
        topic_key: Key for topic field in results.
        extra: Additional fields to include (e.g., usage stats).

    Returns:
        Complete evaluation summary dict.
    """
    topic_stats = compute_topic_stats(results, topic_key=topic_key)
    overall = compute_overall_stats(topic_stats)

    # Collect wrong question identifiers
    wrong_names = []
    for r in results:
        report = r.get("report", r)
        if not is_correct(report):
            name = r.get("name", report.get("name", ""))
            wrong_names.append(name)

    summary = {
        "mode": mode,
        "model": model,
        **overall,
        "topic_stats": topic_stats,
        "wrong_names": wrong_names,
    }

    if extra:
        summary.update(extra)

    return summary


def save_eval_summary(
    eval_summary: dict[str, Any],
    output_dir: str | Path,
) -> Path:
    """Save evaluation summary to output_dir/evals/evaluation_summary.json.

    Args:
        eval_summary: Evaluation summary dict.
        output_dir: Base output directory.

    Returns:
        Path to the saved file.
    """
    eval_dir = Path(output_dir) / "evals"
    eval_dir.mkdir(parents=True, exist_ok=True)
    eval_path = eval_dir / "evaluation_summary.json"
    with eval_path.open("w") as f:
        json.dump(eval_summary, f, indent=2, ensure_ascii=False)
    return eval_path


def print_summary(eval_summary: dict[str, Any]) -> None:
    """Print a formatted evaluation summary to stdout.

    Args:
        eval_summary: Evaluation summary dict from build_eval_summary().
    """
    mode = eval_summary.get("mode", "unknown").upper()
    total = eval_summary["total_completed"]
    correct = eval_summary["correct"]
    accuracy = eval_summary["accuracy"]
    topic_stats = eval_summary.get("topic_stats", {})

    print(f"\n{'='*60}")
    print(f"{mode} Results: {total} tasks completed")
    print(f"Accuracy: {correct}/{total} ({accuracy:.1%})")
    for tn, ts in sorted(topic_stats.items()):
        print(f"  {tn}: {ts['correct']}/{ts['total']} ({ts['accuracy']:.1%})")
    print(f"{'='*60}")
