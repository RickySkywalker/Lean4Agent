"""ELAIPBench benchmark runner - main entry point.

Evaluates agents on academic paper question answering (403 questions).
Based on https://huggingface.co/datasets/KangKang625/ELAIPBench

Example usage:

# Run all questions (uses model from workflow YAML, default: gpt-5)
python experiments/elaipbench/run.py

# Run 10 questions
python experiments/elaipbench/run.py --limit 10

# Run only single-answer questions
python experiments/elaipbench/run.py --question-type SA-MCQ

# Skip evaluation
python experiments/elaipbench/run.py --skip-eval
"""

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from config import ELAIPBenchResult, parse_args
from evaluate import evaluate
from instance import run_instance


def _filter_resumable(
    questions: List[dict], runs_dir: Path
) -> Tuple[List[dict], List[ELAIPBenchResult]]:
    """Split questions into (remaining_to_run, already_completed_results).

    A question is treated as already completed if ``runs/<id>.json`` exists
    and its ``status`` is ``"completed"``. Failed or partial results are
    re-run on the next pass.
    """
    remaining: List[dict] = []
    resumed: List[ELAIPBenchResult] = []

    if not runs_dir.exists():
        return questions, resumed

    for q in questions:
        result_path = runs_dir / f"{q['id']}.json"
        if not result_path.exists():
            remaining.append(q)
            continue
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            remaining.append(q)
            continue
        if data.get("status") != "completed":
            remaining.append(q)
            continue
        resumed.append(
            ELAIPBenchResult(
                question_id=data.get("question_id", q["id"]),
                question=data.get("question", q["question"]),
                question_type=data.get("question_type", q["question_type"]),
                correct_answer=data.get("correct_answer", q["answer"]),
                paper_id=data.get("paper_id", q.get("paper_id", 0)),
                status="completed",
                response=data.get("response", ""),
                parsed_answer=data.get("parsed_answer"),
                is_correct=bool(data.get("is_correct", False)),
                error=data.get("error"),
            )
        )
    return remaining, resumed


def _load_questions(
    question_ids=None,
    question_type=None,
    limit=None,
    dataset=None,
) -> List[dict]:
    """Load questions from a local parquet dataset, or HuggingFace if no path is given."""
    if dataset:
        import pandas as pd

        ds_path = Path(dataset)
        if ds_path.is_dir():
            parquet_path = ds_path / "test.parquet"
            if not parquet_path.exists():
                raise FileNotFoundError(
                    f"Expected test.parquet in {ds_path}, but found nothing."
                )
        else:
            parquet_path = ds_path
        print(f"Loading ELAIPBench from local parquet: {parquet_path}")
        df = pd.read_parquet(parquet_path)
        ds = df.to_dict(orient="records")
    else:
        from datasets import load_dataset

        ds = load_dataset(
            "KangKang625/ELAIPBench", data_files="elabench.jsonl", split="train"
        )

    questions = []
    for idx, row in enumerate(ds):
        questions.append(
            {
                "id": idx,
                "paper_id": row["paper_id"],
                "question_type": row["question_type"],
                "question": row["question"],
                "answer": row["answer"],
                "relevant_passage": row["relevant_passage"],
                "paper_content": row["paper_content"],
            }
        )

    if question_type:
        questions = [q for q in questions if q["question_type"] == question_type]

    if question_ids:
        id_set = set(question_ids)
        questions = [q for q in questions if q["id"] in id_set]

    if limit and limit < len(questions):
        seed = int(os.environ.get("ELAIPBENCH_SEED", "42"))
        rng = random.Random(seed)
        questions = rng.sample(questions, limit)

    return questions


def main():
    args = parse_args()

    # Step 1: Load questions
    if not args.dataset:
        print("Loading ELAIPBench from HuggingFace...")
    questions = _load_questions(
        question_ids=args.question_ids,
        question_type=args.question_type,
        limit=args.limit,
        dataset=args.dataset,
    )
    print(f"\n{len(questions)} questions to process")

    # Step 2: Run agent on each question
    output_dir = Path(args.output_dir) / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)

    resumed_results: List[ELAIPBenchResult] = []
    if getattr(args, "resume", False):
        if not output_dir.exists():
            print(
                f"Warning: --resume specified but {output_dir} does not exist; "
                "starting from scratch."
            )
        else:
            questions, resumed_results = _filter_resumable(questions, output_dir)
            if resumed_results:
                print(
                    f"Resuming: {len(resumed_results)} question(s) already "
                    f"completed, skipping. {len(questions)} remaining."
                )

    results: List[ELAIPBenchResult] = []

    if args.max_parallel > 1:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            futures = {
                executor.submit(
                    run_instance, i + 1, len(questions), q, args, output_dir
                ): q
                for i, q in enumerate(questions)
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    q = futures[future]
                    results.append(
                        ELAIPBenchResult(
                            question_id=q["id"],
                            question=q["question"],
                            question_type=q["question_type"],
                            correct_answer=q["answer"],
                            status="failed",
                            error=str(e),
                        )
                    )
    else:
        for i, q in enumerate(questions):
            results.append(run_instance(i + 1, len(questions), q, args, output_dir))

    # Summary (merge resumed + newly run)
    all_results = resumed_results + results
    completed = [r for r in all_results if r.status == "completed"]
    correct = sum(1 for r in completed if r.is_correct)
    failed = len(all_results) - len(completed)

    print(f"\n{'='*60}")
    print(
        f"Completed: {len(completed)}/{len(all_results)}"
        + (f" ({failed} failed)" if failed else "")
        + (f" ({len(resumed_results)} resumed)" if resumed_results else "")
    )
    if completed:
        print(f"Accuracy: {correct}/{len(completed)} ({correct/len(completed):.1%})")
    print(f"Results: {output_dir}")

    # Step 3: Evaluate
    if not args.skip_eval and completed:
        print("\nRunning evaluation...")
        eval_dir = Path(args.output_dir) / "evals"
        evaluate(runs_dir=str(output_dir), eval_dir=str(eval_dir))
    elif args.skip_eval:
        print("\nSkipped evaluation (--skip-eval)")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
