"""Evaluation for WritingBench using rubric-based scoring.

Adapted from https://github.com/X-PLUG/WritingBench/blob/main/evaluate_benchmark.py
Each query has 5 criteria scored 1-10 by an LLM judge.
"""

import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

from benchmarks.writing_bench.prompts import EVALUATE_PROMPT, EVALUATE_SYSTEM
from harness.llms.client import LLMClient

EVAL_TIMES = 1


def _strip_think_prefix(text: str) -> str:
    """Remove chain-of-thought prefix from reasoning models."""
    marker = "</think>\n\n"
    pos = text.find(marker)
    return text[pos + len(marker) :] if pos != -1 else text


def _parse_score_json(raw: str) -> Optional[dict]:
    """Parse the judge's JSON response, tolerating markdown fences."""
    cleaned = raw.strip().strip("`").removeprefix("json").strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            result = json.loads(m.group())
        except json.JSONDecodeError:
            return None

    if (
        isinstance(result, dict)
        and isinstance(result.get("score"), int)
        and 1 <= result["score"] <= 10
        and isinstance(result.get("reason"), str)
    ):
        return result
    return None


def _call_judge(
    client: LLMClient,
    query: str,
    response: str,
    criteria: dict,
    model: str,
    max_retries: int = 5,
) -> Optional[dict]:
    """Score a single (response, criteria) pair via the judge model.

    Matches the official WritingBench evaluation protocol:
    - Criteria passed as raw dict (str() representation via .format())
    - temperature=1.0, max_tokens=2048
    - Up to 5 retries per criterion
    """
    prompt = EVALUATE_PROMPT.format(query=query, response=response, criteria=criteria)

    for _ in range(max_retries):
        try:
            completion = client.completion(
                model=model,
                messages=[
                    {"role": "system", "content": EVALUATE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=1.0,
                max_tokens=2048,
            )
            text = completion.choices[0].message.content or ""
            result = _parse_score_json(text)
            if result is not None:
                return result
        except Exception as e:
            print(f"  Judge API error: {e}")

    return None


def load_benchmark_queries(jsonl_path: Path) -> Dict[int, dict]:
    """Load the full benchmark JSONL (index -> {query, checklist, domain1, ...})."""
    data = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                data[obj["index"]] = obj
    return data


def _evaluate_single(
    json_path: Path,
    eval_path: Path,
    benchmark: Dict[int, dict],
    client: LLMClient,
    judge_model: str,
    force: bool,
) -> Optional[dict]:
    """Evaluate a single result file. Returns the score dict or None if skipped."""
    # Use cached eval if available
    if eval_path.exists() and not force:
        try:
            with eval_path.open("r") as f:
                return json.load(f)
        except Exception:
            pass

    with json_path.open("r") as f:
        run_data = json.load(f)

    index = run_data.get("index")
    if index not in benchmark:
        return None

    bm_entry = benchmark[index]
    query = bm_entry["query"]
    checklist = bm_entry["checklist"]
    response_text = run_data.get("response", "")
    is_completed = run_data.get("status") == "completed"

    if not response_text or not is_completed:
        result = {
            "index": index,
            "status": "skipped",
            "scores": {},
        }
    else:
        response_clean = _strip_think_prefix(response_text)
        scores: Dict[str, list] = {}

        for criteria in checklist:
            name = criteria["name"]
            scores[name] = []
            for _ in range(EVAL_TIMES):
                score_result = _call_judge(
                    client, query, response_clean, criteria, judge_model
                )
                if score_result:
                    scores[name].append(score_result)
                else:
                    scores[name].append({"score": 0, "reason": "Judge failed"})

        result = {
            "index": index,
            "status": "evaluated",
            "scores": scores,
        }

    with eval_path.open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def evaluate(
    runs_dir: str,
    benchmark_path: str,
    eval_dir: str = "evals",
    judge_model: str = "claude-sonnet-4-5",
    force: bool = False,
    max_parallel: int = 1,
) -> dict:
    """Run rubric-based evaluation over completed writing results.

    Args:
        runs_dir: Directory containing run result JSON files.
        benchmark_path: Path to benchmark_all.jsonl.
        eval_dir: Directory to save evaluation results.
        judge_model: Model to use for judging.
        force: If True, re-evaluate even if cached results exist.
        max_parallel: Max parallel evaluation threads (default: 1, sequential).
    """
    runs_path = Path(runs_dir)
    output_dir = Path(eval_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    benchmark = load_benchmark_queries(Path(benchmark_path))

    # Support both directory layouts:
    #   New: runs/{index}/result.json  (per-instance directories)
    #   Old: runs/{index}.json         (flat layout, backward compat)
    json_files = sorted(runs_path.glob("*/result.json"))
    if not json_files:
        json_files = sorted(runs_path.glob("*.json"))
    if not json_files:
        print(f"No result JSON files in {runs_path}")
        return {}

    client = LLMClient()

    # Build (json_path, eval_path) pairs
    eval_tasks = []
    for json_path in json_files:
        if json_path.name == "result.json":
            eval_key = json_path.parent.name
        else:
            eval_key = json_path.stem
        eval_path = output_dir / f"{eval_key}_eval.json"
        eval_tasks.append((json_path, eval_path))

    all_scores: List[dict] = []

    if max_parallel > 1:
        print(
            f"Evaluating {len(eval_tasks)} results with max {max_parallel} parallel judges"
        )
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_to_key = {
                executor.submit(
                    _evaluate_single,
                    json_path,
                    eval_path,
                    benchmark,
                    client,
                    judge_model,
                    force,
                ): eval_path.stem
                for json_path, eval_path in eval_tasks
            }
            for future in tqdm(
                as_completed(future_to_key),
                total=len(future_to_key),
                desc="Evaluating",
            ):
                key = future_to_key[future]
                try:
                    result = future.result()
                    if result is not None:
                        all_scores.append(result)
                except Exception as e:
                    print(f"  [{key}] Evaluation error: {e}")
    else:
        for json_path, eval_path in tqdm(eval_tasks, desc="Evaluating"):
            result = _evaluate_single(
                json_path, eval_path, benchmark, client, judge_model, force
            )
            if result is not None:
                all_scores.append(result)

    if not all_scores:
        return {}

    # Aggregate
    evaluated = [s for s in all_scores if s["status"] == "evaluated"]
    total = len(evaluated)

    if total == 0:
        print("No queries were evaluated.")
        return {}

    # Overall average score across all criteria
    score_sum = 0.0
    score_count = 0
    for entry in evaluated:
        for criteria_name, evals in entry["scores"].items():
            for ev in evals:
                if ev["score"] > 0:
                    score_sum += ev["score"]
                    score_count += 1

    overall_avg = round(score_sum / score_count, 2) if score_count else 0.0

    # Per-domain averages
    domain_scores: Dict[str, List[float]] = defaultdict(list)
    for entry in evaluated:
        idx = entry["index"]
        if idx in benchmark:
            d1 = benchmark[idx].get("domain1", "unknown")
            entry_avg = _entry_avg_score(entry)
            if entry_avg is not None:
                domain_scores[d1].append(entry_avg)

    domain_avgs = {
        d: round(sum(vals) / len(vals), 2) for d, vals in domain_scores.items()
    }

    summary = {
        "total_evaluated": total,
        "total_skipped": len(all_scores) - total,
        "overall_avg_score": overall_avg,
        "domain_avg_scores": domain_avgs,
        "judge_model": judge_model,
        "evaluation_date": datetime.now().date().isoformat(),
    }

    summary_path = output_dir / "evaluation_summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nResults ({total} queries evaluated):")
    print(f"  Overall Avg Score: {overall_avg}/10")
    for d, avg in sorted(domain_avgs.items()):
        print(f"  {d}: {avg}/10")
    print(f"Summary saved to {summary_path}")

    return summary


def _entry_avg_score(entry: dict) -> Optional[float]:
    """Compute the average score for a single evaluated entry."""
    total = 0.0
    count = 0
    for evals in entry["scores"].values():
        for ev in evals:
            if ev["score"] > 0:
                total += ev["score"]
                count += 1
    return round(total / count, 2) if count else None
