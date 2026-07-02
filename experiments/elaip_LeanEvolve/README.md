# ELAIP-Bench Lean Plan-Evolution

A pipeline that takes a baseline ELAIP-Bench run, identifies failed
`(plan, question_id)` pairs, evolves the YAML plan against each pair's
trajectory, re-runs the evolved plan once, and compares accuracy. Unlike the
SWE pipeline there is no environment feedback, so evolution is guided purely by
the Lean Layer-3 diagnosis.

| Path | Signal source for the LLM judge |
|------|---------------------------------|
| `experiments/elaip_LeanEvolve/run.py` | Layer-3 Lean diagnosis (per-step, per-predicate) |

## Top-level invariant

The LLM judge sees only the **trajectory**. `is_correct`,
`parsed_answer`, `correct_answer`, and `response` are stripped from any
context staged for the LLM. They may be used by the *driver* to decide
which `(plan, qid)` pairs to enqueue (default filter:
`is_correct == False`).

## Directory layout

```
experiments/elaip_LeanEvolve/
  build_layer2_ir.py            One-shot Layer-2 IR generator over the ELAIP plans
  elaip_layer3_codegen.py       IR → per-(plan, qid) Layer-3 .lean file
  run.py                        End-to-end Stage A → D for the Lean pipeline
  package_files/
    elaip_layer3_ir_init.py     Trajectory → Layer-3 IR seeder
    trace_segmenter.py          agent_events.log → per-step excerpts + summaries (verbatim copy)
    plan_validator.py           ELAIP-specific structural validator + repair
    EditYaml.py / EditJson.py   verbatim from leanagent/codegen/agent_evolve/
    lean_report_loader.py       verbatim from leanagent/codegen/agent_evolve/
  FAILURE_PATTERNS.md           Phase-0 mining output: 12 data-derived patterns

FormalAgentLib/AgentVerifier/DynamicVerification/ElaipBench/
  PredicateChecks.lean          Pure decidable JSON-shape checks (no axioms)
  ElaipBench.lean               PerStepAnalysisRules glue + name-lookup helpers
  ElaipExamples/                Generated per-(plan, qid) Layer-3 .lean files

FormalAgentLib/VerificationExamples/elaipbench_layer2/
  passed_workflow_{1,2,3}_layer2_v2.ir.json   Pre-generated, checked in
  failed_workflow_{1,2,3}_layer2_v2.ir.json   Pre-generated, checked in
```

## Stage B is YAML-driven (mirrors SWE)

Stage B (the LLM diagnosis + amendment + validation) is implemented as a
proper YAML agent workflow, spawned via `scripts/run_agent.sh`
exactly like the SWE pipelines. Each YAML uses `enable_inline_tool_calls:
true` so `shell_run` works without an MCP server. The Python `run.py` driver
sets the canonical environment variables (`PAIR_ID`, `ORIGINAL_PLAN_YAML`,
`WORKING_PLAN_YAML`, `STAGING_DIR`, `PACKAGE_DIR`, optional
`FAILURE_PATTERNS_PATH`, `LAYER2_IR_PATH`/`LEAN_DIAGNOSIS_PATH` /
`LAYER3_QUERY_PATH` / `TRAJECTORY_EVIDENCE_PATH` / `PREDICATES_PATH`
as applicable) and then invokes the wrapper helper
`package_files/yaml_runner.py::run_yaml_agent`.

The two YAML workflows:

| YAML | Path | Phases |
|------|------|--------|
| `annotate_layer3_elaip.yaml` | `experiments/elaip_LeanEvolve/` | seg + init IR → load context → **per-step annotation while-loop** (Rule-1 JSON-decidable gate / Rule-2 trajectory-completeness / Rule-3 conservative default) → consistency review + apply → **deterministic JSON-shape gate** (`tighten_layer3_verdicts.py`) → status |
| `evolve_plan_elaip.yaml` | `experiments/elaip_LeanEvolve/` | copy + build digest → load digest + Lean diagnosis + question_meta + FAILURE_PATTERNS.md → **per-step rewrite while-loop** with E1-E12 named patterns + hard rules (length cap 1.5×, no answer leakage, no eval signal, no audit trail, templates preserved) → whole-plan consistency review + apply → **validate** with R1/R2/R3 recovery protocol → finalize |

Each YAML:
- Sees only the trajectory (`trajectory_evidence.json`) and the Lean
  Layer-3 diagnosis
- NEVER sees `is_correct`, `parsed_answer`, `correct_answer`, `response`
  (those fields are stripped from `run_meta.json` by Stage A)
- Uses `EditYaml.py --set-by-name` for surgical instruction rewrites
- Uses `EditJson.py --set-by-name` to flip per-step digest entries
- Ends with `plan_validator.py --repair` which reverts any step whose
  rewrite leaks an answer letter, eval signal, or audit-trail phrase

To fall back to the direct-litellm path (no AgentSPEX / no `scripts/run_agent.sh`),
pass `--no-use-yaml-workflow`. The fallback is functionally equivalent but
runs as a single litellm call; the YAML path is the canonical one.

## Stages

The pipeline has the following shape:

```
A  stage inputs:           agent_events.log → trace_index.json + per-step summaries
                           runs/<qid>.json  → question_meta.json (redacted)
                                            → trajectory_evidence.json (per-step signals)
A* (lean only) IR seed → IR with annotations → codegen → lake build → diagnosis parse
                           emits layer3_query.json
B  LLM evolves YAML:       YAML agent workflow (per-step rewrite -> review ->
                           validate) returns the evolved YAML, checked by
                           package_files/plan_validator.py (one repair attempt:
                           revert failing steps to original). --no-use-yaml-workflow
                           swaps in an equivalent single litellm call.
C  rerun:                  subprocess experiments/elaipbench/run.py with the
                           evolved YAML on the single qid
D  evaluate:               aggregate is_correct deltas
```

Resume sentinels are per-substage; re-running with `--resume` (default) skips
substeps whose sentinels exist. `--fresh` disables. See each `run.py` docstring
for the exact sentinel list.

## Quick smoke test

```bash
# 1. Pre-generate Layer-2 IRs (one-time)
python experiments/elaip_LeanEvolve/build_layer2_ir.py
# -> FormalAgentLib/VerificationExamples/elaipbench_layer2/<plan>.ir.json (×6)

# 2. Build the Lean Layer-3 framework (one-time)
cd FormalAgentLib && lake build AgentVerifier.DynamicVerification.ElaipBench.ElaipBench
cd ..

# 3. Run the Lean pipeline on one (plan, qid) pair, only Stage A (no LLM call)
PAIR_ROOT=outputs/gpt-5.2/ELAIPBench_100problems_subset/passed_workflow_1

python experiments/elaip_LeanEvolve/run.py \
    --plan-name passed_workflow_1 \
    --source-outputs-root $PAIR_ROOT \
    --question-ids 0 --only-stage A \
    --unified-staging-root outputs/elaip_smoke/lean_evolve
```

Expected after step 3: the staging dir contains the per-step segments,
trajectory_evidence.json, layer3_ir.json, per_step.lean, lean_diagnosis.txt,
and layer3_query.json.

## Full end-to-end run (requires OPENAI_API_KEY etc.)

```bash
export OPENAI_API_KEY=sk-...

python experiments/elaip_LeanEvolve/run.py \
    --plan-name passed_workflow_1 \
    --source-outputs-root outputs/gpt-5.2/ELAIPBench_100problems_subset/passed_workflow_1 \
    --model gpt-5.2 \
    --max-parallel 4 \
    --unified-staging-root outputs/elaip_LeanEvolve/gpt-5.2/passed_workflow_1 \
    --failure-patterns experiments/elaip_LeanEvolve/FAILURE_PATTERNS.md \
    --summary outputs/elaip_LeanEvolve/gpt-5.2/passed_workflow_1/_summary.json
```

The default selection filter (`is_correct == False`) means only the failing
trajectories are evolved — all `is_correct=True` pairs are skipped.

## Extension points

- **Annotator (Stage A.4)**: currently a stub that copies the seed IR. To
  add an LLM annotator, replace `run_stage_a_annotate` with a call that
  fills `llm_injections` per (step, var_name).
- **Phase-2 per-step temporal granularity**: currently `execState_q<qid>`
  is a single final-state snapshot. For the `recheck_options` while-loop,
  per-iteration snapshots would tighten the verdict.
