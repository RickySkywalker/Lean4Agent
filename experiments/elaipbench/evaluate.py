"""Evaluation for ELAIPBench benchmark - accuracy-based scoring.

Handles both SA-MCQ (single answer) and MA-MCQ (multiple answer) questions.
For SA-MCQ: exact match on single letter.
For MA-MCQ: exact match on the set of letters.
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def parse_answer(response: str, question_type: str) -> Optional[str]:
    """Extract answer letter(s) from the agent's response.

    For SA-MCQ: returns a single letter like "B".
    For MA-MCQ: returns sorted letters like "ABC".
    """
    if question_type == "SA-MCQ":
        return _parse_single_answer(response)
    else:
        return _parse_multi_answer(response)


_VALID_LETTERS = {"A", "B", "C", "D"}


def _strip_json_wrapper(response: str) -> str:
    """If the response is a JSON object whose only value is the answer
    (e.g. `{"final_response": "A"}` or `{"answer": "AC"}`), return the
    inner string. Otherwise return the response unchanged. Models often
    wrap the final letter(s) in JSON despite a "bare letter" instruction —
    treating the wrapper as transparent recovers the real answer."""
    s = response.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return response
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return response
    if not isinstance(obj, dict) or not obj:
        return response
    # Take the FIRST string value; usually there's only one.
    for v in obj.values():
        if isinstance(v, str):
            return v
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            # ["A","C"] → "AC"
            return "".join(v)
    return response


def _parse_single_answer(response: str) -> Optional[str]:
    """Extract a single answer letter (A/B/C/D) from the response."""
    valid = _VALID_LETTERS

    # 0. JSON-wrapper fallthrough — `{"final_response": "A"}` etc.
    unwrapped = _strip_json_wrapper(response)

    # 1. Bare-letter response: the entire response stripped is a single A-D.
    s = unwrapped.strip()
    if s in valid:
        return s

    # 2. Last non-empty line is a single A-D (or "(A)" / "A." / "A)").
    for line in reversed(unwrapped.splitlines()):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^[\(\[]?([A-D])[\)\].\s]*$", line)
        if m and m.group(1) in valid:
            return m.group(1)
        break  # only check the last non-empty line

    # 3. Phrase-based patterns (canonical answer formats).
    patterns = [
        r"answer is \((.)\)",
        r"Answer: \((.)\)",
        r"answer: \((.)\)",
        r"answer is ([A-D])\b",
        r"Answer: ([A-D])\b",
        r"\banswer\s*[:=]\s*([A-D])\b",
        r"\boption\s+([A-D])\s+is\s+(?:correct|right|the answer)",
    ]
    for pattern in patterns:
        match = re.search(pattern, unwrapped)
        if match and match.group(1) in valid:
            return match.group(1)

    # 4. Fallback: last "(X)" pattern in the response.
    matches = re.findall(r"\(([A-D])\)", unwrapped)
    if matches:
        return matches[-1]

    return None


def _parse_multi_answer(response: str) -> Optional[str]:
    """Extract multiple answer letters from the response.

    Returns sorted letters as a string, e.g. "ABC".
    """
    valid = _VALID_LETTERS

    # 0. JSON-wrapper fallthrough.
    unwrapped = _strip_json_wrapper(response)

    # 1. Bare-letter-set response: entire response is letters from {A,B,C,D},
    #    optionally with separators (commas, spaces). E.g. "AC", "A,C", "A C".
    s = unwrapped.strip()
    bare = re.sub(r"[\s,;]+", "", s)
    if bare and len(bare) <= 4 and all(ch in valid for ch in bare):
        letters = set(bare)
        if letters <= valid:
            return "".join(sorted(letters))

    # 2. Last non-empty line is a letter set ("AC", "(A)(C)", "A, C", etc.).
    for line in reversed(unwrapped.splitlines()):
        line = line.strip()
        if not line:
            continue
        # Strip parens / commas / whitespace, see if remainder is a letter run.
        cleaned = re.sub(r"[\(\)\[\]\s,;]+", "", line)
        if cleaned and len(cleaned) <= 4 and all(ch in valid for ch in cleaned):
            letters = set(cleaned)
            if letters <= valid:
                return "".join(sorted(letters))
        break

    # 3. "The correct answers are (A, B, C)" or "(A, B, C)"
    match = re.search(r"answers? (?:are|is) \(([A-D](?:\s*,\s*[A-D])*)\)", unwrapped)
    if match:
        letters = set(re.findall(r"[A-D]", match.group(1)))
        if letters and letters <= valid:
            return "".join(sorted(letters))

    # 4. "answers are A, B, C" or "answers are A, B and C"
    match = re.search(r"answers? (?:are|is)\s+([A-D](?:\s*[,and]+\s*[A-D])*)", unwrapped)
    if match:
        letters = set(re.findall(r"[A-D]", match.group(1)))
        if letters and letters <= valid:
            return "".join(sorted(letters))

    # 5. "(A)(B)(C)" or "(A), (B), (C)" — at least 2 paren-letters near end.
    tail = unwrapped[-300:] if len(unwrapped) > 300 else unwrapped
    matches = re.findall(r"\(([A-D])\)", tail)
    if len(matches) >= 2:
        letters = set(matches)
        if letters <= valid:
            return "".join(sorted(letters))

    # 6. Consecutive capital letters "ABC" near end.
    match = re.search(r"\b([A-D]{2,4})\b", tail)
    if match:
        letters = set(match.group(1))
        if letters <= valid:
            return "".join(sorted(letters))

    return None


def evaluate(
    runs_dir: str,
    eval_dir: str = "evals",
) -> dict:
    """Compute accuracy over completed ELAIPBench results."""
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
    failed_results = [r for r in results if r.get("status") != "completed"]
    wrong_results = [r for r in completed if not r.get("is_correct", False)]

    failed_ids = [r.get("question_id") for r in failed_results]
    wrong_ids = [r.get("question_id") for r in wrong_results]
    correct_ids = [
        r.get("question_id")
        for r in completed
        if r.get("is_correct", False) and "question_id" in r
    ]

    if total == 0:
        print("No completed questions to evaluate.")
        return {}

    correct = sum(1 for r in completed if r.get("is_correct", False))
    accuracy = round(correct / total, 4)

    # Per question-type accuracy
    type_stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )
    for r in completed:
        qt = r.get("question_type", "unknown")
        type_stats[qt]["total"] += 1
        if r.get("is_correct", False):
            type_stats[qt]["correct"] += 1

    type_accuracy = {
        t: round(s["correct"] / s["total"], 4) if s["total"] > 0 else 0.0
        for t, s in type_stats.items()
    }

    summary = {
        "total_completed": total,
        "total_failed": len(failed_results),
        "correct": correct,
        "accuracy": accuracy,
        "type_accuracy": type_accuracy,
        "failed_ids": failed_ids,
        "wrong_ids": wrong_ids,
        "correct_ids": correct_ids,
        "evaluation_date": datetime.now().date().isoformat(),
    }
    summary_path = output_dir / "evaluation_summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nResults ({total} questions):")
    print(f"  Accuracy: {accuracy:.1%} ({correct}/{total})")
    for t, acc in sorted(type_accuracy.items()):
        n = type_stats[t]["total"]
        c = type_stats[t]["correct"]
        print(f"  {t}: {acc:.1%} ({c}/{n})")
    print(f"Summary saved to {summary_path}")

    return summary
