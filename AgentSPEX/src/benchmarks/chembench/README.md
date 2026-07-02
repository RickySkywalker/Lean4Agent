# ChemBench Benchmark

Evaluates agents on chemistry questions across multiple topics (MCQ and numerical) using the [ChemBench](https://github.com/lamalab-org/chem-bench) dataset from HuggingFace. Supports both an agentic workflow mode and a direct LLM baseline mode.

## Quick Start

```bash
# Setup API KEY
export OPENAI_API_KEY="YOUR_API_KEY"

# List available topics
python -m benchmarks.chembench.run --list-topics

# Run agent workflow on all topics
python -m benchmarks.chembench.run --model gpt-5

# Run agent on specific topics, sample 10 per topic, 8 parallel workers
python -m benchmarks.chembench.run --model gpt-5 \
    --topics general_chemistry organic_chemistry \
    --sample-per-topic 10 \
    --max-parallel 8

# Run baseline (direct LLM call, no agent workflow)
python -m benchmarks.chembench.run_baseline --model gpt-5 \
    --sample-per-topic 10 --max-parallel 8
```

## Pipeline

1. **Load** -- Downloads questions from HuggingFace via `ChemBenchmark.from_huggingface()`. Questions are organized by topic, each containing MCQ or numerical chemistry problems.

2. **Agent Workflow** (`run.py`) -- For each question, a YAML-driven agentic workflow runs through multiple phases:
   - **Analyze** -- Identifies problem type (MCQ/numerical), core concepts, given data, and potential pitfalls. Does NOT solve yet.
   - **Solve** -- Solves step-by-step based on the analysis, wrapping the final answer in `[ANSWER]...[/ANSWER]` tags.
   - **Validate** -- Checks 5 criteria: correct tags, logical reasoning, answer consistency, option consideration (MCQ), units/sig figs (numerical). On failure, triggers a retry from scratch.
   - **Return Solution** -- Extracts only the final answer in the required format.

3. **Baseline** (`run_baseline.py`) -- Calls the LLM directly via ChemBench's PrompterBuilder

4. **Evaluate** -- Shared evaluation logic for both modes:
   - **MCQ**: Extracts letter(s) from `[ANSWER]` tags, computes Hamming distance against ground truth. Correct only if Hamming = 0.
   - **Numerical**: Parses float from `[ANSWER]` tags, correct if within 1% tolerance of target value.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `gpt-5` | Agent/LLM model |
| `--output-dir` | `outputs/chembench_<timestamp>` | Results directory |
| `--max-parallel` | `1` | Parallel workers |
| `--topics` | all | Specific topics to evaluate |
| `--sample-per-topic` | all | Randomly sample N questions per topic |
| `--seed` | `42` | Random seed for reproducible sampling |
| `--workflow-file` | `chembench_agent.yaml` | Agent YAML workflow |
| `--list-topics` | `false` | List available topics and exit |
| `--skip-eval` | `false` | Skip evaluation after running queries |

## Output Structure

### Agent mode (`run.py`)

```
outputs/chembench_<timestamp>/
├── runs/
│   ├── 1.json                        # Per-question result
│   ├── 2.json
│   ├── ...
│   └── logs/
│       ├── question_1/
│       │   ├── agent_run.log         # Full agent log
│       │   ├── agent_events.log      # Structured agent events
│       │   ├── trace.jsonl           # Execution trace
│       │   ├── final-output.txt      # Final agent output
│       │   ├── step-1-output.txt     # Per-step outputs (analyze, solve, ...)
│       │   ├── step-2-output.txt
│       │   ├── checkpoint.json       # Agent checkpoint state
│       │   └── reproducibility/      # Reproducibility metadata
│       ├── question_2/
│       └── ...
└── evals/
    └── evaluation_summary.json       # Aggregated accuracy + per-topic breakdown
```

### Baseline mode (`run_baseline.py`)

```
outputs/chembench_baseline_<model>_<timestamp>/
├── runs/
│   ├── 1.json
│   ├── 2.json
│   └── ...
└── evals/
    └── evaluation_summary.json
```

### Per-question result (`<id>.json`)

- `question_id` -- Sequential ID
- `name` -- ChemBench task name
- `uuid` -- ChemBench task UUID
- `topic` -- Topic name
- `response` -- Full model response text
- `extracted_answer` -- Parsed answer from `[ANSWER]` tags
- `is_correct` -- Whether the answer is correct
- `usage` -- Token usage (`input_tokens`, `output_tokens`, `reasoning_tokens`, `cost`)
- `report` -- ChemBench-compatible report with targets and metrics

## Evaluation Metrics

The evaluation summary (`evaluation_summary.json`) contains:

- `mode` -- `"agent"` or `"baseline"`
- `model` -- Model name
- `accuracy` -- Overall fraction correct
- `total_completed` / `correct` -- Question counts
- `topic_stats` -- Per-topic `{correct, total, accuracy}`
- `wrong_names` -- Task names of incorrectly answered questions
- `usage` -- Aggregated token usage (`input_tokens`, `output_tokens`, `reasoning_tokens`, `cost`)
- `evaluation_date` -- ISO timestamp
- `topics` -- Topics filter used (null if all)
- `workflow_file` -- YAML workflow path (agent mode only)

## Environment Variables

- `OPENAI_API_KEY` -- Required if using OpenAI models
- `ANTHROPIC_API_KEY` -- Required if using Anthropic models (Claude)
