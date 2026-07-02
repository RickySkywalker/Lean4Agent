# AIME Benchmark

Evaluates agents on [AIME](https://en.wikipedia.org/wiki/American_Invitational_Mathematics_Examination) (American Invitational Mathematics Examination) competition problems from 2024, 2025, and 2026. Answers are always integers from 000 to 999.

The agent uses a two-step workflow: solve with Python code verification, then independently verify with a different computational approach. Only `execute_python_code` is available (no web search).

## Quick Start

```bash
# Source env first
source config/vm.env && source config/host.env

# Run all 60 problems (AIME 2024 + 2025)
python -m benchmarks.aime.run --dataset all --max-parallel 10

# Run AIME 2024 only (30 problems)
python -m benchmarks.aime.run --dataset aime24 --max-parallel 10

# Run 5 problems
python -m benchmarks.aime.run --dataset all --limit 5

# Run specific problems
python -m benchmarks.aime.run --problem-ids 2024-I-4 2025-II-3

# Resume a previous run (skip completed problems)
python -m benchmarks.aime.run --dataset all --max-parallel 10 \
  --output-dir outputs/aime_20260323_023701 --resume

# Custom timeout (default: 900s per problem)
python -m benchmarks.aime.run --dataset all --max-parallel 10 --timeout 900
```

## Pipeline

1. **Load** -- Downloads problems from HuggingFace (`Maxwell-Jia/AIME_2024`, `opencompass/AIME2025`, `math-ai/aime26`).

2. **Solve** -- Agent reasons through the problem and writes Python code via `execute_python_code` to compute the answer. Math reasoning and code must agree.

3. **Verify** -- Agent independently verifies using a different computational approach. If results disagree, it determines the correct answer.

4. **Evaluate** -- Uses [math-verify](https://github.com/huggingface/Math-Verify) for robust answer comparison with `\boxed{}` extraction fallback. Reports accuracy overall and per dataset.

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dataset` | `all` | Dataset (`aime24`, `aime25`, `aime26`, `all`) |
| `--output-dir` | `outputs/aime_<timestamp>` | Results directory |
| `--max-parallel` | `1` | Parallel workers |
| `--limit` | all | Max problems to process |
| `--problem-ids` | all | Specific problem IDs (e.g. `2024-I-4 2025-II-3`) |
| `--timeout` | `900` | Per-problem timeout in seconds |
| `--resume` | false | Skip completed problems in output dir |
| `--workflow-file` | `aime_agent.yaml` | Agent YAML workflow |
| `--model` | yaml config | Model override (note: YAML config takes precedence) |
| `--skip-eval` | false | Skip evaluation |

## Output Structure

```
outputs/aime_<timestamp>/
├── runs/
│   ├── 2024-I-4.json          # Per-problem result
│   ├── 2025-II-3.json
│   └── ...
└── evals/
    └── evaluation_summary.json
```

## Datasets

| Dataset | Problems | Source |
|---------|----------|--------|
| `aime24` | 30 | AIME 2024 (I + II) |
| `aime25` | 30 | AIME 2025 (I + II) |
| `aime26` | 30 | AIME 2026 (I + II) |
| `all` | 90 | All three years |

## Results

### gpt-5 + workflow (by dataset)

| Dataset | Correct | Wrong | Timeout | Accuracy |
|---------|---------|-------|---------|----------|
| AIME 2024+2025 | 59/60 | 0 | 1 | 98.3% |
| AIME 2026 | 29/30 | 0 | 1 | 96.7% |
| **Total** | **88/90** | **0** | **2** | **97.8%** |

### Model comparison (AIME 2024+2025)

| Model | Mode | Correct | Wrong | Timeout | Accuracy |
|-------|------|---------|-------|---------|----------|
| gpt-5-mini | Pure reasoning (no tools) | 52/60 | 8 | 0 | 86.7% |
| gpt-5-mini | Workflow + code verify | 54/60 | 3 | 3 | 90.0% |
| **gpt-5** | **Workflow + code verify** | **59/60** | **0** | **1** | **98.3%** |

gpt-5 with workflow achieves **zero wrong answers** across all 90 problems. The 2 missing problems timed out (agent exceeded time limit on code execution loops).

## Environment Variables

- `OPENAI_API_KEY` -- Required (set via `source config/vm.env`)
- Sandbox container must be running (`bash scripts/run_vm.sh start`)
