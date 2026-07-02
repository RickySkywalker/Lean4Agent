"""Main orchestration for AIME benchmark: load → solve → evaluate."""

import argparse
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

from benchmarks.aime.config import DATASETS, AIMEResult, parse_args
from benchmarks.aime.evaluate import evaluate, parse_answer, verify_answer
from benchmarks.aime.prompts import QUESTION_PROMPT


def _load_existing_results(output_dir: Path) -> Dict[str, AIMEResult]:
    """Load completed results from a previous run."""
    existing = {}
    for json_path in output_dir.glob("*.json"):
        try:
            with json_path.open("r") as f:
                data = json.load(f)
            if data.get("status") == "completed":
                existing[data["problem_id"]] = AIMEResult(
                    problem_id=data["problem_id"],
                    problem=data.get("problem", ""),
                    correct_answer=data.get("correct_answer", ""),
                    dataset=data.get("dataset", ""),
                    status="completed",
                    response=data.get("response", ""),
                    parsed_answer=data.get("parsed_answer"),
                    is_correct=data.get("is_correct", False),
                )
        except (json.JSONDecodeError, KeyError):
            continue
    return existing


def _load_problems(dataset="all", problem_ids=None, limit=None) -> List[dict]:
    """Load AIME problems from HuggingFace.

    Supports:
      - dataset="aime24"  → AIME 2024 (30 problems)
      - dataset="aime25"  → AIME 2025 I & II (30 problems)
      - dataset="all"     → Both datasets (60 problems)
    """
    from datasets import load_dataset

    datasets_to_load = [dataset] if dataset != "all" else list(DATASETS.keys())

    problems = []
    for ds_key in datasets_to_load:
        ds_info = DATASETS[ds_key]

        for config_name in ds_info["configs"]:
            # Load from HuggingFace
            if config_name is not None:
                ds = load_dataset(
                    ds_info["hf_path"], config_name, split=ds_info["split"]
                )
            else:
                ds = load_dataset(ds_info["hf_path"], split=ds_info["split"])

            for row_idx, row in enumerate(ds):
                # Build problem ID
                if ds_info["id_field"] and ds_info["id_field"] in row:
                    pid = str(row[ds_info["id_field"]])
                else:
                    # Generate ID from config name and index
                    # e.g. "AIME2025-I" → "2025-I-1"
                    if config_name:
                        prefix = config_name.replace("AIME", "")
                        pid = f"{prefix}-{row_idx + 1}"
                    else:
                        pid = f"{ds_key}-{row_idx + 1}"

                question = row[ds_info["question_field"]]
                answer = str(row[ds_info["answer_field"]])

                # Determine dataset label for grouping
                if config_name:
                    dataset_label = f"{ds_key}-{config_name.split('-')[-1]}"
                else:
                    dataset_label = ds_key

                problems.append(
                    {
                        "id": pid,
                        "problem": question,
                        "answer": answer,
                        "dataset": dataset_label,
                    }
                )

    # Apply filters
    if problem_ids:
        id_set = set(str(p) for p in problem_ids)
        problems = [p for p in problems if p["id"] in id_set]

    if limit and limit < len(problems):
        problems = problems[:limit]

    return problems


def _run_single_problem(
    idx: int,
    total: int,
    problem: dict,
    args,
    output_dir: Path,
) -> AIMEResult:
    """Run the agent on a single AIME problem."""
    pid = problem["id"]
    preview = problem["problem"][:80].replace("\n", " ")

    print(f"\n[{idx}/{total}] Problem {pid} ({problem['dataset']}): {preview}...")

    try:
        from harness.agent import AgentSPEX
        from harness.types.config import EffectiveArgs
        from mcp_client.client import MCPClient

        mcp_client = MCPClient()
        agent = AgentSPEX(mcp_client=mcp_client)

        # Create a thread-local copy of args to avoid race conditions
        # Ensure agent-level resume is disabled (benchmark handles its own resume)
        local_args = argparse.Namespace(**vars(args))
        local_args.problem_statement = QUESTION_PROMPT.format(
            problem=problem["problem"]
        )
        local_args.resume = False

        agent_args = EffectiveArgs(
            workflow_file=args.workflow_file,
            _original_args=local_args,
        )

        import concurrent.futures

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(agent.run, agent_args)
        timeout = getattr(args, "timeout", 900)
        try:
            agent_output = future.result(timeout=timeout)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        response_text = (
            agent_output if isinstance(agent_output, str) else str(agent_output or "")
        )

        parsed = parse_answer(response_text)
        ground_truth = problem["answer"]

        # Use math-verify for robust comparison
        is_correct = verify_answer(response_text, ground_truth)

        result = AIMEResult(
            problem_id=pid,
            problem=problem["problem"],
            correct_answer=ground_truth,
            dataset=problem["dataset"],
            status="completed",
            response=response_text,
            parsed_answer=parsed,
            is_correct=is_correct,
        )

        from benchmarks.aime.instance import save_result

        save_result(result, output_dir)
        status = "CORRECT" if is_correct else ("REFUSED" if parsed is None else "WRONG")
        print(f"  [{pid}] {status} (parsed={parsed}, correct={ground_truth})")
        return result

    except Exception as e:
        print(f"  [{pid}] Error: {e}")
        traceback.print_exc()
        result = AIMEResult(
            problem_id=pid,
            problem=problem["problem"],
            correct_answer=problem["answer"],
            dataset=problem.get("dataset", ""),
            status="failed",
            error=str(e),
        )
        from benchmarks.aime.instance import save_result

        save_result(result, output_dir)
        return result


def main():
    args = parse_args()

    # Step 1: Load problems from HuggingFace
    ds_label = args.dataset if args.dataset != "all" else "AIME 2024 + 2025"
    print(f"Loading {ds_label} from HuggingFace...")
    problems = _load_problems(
        dataset=args.dataset,
        problem_ids=args.problem_ids,
        limit=args.limit,
    )
    print(f"\n{len(problems)} problems to process")

    # Step 2: Run agent on each problem
    output_dir = Path(args.output_dir) / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resume: load existing completed results and skip them
    existing_results = {}
    if args.resume:
        existing_results = _load_existing_results(output_dir)
        if existing_results:
            print(
                f"Resuming: {len(existing_results)} completed problems found, skipping them"
            )

    results: List[AIMEResult] = []
    to_run = []
    for i, p in enumerate(problems):
        if p["id"] in existing_results:
            results.append(existing_results[p["id"]])
        else:
            to_run.append((i, p))

    if not to_run:
        print("All problems already completed!")
    elif args.max_parallel > 1:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            futures = {
                executor.submit(
                    _run_single_problem, i + 1, len(problems), p, args, output_dir
                ): p
                for i, p in to_run
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    p = futures[future]
                    results.append(
                        AIMEResult(
                            problem_id=p["id"],
                            problem=p["problem"],
                            correct_answer=p["answer"],
                            dataset=p.get("dataset", ""),
                            status="failed",
                            error=str(e),
                        )
                    )
    else:
        for i, p in to_run:
            results.append(
                _run_single_problem(i + 1, len(problems), p, args, output_dir)
            )

    # Summary
    completed = [r for r in results if r.status == "completed"]
    correct = sum(1 for r in completed if r.is_correct)
    failed = len(results) - len(completed)
    print(f"\n{'='*60}")
    print(
        f"Completed: {len(completed)}/{len(results)}"
        + (f" ({failed} failed)" if failed else "")
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
