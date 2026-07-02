# SWE_bench_LeanEvolve — joint LeanEvolve → LLMEvolve correction cascade

Merged entry point for the two SWE-bench workflow-evolution arms. Given a set of
**previously-failed** instances, it runs **LeanEvolve** first, evaluates, and
for the instances still failing falls back to **LLMEvolve**, then reports how
many additional problems pass once.

This package is a *thin wrapper*: every heavy step is delegated to the two
**vendored** arm packages and the SWE-bench harness — no evolution / rerun /
eval logic is reimplemented here.

| Arm | Delegated to | What it does |
|---|---|---|
| **LeanEvolve** | `PureLean/run.py` | Stage A annotate → B Lean-formal-guided evolve → C rerun |
| **LLMEvolve** | `PureLLMAddsOn/run_e2e.py` | LLM-only evolve → rerun (no Lean) |
| **evaluate** | `python -m swebench.harness.run_evaluation` | per-instance `resolved` verdicts |

### Self-contained layout

```
SWE_bench_LeanEvolve/
├── run.py             # the joint cascade wrapper (this package's entry point)
├── PureLean/          # vendored copy of the Lean-formal-guided arm
└── PureLLMAddsOn/     # vendored copy of the LLM-only arm
```

`PureLean` and `PureLLMAddsOn` are self-contained packages for the two evolve
arms (Lean-guided and LLM-only). They rely on the sibling
`experiments/SWE_bench_verified` package and the repo-level `leanagent/` and
`AgentSPEX` harness.

## Cascade

```
previously-failed instances
        │
        ▼
  ┌───────────────┐   resolved?   ┌──────────────────────────┐
  │  LeanEvolve   ├──── yes ──────▶│  fixed by Lean (counted)  │
  │  + evaluate   │               └──────────────────────────┘
  └──────┬────────┘
         │ no (still failing)
         ▼
  ┌───────────────┐   resolved?   ┌──────────────────────────┐
  │  LLMEvolve    ├──── yes ──────▶│  fixed by LLM (counted)   │
  │  + evaluate   │               └──────────────────────────┘
  └──────┬────────┘
         │ no
         ▼
   still failing (not counted)
```

An instance is an **additional pass** iff *either* arm resolves it. LLMEvolve is
run only on instances LeanEvolve did not fix, and its eval is scored on that
still-failing subset, so a problem is never double-counted.

## Reuse & resume

Each arm keeps its own resumable staging tree at the **same default locations**
as the standalone runs:

- LeanEvolve → `workspace/swe_lean_evolve/<model_slug>/<plan>`
- LLMEvolve  → `workspace/swe_llm_evolve/<plan>`

So re-invoking this wrapper picks up all prior Stage-A/B/C work (annotated IRs,
Lean queries, evolved plans, rerun patches) and only the missing pieces run. The
SWE-bench harness likewise skips instances whose `report.json` already exists,
so re-evaluation is cheap.

## Invocation (glm-5 on Bedrock — the paper's SWE arm)

```bash
source ./configs/LLM-config.env          # Bedrock zai.glm-5 config

python -u experiments/SWE_bench_LeanEvolve/run.py \
  --plan-name passed_workflow_1 \
  --source-outputs-root tmp/runs/passed_workflow_1 \
  --source-eval-root tmp/runs/baseline_eval/logs/run_evaluation/glm5_baseline/bedrock__zai.glm-5 \
  --source-layer2-ir FormalAgentLib/VerificationExamples/layer2_v2_ir/passed_workflow_1_layer2_v2.ir.json \
  --dataset data/SWE_bench_verified_50problems_subset \
  --split test \
  --model bedrock/zai.glm-5 \
  --conda-env Lean4Agent_env \
  --max-parallel 8
```

> **Layer-2 IR path:** pass the plan's Layer-2 IR explicitly via `--source-layer2-ir`.
> For `passed_workflow_1` (the 5-step passing plan) this is
> `FormalAgentLib/VerificationExamples/layer2_v2_ir/passed_workflow_1_layer2_v2.ir.json`.

### Failure set

By default the wrapper corrects the instances whose **baseline**
`report.json` (under `--source-eval-root`) shows `resolved == False` and that
have a prior trajectory (`<inst>_agent_events.log`) under
`--source-outputs-root`. Override with `--instance-ids a,b,c`. Add
`--include-unevaluated` to also re-roll trajectories with no baseline report
(baseline error / not-submitted).

## Key flags

| Flag | Meaning |
|---|---|
| `--plan-name` | plan prefix, e.g. `passed_workflow_1` |
| `--source-outputs-root` | baseline run's `<inst>_agent_events.log` dir |
| `--source-eval-root` | baseline eval dir with `<inst>/report.json` (failure discovery) |
| `--source-layer2-ir` | Layer-2 IR for the Lean arm (see note above) |
| `--instance-ids` | explicit failed-instance whitelist (overrides discovery) |
| `--include-unevaluated` | also treat no-baseline-report trajectories as failed |
| `--max-parallel` | per-arm concurrency (also the default eval `--max_workers`) |
| `--fresh` | disable resume in both arms |
| `--skip-lean-arm` / `--skip-llm-arm` | reuse existing predictions, still evaluate |
| `--lean-eval-cwd` / `--llm-eval-cwd` + `*-run-id` | point eval at an existing run dir to reuse reports |
| `--dry-run` | print every sub-command without executing |

## Outputs

```
<run-root>/                              # default tmp/runs/swe_leanevolve/<model_slug>/<plan>
├── lean_eval/logs/run_evaluation/<plan>_lean/<model>/<inst>/report.json
├── llm_eval/
│   ├── predictions_still_failing.jsonl  # LLM preds filtered to Lean's failures
│   └── logs/run_evaluation/<plan>_llm/<model>/<inst>/report.json
└── joint_correction_report.json         # the merged result
```

`joint_correction_report.json` records the failed set, each arm's resolved
instances, the union (`additional_passes`), and per-instance `attribution`
(`lean` / `llm`).
