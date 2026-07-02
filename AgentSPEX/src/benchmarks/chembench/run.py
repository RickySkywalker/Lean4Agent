"""ChemBench benchmark runner - agent workflow entry point.

Example usage:

# Run all topics with agent workflow
python -m benchmarks.chembench.run --model gpt-5

# Run specific topics, 10 per topic
python -m benchmarks.chembench.run --model gpt-5 --topics general_chemistry --sample-per-topic 10

"""

import json
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from chembench.evaluate import ChemBenchmark, TopicQuestions
from chembench.prompter import create_multiple_choice_prompt, general_prompt
from chembench.utils import (post_process_prompts, remove_ce, remove_math,
                             remove_pu, remove_rxnsmiles, remove_smiles)

from benchmarks.chembench.config import parse_args
from benchmarks.chembench.evaluate import (build_eval_summary, extract_answer,
                                           print_summary, save_eval_summary,
                                           score_answer)
from harness.agent import AgentSPEX
from harness.types.config import EffectiveArgs
from mcp_client.client import MCPClient
from mcp_client.logger import Logger

_print_lock = threading.Lock()


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def _extract_question_text(task) -> str:
    """Extract the question text from a ChemBench task."""
    if not task._examples:
        return ""

    example = task._examples[0]
    is_mcq = "multiple_choice_grade" in task._metrics

    if is_mcq:
        prompt_str, _ = create_multiple_choice_prompt(
            example, permute=False, cot=False, random_seed=42
        )
    else:
        prompt_str = general_prompt(example, cot=False)

    prompt_str = post_process_prompts(
        prompt_str,
        post_process_ce=remove_ce,
        post_process_math=remove_math,
        post_process_smiles=remove_smiles,
        post_process_rxnsmiles=remove_rxnsmiles,
        post_process_pu=remove_pu,
    )

    return prompt_str


def run_single_question(
    idx: int,
    total: int,
    topic_name: str,
    task,
    workflow_file: str,
    model: str,
    output_dir: Path,
):
    """Run the agent on a single ChemBench question."""
    question_id = idx + 1
    question_text = _extract_question_text(task)
    question_output_dir = output_dir / "runs" / "logs" / f"question_{question_id}"

    _safe_print(f"\n[{question_id}/{total}] {task._name} ({topic_name})...")

    try:
        mcp_client = MCPClient()
        agent = AgentSPEX(mcp_client=mcp_client)

        # Create per-question logger
        question_output_dir.mkdir(parents=True, exist_ok=True)
        logger = Logger(
            mcp_client=mcp_client,
            log_file=str(question_output_dir / "agent_run.log"),
            host_log_path=question_output_dir / "agent_run.log",
            event_log_path=str(question_output_dir / "agent_events.log"),
            host_event_log_path=question_output_dir / "agent_events.log",
        )

        original_args = SimpleNamespace(
            workflow_file=workflow_file,
            model=model,
            problem_statement=question_text,
            output_dir=str(question_output_dir),
        )

        agent_args = EffectiveArgs(
            workflow_file=workflow_file,
            model=model,
            _original_args=original_args,
        )

        agent_output = agent.run(agent_args, external_logger=logger)
        response_text = (
            agent_output if isinstance(agent_output, str) else str(agent_output or "")
        )

        usage = {
            "input_tokens": agent.usage_tracker["prompt_tokens_total"],
            "output_tokens": agent.usage_tracker["completion_tokens_total"],
            "reasoning_tokens": agent.usage_tracker["reasoning_tokens_total"],
            "cost": agent.usage_tracker["cost_total"],
        }

        # Score the answer
        example = task._examples[0] if task._examples else {}
        metrics = score_answer(
            response_text,
            target_scores=example.get("target_scores"),
            target=example.get("target"),
        )
        extracted_answer = extract_answer(response_text)
        is_correct = metrics.get("all_correct", 0) == 1

        result = {
            "question_id": question_id,
            "name": task._name,
            "uuid": task._uuid,
            "topic": topic_name,
            "response": response_text,
            "extracted_answer": extracted_answer,
            "is_correct": is_correct,
            "usage": usage,
            "report": {
                "name": task._name,
                "uuid": task._uuid,
                "targets": [
                    ex.get("target", ex.get("target_scores")) for ex in task._examples
                ],
                "results": [{"metrics": metrics}],
            },
        }

        status = "correct" if is_correct else "wrong"
        _safe_print(f"  [{question_id}] done ({status})")
        return result

    except Exception as e:
        _safe_print(f"  [{question_id}] Error: {e}")
        return {
            "question_id": question_id,
            "name": task._name,
            "uuid": task._uuid,
            "topic": topic_name,
            "response": "",
            "usage": {},
            "report": {
                "name": task._name,
                "uuid": task._uuid,
                "results": [{"metrics": {"all_correct": 0}}],
                "error": str(e),
            },
        }


def main():
    os.environ.setdefault("TIMEOUT", "600")
    args = parse_args()
    model = args.model or "gpt-5"

    # Load benchmark
    print("Loading ChemBench from HuggingFace...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir or f"outputs/chembench_agent_{model}_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    benchmark = ChemBenchmark.from_huggingface(
        verbose=False,
        skip_errors=True,
    )

    if args.list_topics:
        benchmark.echo_topics()
        return

    # Filter topics
    topics = benchmark.registry.topics
    if args.topics:
        topics = {k: v for k, v in topics.items() if k in args.topics}

    # Sample per topic
    if args.sample_per_topic:
        n = args.sample_per_topic
        random.seed(args.seed)
        for topic_name, topic_data in topics.items():
            if len(topic_data.tasks) > n:
                topics[topic_name] = TopicQuestions(
                    topic=topic_name, tasks=random.sample(topic_data.tasks, n)
                )

    total_tasks = sum(len(td.tasks) for td in topics.values())
    max_parallel = args.max_parallel
    print(
        f"Running ChemBench AGENT (model: {model}, {total_tasks} questions, parallel={max_parallel})"
    )

    # Build all tasks list
    all_task_items = []
    for topic_name, topic_data in sorted(topics.items()):
        for task in topic_data.tasks:
            all_task_items.append((topic_name, task))

    # Run all questions (parallel)
    all_results = []
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                run_single_question,
                i,
                total_tasks,
                topic_name,
                task,
                args.workflow_file,
                model,
                output_dir,
            ): i
            for i, (topic_name, task) in enumerate(all_task_items)
        }
        for future in as_completed(futures):
            result = future.result()
            all_results.append(result)

    all_results.sort(key=lambda r: r["question_id"])

    # Save per-question results
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for r in all_results:
        with (runs_dir / f"{r['question_id']}.json").open("w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

    # Aggregate usage
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cost": 0.0,
    }
    for r in all_results:
        u = r.get("usage", {})
        total_usage["input_tokens"] += u.get("input_tokens", 0)
        total_usage["output_tokens"] += u.get("output_tokens", 0)
        total_usage["reasoning_tokens"] += u.get("reasoning_tokens", 0)
        total_usage["cost"] += u.get("cost", 0.0)

    # Build and save evaluation summary
    eval_summary = build_eval_summary(
        all_results, mode="agent", model=model, extra={"usage": total_usage}
    )
    eval_summary["evaluation_date"] = datetime.now().isoformat()
    eval_summary["topics"] = args.topics
    eval_summary["workflow_file"] = args.workflow_file
    eval_path = save_eval_summary(eval_summary, output_dir)

    print_summary(eval_summary)
    print(f"Output: {output_dir}")
    print(f"Evaluation: {eval_path}")


if __name__ == "__main__":
    main()
