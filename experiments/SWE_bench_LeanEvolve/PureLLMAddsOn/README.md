# llm_evolve — LLM-only task-plan evolution baseline

LLM-driven baseline for task-plan evolution on SWE-bench. Given an unresolved
instance's original YAML plan, the agent's execution trajectory
(`agent_events.log`), and the SWE-bench evaluation result (`report.json` +
`test_output.txt`), this package runs a 5-phase YAML workflow that:

1. Segments the trajectory into per-step summaries.
2. Extracts concise failure evidence from the eval.
3. Iterates over each workflow step: decides whether that step's instruction led the
   agent astray, and if so rewrites the instruction in-place with
   trajectory-informed guidance.
4. Runs a whole-plan consistency review.
5. Validates structural invariants and emits the evolved YAML.

This is the control arm for the Lean-guided evolution pipeline at
`leanagent/codegen/agent_evolve/`. Both pipelines produce the same output shape (evolved
YAML with amended per-step `instruction:` blocks, preserving structure /
templates / style) and both feed downstream SWE-bench re-inference via
`experiments/SWE_bench_LeanEvolve/PureLean/run.py`.

## Quickstart

### End-to-end (evolve → rerun → evaluate)

Use `run_e2e.py` to chain all three stages in one invocation:

```bash
source ./experiments/SWE_bench_verified/gpt5.2_config.env
python -u ./experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run_e2e.py \
    --plan-name passed_workflow_1 \
    --original-plan-yaml ./experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --source-outputs-root ./outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \
    --source-eval-root ./benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1/gpt-5.2 \
    --dataset ./data/test_dataset/SWE_bench_verified_50problems_subset \
    --split test \
    --model gpt-5.2 \
    --unified-staging-root ./outputs/llm_evolve/gpt-5.2/passed_workflow_1 \
    --limit 10 \
    --max-parallel 10 \
    --skip-resolved \
    --run-eval
```

Stage layout (under `--unified-staging-root`):
- `stage_b_evolved_plans/<plan_name>_<inst>_llm.yaml` — evolved plans
- `stage_c_rerun/predictions.jsonl` — SWE-bench predictions from rerun
- `stage_c_rerun/logs/run_evaluation/<run_id>/…` — stage-D eval results

`--run-eval` is required if you want the SWE-bench harness (stage D) to
execute; otherwise the pipeline stops after stage C and you can run the
harness manually later.

### Plan-evolution only

Use `run.py` if you already have a prior SWE-bench run and only want to
produce evolved YAMLs (no rerun/eval):

```bash
# Single instance (smoke test)
python experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run.py \
    --outputs_root outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \
    --eval_root benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1 \
    --original_plan_yaml experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --single_instance django__django-14140 \
    --stream_logs

# Batch with resume + parallelism + limit
python experiments/SWE_bench_LeanEvolve/PureLLMAddsOn/run.py \
    --outputs_root outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \
    --eval_root benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1 \
    --original_plan_yaml experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --plan_name passed_workflow_1 \
    --max_parallel 3 \
    --limit 10 \
    --resume \
    --skip_resolved
```

## Durable outputs

Validated evolved plans land at:

```
experiments/SWE_bench_verified/layer3_smoke_test/LLM_only_evolve/<plan_name>_<instance_id>_llm.yaml
```

This directory is a sibling of:

- `layer3_smoke_test/baseline/` — Claude skill–produced reference outputs (no
  trajectory access). This package's outputs are the YAML-agent-driven
  equivalent with richer inputs.
- `layer3_smoke_test/Lean_guided_modification/` — outputs of the
  Lean-guided arm at `leanagent/codegen/agent_evolve/run_plan_evolve.py`.

## Resume + limit semantics

`--resume` drops already-completed instances **before** `--limit` is applied.
An instance counts as complete iff both:

1. `<output_dir>/<plan_name>_<instance>_llm.yaml` exists, AND
2. `<staging_root>/outputs/<instance>/validation_report.json` has
   `summary.pass == true`.

So `--resume --limit 5` processes 5 **incomplete** instances, not 5
picked-from-the-top that might already be done.

## Staging layout

```
<staging_root>/                                # must be inside <workspace_root>
├── package/                                    # helpers copied from package_files/
├── evolve.yaml                                 # copy of task plan
├── inputs/<instance>/
│   ├── original_plan.yaml
│   ├── agent_events.log
│   ├── report.json
│   └── test_output.txt
├── staging/<instance>/
│   ├── working_plan.yaml                       # mutated in place by Phase 3
│   ├── trace_index.json                        # per-step trajectory summary
│   ├── eval_evidence.json                      # compact eval digest
│   └── amendments_digest.json                  # per-step verdicts (confirmed/amended)
├── outputs/<instance>/
│   ├── evolved_plan.yaml                       # copied to durable dir on success
│   └── validation_report.json                  # structural checks
└── runtime/<instance>/
    └── driver.log                              # YAML agent stdout/stderr capture
```

All paths are inside `<staging_root>` so Docker sees them under `/workspace/…`.

## Downstream re-inference

After evolving plans, re-run SWE-bench on the evolved plans with the existing
`lean_evolve` runner:

```bash
python experiments/SWE_bench_LeanEvolve/PureLean/run.py \
    --task-plans-dir experiments/SWE_bench_verified/layer3_smoke_test/LLM_only_evolve \
    --output-dir outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1_regen_llm \
    --max-parallel 4 \
    --resume
```

`lean_evolve` is plan-agnostic — it reads any `_llm.yaml` in the
`--task-plans-dir` and re-runs SWE-bench evaluation.

## Comparison against the Claude-skill version

An earlier ad-hoc version existed as a Claude skill (historical reference only, not present in this repo).
Differences:

| Aspect | Claude skill | This package |
|--------|--------------|--------------|
| Trajectory access | No (only report.json + test_output.txt) | Yes (agent_events.log segmented per-step) |
| Execution | Ad-hoc Claude-code invocation | Reproducible AgentSPEX run (`scripts/run_agent.sh`) |
| Per-step decisions | Single monolithic LLM call | Per-step loop |
| Batching | One-at-a-time | Parallel with `--max_parallel`, `--resume`, `--limit` |
| Validation | Inline inside skill | Separate `plan_validator.py` with machine-checkable report |

The skill's outputs in `layer3_smoke_test/baseline/` are the structural
reference for output quality — each run of this package should produce
evolved plans of comparable shape (same instructions for unchanged steps,
similar concrete-guidance additions for changed steps).

## Files

| File | Purpose |
|------|---------|
| `evolve.yaml` | 5-phase task plan executed per-instance by AgentSPEX |
| `run.py` | Batch driver; argparse + PTY + resume + limit + parallelism |
| `paths.py` | Staging-tree path helpers (one source of truth) |
| `package_files/trace_segmenter.py` | Event-log → per-step JSONL + Markdown summaries |
| `package_files/eval_forensics.py` | report.json + test_output.txt → compact evidence JSON |
| `package_files/EditYaml.py` | Surgical YAML instruction-block editor |
| `package_files/EditJson.py` | Path-based JSON mutation CLI |
| `package_files/seed_digest.py` | Seeds `amendments_digest.json` with all steps marked confirmed |
| `package_files/plan_validator.py` | 9-check structural validator (reused from Lean arm) |
