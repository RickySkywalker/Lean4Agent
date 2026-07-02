# WritingBench Benchmark

Evaluates agents on generative writing tasks across 6 domains with rubric-based scoring. Based on [WritingBench](https://github.com/X-PLUG/WritingBench).

The agent uses a multi-phase agentic workflow (defined in `writing_bench_agent.yaml`) running on Claude Sonnet 4.5. Evaluation uses an LLM-as-judge approach, also powered by Claude Sonnet 4.5 by default.

## Quick Start

```bash
# Setup API KEY
export ANTHROPIC_API_KEY="YOUR_API_KEY"

# Step 1: Sample a balanced subset (20 questions per domain, 120 total)
python src/benchmarks/writing_bench/sample_dataset.py --per-domain 20 --seed 42
# Prints the sampled --query-indices and saves to data/benchmark_sampled_20x6.jsonl

# Step 2: Run the sampled queries with Claude Sonnet 4.5 in parallel, skip eval
TIMEOUT=600 python src/benchmarks/writing_bench/run.py \
    --model claude-sonnet-4-5 \
    --query-indices <paste indices from step 1> \
    --max-parallel 10 \
    --save-logs --quiet \
    --skip-eval \
    --output-dir outputs/writing_bench_claude_sonnet_45

# Evaluate completed runs (can be run separately after generation)
python -c "
from benchmarks.writing_bench.evaluate import evaluate
evaluate(
    runs_dir='outputs/writing_bench_claude_sonnet_45/runs',
    benchmark_path='src/benchmarks/writing_bench/data/benchmark_all.jsonl',
    judge_model='claude-sonnet-4-5',
    eval_dir='outputs/writing_bench_claude_sonnet_45/evals',
    max_parallel=30,
)
"
```

## Pipeline

1. **Download** -- Automatically downloads `benchmark_all.jsonl` and requirement subset files from GitHub on first run. Cached in `data/`.

2. **Agent Workflow** -- For each query, a YAML-driven agentic workflow runs through multiple phases inside the sandbox VM:
   - **Requirement Extraction** -- Parses the query into structured requirements (format, length, style, language, domain, etc.)
   - **Output Format Selection** -- Chooses the appropriate file format (`.md`, `.txt`, `.tex`, `.html`) based on the task
   - **Rubric Generation** -- Creates 5 task-specific evaluation criteria with measurable verification methods
   - **Drafting** -- Writes the document incrementally into a file using sandbox tools (`fs_write`, `shell_run`, `string_replace`)
   - **Constraint Verification** -- Runs shell commands to verify word counts, structure, and formatting requirements
   - **Self-Critique** -- Evaluates the draft against the rubric, producing a PASS/FAIL verdict per criterion
   - **Conditional Revision** -- If any criteria fail, revises the draft using targeted `string_replace` edits
   - **Word Count Annotation** -- Injects verified word/character count annotations into the final document
   - **Return** -- Returns the output file path; `run.py` reads the content from the file via MCP

3. **Evaluate** -- An LLM judge (Claude Sonnet 4.5) scores each response on 5 rubric criteria (1-10 scale). Produces per-query eval files and an overall summary with domain breakdowns.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `claude-sonnet-4-5` | Agent model (overrides workflow config) |
| `--output-dir` | `outputs/writing_bench_<timestamp>` | Results directory |
| `--max-parallel` | `1` | Parallel query workers |
| `--limit` | all | Max queries to process |
| `--query-indices` | all | Specific query indices to run |
| `--judge-model` | `claude-sonnet-4-5` | Model for rubric-based evaluation |
| `--workflow-file` | `writing_bench_agent.yaml` | Agent YAML workflow |
| `--skip-eval` | `false` | Skip evaluation after generation |
| `--save-logs` | `false` | Save per-instance agent logs (full log + structured events) |
| `--max-parallel-eval` | `1` | Parallel evaluation judge workers |
| `--quiet` | `false` | Suppress agent logs on terminal (use with `--save-logs`) |

The `TIMEOUT` environment variable controls per-query timeout in seconds.

## Sampling a Subset

The full benchmark has 1,000 queries. Use `sample_dataset.py` to create a balanced subset by sampling equally from each of the 6 primary domains:

```bash
# Sample 20 questions per domain (120 total, default)
python src/benchmarks/writing_bench/sample_dataset.py

# Sample 10 per domain with a different seed
python src/benchmarks/writing_bench/sample_dataset.py --per-domain 10 --seed 123

# Save to a custom path
python src/benchmarks/writing_bench/sample_dataset.py --output data/my_sample.jsonl
```

The script prints:
- A per-domain count summary
- The saved JSONL path (default: `data/benchmark_sampled_20x6.jsonl`)
- The list of sampled indices, ready to paste into `run.py --query-indices`

| Flag | Default | Description |
|------|---------|-------------|
| `--per-domain` | `20` | Number of questions to sample per domain |
| `--seed` | `42` | Random seed for reproducibility |
| `--output` | auto-generated | Output JSONL path |

## Output Structure

```
outputs/writing_bench_<name>/
├── runs/
│   ├── 1/
│   │   ├── result.json          # Agent response + metadata
│   │   ├── draft.md             # Collected artifact from sandbox
│   │   ├── 1.yaml              # Per-instance YAML config
│   │   ├── 1_full.log          # Full agent log (if --save-logs)
│   │   └── 1_agent_events.log  # Structured events (if --save-logs)
│   ├── 2/
│   │   └── ...
│   └── ...
└── evals/
    ├── 1_eval.json              # Per-query rubric scores
    ├── 2_eval.json
    └── evaluation_summary.json  # Aggregated scores + domain breakdown
```

## Evaluation Metrics

- **Overall Avg Score (/10)** -- Average across all criteria and queries
- **Per-domain averages** -- Breakdown by 6 writing domains

## Data Directory

The `data/` folder is gitignored and populated on first run:

```
data/
├── benchmark_all.jsonl              # 1,000 writing queries with checklists
└── requirement/
    ├── style/style_subset.jsonl
    ├── style/style_subset_C.jsonl
    ├── format/format_subset.jsonl
    ├── format/format_subset_C.jsonl
    ├── length/length_subset.jsonl
    └── length/length_subset_C.jsonl
```

## Environment Variables

- `ANTHROPIC_API_KEY` -- Required for agent execution and evaluation (Claude Sonnet 4.5)
