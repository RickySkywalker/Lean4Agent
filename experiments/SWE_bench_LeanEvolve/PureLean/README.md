# lean_evolve

Two entry points:

| Script | Role |
|---|---|
| `run_e2e.py` | **End-to-end orchestrator** — chains annotate → evolve → rerun (→ evaluate) for the full Lean-guided experiment loop |
| `run.py` | Stage C only — sibling of `swe_bench_verified/run.py` that dispatches each instance to its own evolved plan YAML |

See `run_e2e.py --help` for the full pipeline; the remainder of this README
documents `run.py` (the stage-C runner it orchestrates).

## End-to-end pipeline (run_e2e.py)

Chains four stages over the same instance set:

```
                      +-------------------------------------------------+
  STAGE A annotate -> | leanagent/codegen/agent_evolve/run_agent_evolve.py           |
                      |   prior trajectories + eval -> layer3_query.json|
                      +-------------------------------------------------+
                                           |
                                           v
                      +-------------------------------------------------+
  STAGE B evolve   -> | leanagent/codegen/agent_evolve/run_plan_evolve.py            |
                      |   layer3_query.json -> evolved YAML plan        |
                      +-------------------------------------------------+
                                           |
                                           v
                      +-------------------------------------------------+
  STAGE C rerun    -> | experiments/SWE_bench_LeanEvolve/PureLean/run.py           |
                      |   evolved plans -> per-instance diffs +         |
                      |                    predictions.jsonl            |
                      +-------------------------------------------------+
                                           |
                                           v
                      +-------------------------------------------------+
  STAGE D evaluate -> | python -m swebench.harness.run_evaluation       |
                      |   predictions.jsonl -> report.json              |
                      |   (skipped unless --run-eval)                   |
                      +-------------------------------------------------+
```

### Resume semantics

- **Intermediate resume (default)**: every sub-stage is invoked with its own
  `--resume`, so per-instance work already completed is skipped. Interrupt
  anywhere and re-run the same command to pick up from where it left off.
- **Resume from scratch**: `--fresh` drops `--resume` from every sub-stage so
  every instance is re-processed. Does NOT delete artifacts on disk — combine
  with a manual `rm -rf` of the staging dirs if you want a true clean slate.
- **Skip ahead**: `--start-stage {annotate,evolve,rerun,evaluate}` begins at
  the named stage and assumes earlier stages have produced their artifacts.
- **Single stage**: `--only-stage X` runs just one stage and stops.

### Typical invocation

```bash
source ./experiments/SWE_bench_verified/gpt5.2_config.env
python -u experiments/SWE_bench_LeanEvolve/PureLean/run_e2e.py \
    --plan-name passed_workflow_1 \
    --original-plan-yaml ./experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --source-outputs-root ./outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \
    --source-eval-root    ./benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1/gpt-5.2 \
    --source-layer2-ir    ./FormalAgentLib/VerificationExamples/layer2_v2_ir/passed_workflow_1_layer2_v2.ir.json \
    --dataset ./data/test_dataset/SWE_bench_verified_50problems_subset \
    --split   test \
    --model   gpt-5.2 \
    --stage-c-output-dir outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1_regen \
    --limit 10 --max-parallel 5 --skip-resolved --run-eval
```

Per-stage defaults derived from `--plan-name` and `--model`:

| Default | Derivation |
|---|---|
| `--stage-a-staging-root` | `workspace/agent_evolve_run/staging_<model_slug>` |
| `--stage-a-results-dir`  | `leanagent/codegen/agent_evolve/outputs/<model_slug>/<plan_name>` |
| `--stage-b-staging-root` | `workspace/agent_evolve_run/staging_<model_slug>_evolve` |
| `--stage-b-smoke-test-dir` | `experiments/SWE_bench_verified/layer3_smoke_test/Lean_guided_modification` |
| `--stage-c-output-dir` | **no default — required** (or use `--unified-staging-root`) |
| `--stage-d-run-id` | `<plan_name>_regen` |

`<model_slug>` strips non-alphanumerics, e.g. `gpt-5.2` → `gpt52`.

### Unified staging layout

Pass `--unified-staging-root <root>` to collapse every stage's staging + output
under one parent directory with per-stage subfolders. All five paths are
auto-derived and auto-created:

```
<root>/
├── stage_a/                   # Stage A Docker-visible workspace
├── stage_a_results/           # Stage A durable outputs (layer3_ir.json, per_step.lean, layer3_query.json)
├── stage_b/                   # Stage B Docker-visible workspace (working_plan.yaml, plan_evolve_digest.json)
├── stage_b_evolved_plans/     # Stage B durable: <plan_name>_<inst>_lean.yaml files
└── stage_c_rerun/             # Stage C diffs + predictions.jsonl
```

`<root>` MUST be inside `--workspace-root` so Docker sees `stage_a/` and
`stage_b/` as `/workspace/...` paths. Any explicit `--stage-*-*` flag
overrides the unified-derived default.

Typical use:

```bash
python experiments/SWE_bench_LeanEvolve/PureLean/run_e2e.py \
    --plan-name passed_workflow_1 \
    --unified-staging-root ./workspace/regen_runs/gpt52/passed_workflow_1 \
    ...
```

`predictions.jsonl` then lives at
`./workspace/regen_runs/gpt52/passed_workflow_1/stage_c_rerun/predictions.jsonl`.

### Dry-run and troubleshooting

Print what each stage would run without executing:

```bash
python experiments/SWE_bench_LeanEvolve/PureLean/run_e2e.py ... --dry-run
```

Interrupted mid-run? Just re-run the same command — the per-stage `--resume`
handles per-instance idempotency. To skip a stage whose output is already
correct, use `--start-stage`.

---

## Stage-C-only runner (run.py)

Sibling of `swe_bench_verified` that runs each instance with **its own
per-instance evolved task plan** (one YAML per instance, discovered
from a directory) instead of a single shared plan.

Use this for the Layer-3 smoke-test re-roll loop — see
`experiments/SWE_bench_verified/layer3_smoke_test/{Lean_guided_modification,baseline}/`.

## How it differs from `swe_bench_verified`

Same orchestration (parallel agents, resume, predictions.jsonl,
dashboard, exclude-list filters), but the YAML plan is selected
per-instance:

| | `swe_bench_verified` | `lean_evolve` |
|---|---|---|
| Plan source | `--task-plan-file <single.yaml>` | `--task-plans-dir <dir of YAMLs>` |
| Plan-to-instance mapping | one plan for all | filename-derived: `*_<instance_id>_<arm>.yaml` |
| Default instance set | full dataset (after exclude/limit) | only instances with a plan in the dir |

Everything else (Docker exec, agent loop, patch extraction,
predictions output) is reused verbatim from the verified package.

## Plan filename convention

Each YAML in `--task-plans-dir` must embed the SWE-bench instance id
in its filename:

```
<prefix>_<instance_id>[_<arm>].yaml
```

where `<instance_id>` is the canonical `<repo>__<repo>-<num>` form.
Examples:

```
passed_workflow_1_django__django-14140_lean.yaml
passed_workflow_1_matplotlib__matplotlib-25775_baseline.yaml
passed_workflow_1_sympy__sympy-13551.yaml
```

Files that don't match are silently skipped.

## Invocation

```bash
source experiments/SWE_bench_verified/gpt5.2_config.env

python experiments/SWE_bench_LeanEvolve/PureLean/run.py \
  --task-plans-dir experiments/SWE_bench_verified/layer3_smoke_test/Lean_guided_modification \
  --dataset       data/test_dataset/SWE_bench_verified_50problems_subset \
  --instance-ids  django__django-14140,sympy__sympy-13551 \
  --split test --limit 50 \
  --model "gpt-5.2" --max-parallel 10 \
  --no-exclude --save-logs --resume \
  --output-dir outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1_regen
```

`--instance-ids` accepts both comma- and space-separated values and
defaults to all instances with a matching plan in `--task-plans-dir`.

## Args inherited from the verified runner

`--dataset`, `--split`, `--model`, `--output-dir`, `--save-logs`,
`--dashboard*`, `--max-parallel`, `--exclude-file`, `--no-exclude`,
`--limit`, `--resume` — all behave identically to `swe_bench_verified`.

`--task-plan-file` is accepted as an **optional fallback** for
instances that have no per-instance YAML (rare; the dataset filter
normally drops these first).

## Outputs

Identical layout to the verified runner:

```
<output_dir>/
├── <instance_id>.yaml            # the evolved plan, materialized with
│                                  # parameters substituted
├── <instance_id>.diff            # extracted patch
├── <instance_id>_full.log        # if --save-logs
├── <instance_id>_agent_events.log
├── <instance_id>_final_output.txt
├── <instance_id>_summary.txt
└── predictions.jsonl             # one row per successful instance
```

so a downstream `sb-cli submit` works on the regen output the same as
on the verified output.

## Smoke-test workflow

For each unresolved instance pair, run the regen runner once per arm
into a separate `--output-dir`, then submit each `predictions.jsonl`
to the SWE-bench harness and compare resolved counts:

```bash
# Lean-guided arm
python experiments/SWE_bench_LeanEvolve/PureLean/run.py \
  --task-plans-dir .../layer3_smoke_test/Lean_guided_modification \
  --output-dir outputs/.../passed_workflow_1_lean_regen \
  ...

# Baseline arm
python experiments/SWE_bench_LeanEvolve/PureLean/run.py \
  --task-plans-dir .../layer3_smoke_test/baseline \
  --output-dir outputs/.../passed_workflow_1_baseline_regen \
  ...
```

Compare:

```bash
sb-cli submit swe-bench_verified test \
  --predictions_path outputs/.../passed_workflow_1_lean_regen/predictions.jsonl \
  --run_id lean-arm

sb-cli submit swe-bench_verified test \
  --predictions_path outputs/.../passed_workflow_1_baseline_regen/predictions.jsonl \
  --run_id baseline-arm
```
