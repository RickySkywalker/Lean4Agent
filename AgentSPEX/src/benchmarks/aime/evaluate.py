"""Evaluation for AIME benchmark using math-verify.

Uses the math-verify library (https://github.com/huggingface/Math-Verify)
for robust mathematical answer verification, supporting LaTeX parsing and
symbolic comparison.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from math_verify import parse, verify


def parse_answer(response: str) -> Optional[str]:
    r"""Extract the answer from the model response using math-verify.

    Tries to parse the last \boxed{} expression. Falls back to extracting
    raw \boxed{} content if math-verify parsing fails.
    """
    # First try math-verify's robust parser
    try:
        parsed = parse(response)
        if parsed:
            # Return string representation for logging; actual comparison uses verify()
            return str(parsed[-1]).strip()
    except Exception:
        pass

    # Fallback: manually extract last \boxed{}
    results = _extract_boxed(response)
    if results:
        return results[-1].strip()

    return None


def _extract_boxed(text: str) -> list[str]:
    r"""Extract all \boxed{...} contents, handling nested braces."""
    results = []
    prefix = r"\boxed{"
    i = 0
    while i < len(text):
        idx = text.find(prefix, i)
        if idx == -1:
            break
        start = idx + len(prefix)
        depth = 1
        j = start
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        if depth == 0:
            results.append(text[start : j - 1])
        i = j
    return results


def _normalize_ground_truth(ground_truth: str) -> str:
    """Normalize AIME ground truth to a plain integer string.

    AIME answers are always integers 0-999, but some datasets include
    formatting like '336^\\circ'. Extract the integer.
    """
    import re

    m = re.search(r"\d+", ground_truth)
    return m.group(0) if m else ground_truth


def verify_answer(model_response: str, ground_truth: str) -> bool:
    """Verify if the model's answer matches the ground truth using math-verify.

    Args:
        model_response: The full model response text.
        ground_truth: The ground truth answer (string of an integer for AIME).

    Returns:
        True if the answer is correct, False otherwise.
    """
    gt_normalized = _normalize_ground_truth(ground_truth)

    try:
        gold = parse(gt_normalized)
        pred = parse(model_response)
        if gold and pred:
            return verify(gold, pred)
    except Exception:
        pass

    # Fallback: exact string match on extracted boxed answer
    parsed = _extract_boxed(model_response)
    if parsed:
        # AIME answers are integers; normalize by stripping leading zeros
        try:
            return int(parsed[-1].strip()) == int(gt_normalized.strip())
        except (ValueError, TypeError):
            pass

    return False


def evaluate(
    runs_dir: str,
    eval_dir: str = "evals",
) -> dict:
    """Compute accuracy over completed AIME results."""
    runs_path = Path(runs_dir)
    output_dir = Path(eval_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(runs_path.glob("*.json"))
    if not json_files:
        print(f"No JSON files in {runs_path}")
        return {}

    results: List[dict] = []
    for json_path in json_files:
        with json_path.open("r") as f:
            results.append(json.load(f))

    completed = [r for r in results if r.get("status") == "completed"]
    total = len(completed)

    if total == 0:
        print("No completed problems to evaluate.")
        return {}

    correct = sum(1 for r in completed if r.get("is_correct", False))
    accuracy = round(correct / total, 4)

    # Refusal rate (could not parse an answer)
    refused = sum(1 for r in completed if r.get("parsed_answer") is None)

    # Per-dataset breakdown
    dataset_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in completed:
        ds = r.get("dataset", "unknown")
        dataset_stats[ds]["total"] += 1
        if r.get("is_correct", False):
            dataset_stats[ds]["correct"] += 1

    per_dataset = {}
    for ds, stats in sorted(dataset_stats.items()):
        ds_acc = (
            round(stats["correct"] / stats["total"], 4) if stats["total"] > 0 else 0.0
        )
        per_dataset[ds] = {
            "total": stats["total"],
            "correct": stats["correct"],
            "accuracy": ds_acc,
        }

    summary = {
        "total_completed": total,
        "total_failed": len(results) - total,
        "correct": correct,
        "accuracy": accuracy,
        "refused": refused,
        "refusal_rate": round(refused / total, 4) if total > 0 else 0.0,
        "per_dataset": per_dataset,
        "evaluation_date": datetime.now().date().isoformat(),
    }

    summary_path = output_dir / "evaluation_summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nResults ({total} problems):")
    print(f"  Accuracy: {accuracy:.1%} ({correct}/{total})")
    if refused:
        print(f"  Refusals: {refused}/{total}")
    print(f"\n  Per-dataset breakdown:")
    for ds, stats in sorted(per_dataset.items()):
        print(
            f"    {ds}: {stats['accuracy']:.1%} ({stats['correct']}/{stats['total']})"
        )
    print(f"Summary saved to {summary_path}")

    return summary
