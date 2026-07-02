"""ChemBench baseline runner - direct LLM call, no agent workflow.
Example usage:

# Run baseline
python -m benchmarks.chembench.run_baseline --model gpt-5

# Run specific topics, 10 per topic
python -m benchmarks.chembench.run_baseline --model gpt-5 --sample-per-topic 10

"""

import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import litellm
from chembench.evaluate import ChemBenchmark, TopicQuestions
from chembench.prompter import PrompterBuilder, PrompterPipeline

from benchmarks.chembench.config import parse_args
from benchmarks.chembench.evaluate import (build_eval_summary, extract_answer,
                                           print_summary, save_eval_summary,
                                           score_answer)


def main():
    args = parse_args()
    model = args.model or "gpt-5"
    litellm.drop_params = True

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"outputs/chembench_baseline_{model}_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading ChemBench from HuggingFace...")
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
        f"Running ChemBench BASELINE (model: {model}, {total_tasks} questions, parallel={max_parallel})"
    )

    # Build all tasks list
    all_task_items = []
    for topic_name, topic_data in sorted(topics.items()):
        for task in topic_data.tasks:
            all_task_items.append((topic_name, task))

    def _create_prompter(model_name):
        """Create a prompter with patched generate that uses single litellm.completion calls."""
        pipeline = PrompterPipeline()
        pipeline.add_arg("llm_refusal", "keyword")
        prompter = PrompterBuilder.from_model_object(
            model=model_name,
            prompt_type="instruction",
            pipeline=pipeline,
        )

        # Track usage per-call
        prompter._usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cost": 0.0,
        }

        original_generate = prompter.model.generate

        def single_generate(prompts, **kwargs):
            from chembench.types import LiteLLMMessage

            results = []
            for prompt_messages in prompts:
                try:
                    response = litellm.completion(
                        model=model_name,
                        messages=prompt_messages,
                        **{k: v for k, v in kwargs.items() if k != "model"},
                    )
                    content = response.choices[0].message.content or ""
                    results.append(LiteLLMMessage(role="assistant", content=content))
                    # Accumulate usage
                    if hasattr(response, "usage") and response.usage:
                        prompter._usage["input_tokens"] += (
                            getattr(response.usage, "prompt_tokens", 0) or 0
                        )
                        prompter._usage["output_tokens"] += (
                            getattr(response.usage, "completion_tokens", 0) or 0
                        )
                        reasoning = getattr(
                            response.usage, "completion_tokens_details", None
                        )
                        if reasoning:
                            prompter._usage["reasoning_tokens"] += (
                                getattr(reasoning, "reasoning_tokens", 0) or 0
                            )
                    try:
                        prompter._usage["cost"] += litellm.completion_cost(
                            completion_response=response
                        )
                    except Exception:
                        pass
                except Exception as e:
                    results.append(LiteLLMMessage(role="assistant", content=""))
            return results

        prompter.model.generate = single_generate
        return prompter

    def run_single(idx_topic_task):
        """Run a single question with its own independent prompter instance."""
        idx, (topic_name, task) = idx_topic_task

        prompter = _create_prompter(model)
        try:
            report = prompter.report(task)
            report_dict = report.model_dump()
        except Exception as e:
            report_dict = {
                "name": task._name,
                "uuid": task._uuid,
                "results": [{"metrics": {"all_correct": 0}}],
                "error": str(e),
            }

        # Extract model completion and score with our own logic
        completion = ""
        if report_dict.get("results") and report_dict["results"][0].get("completion"):
            completion = report_dict["results"][0]["completion"]

        example = task._examples[0] if task._examples else {}
        metrics = score_answer(
            completion,
            target_scores=example.get("target_scores"),
            target=example.get("target"),
        )
        extracted = extract_answer(completion)
        is_correct_flag = metrics.get("all_correct", 0) == 1

        if report_dict.get("results"):
            report_dict["results"][0]["metrics"] = metrics
        report_dict["targets"] = [example.get("target", example.get("target_scores"))]

        return {
            "question_id": idx + 1,
            "name": report_dict.get("name", task._name),
            "uuid": report_dict.get("uuid", task._uuid),
            "topic": topic_name,
            "is_correct": is_correct_flag,
            "extracted_answer": extracted,
            "metrics": metrics,
            "usage": prompter._usage,
            "report": report_dict,
        }

    all_results = []
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(run_single, (i, item)): i
            for i, item in enumerate(all_task_items)
        }
        for future in as_completed(futures):
            result = future.result()
            all_results.append(result)
            status = "✓" if result["is_correct"] else "✗"
            print(f"  [{len(all_results)}/{total_tasks}] {result['name']}: {status}")

    all_results.sort(key=lambda r: r["question_id"])

    # Save per-question results
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for r in all_results:
        with (runs_dir / f"{r['question_id']}.json").open("w") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

    # Aggregate usage across all questions
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

    # Build and save evaluation summary using shared evaluate module
    eval_summary = build_eval_summary(
        all_results, mode="baseline", model=model, extra={"usage": total_usage}
    )
    eval_summary["evaluation_date"] = datetime.now().isoformat()
    eval_summary["topics"] = args.topics
    save_eval_summary(eval_summary, output_dir)

    print_summary(eval_summary)
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
