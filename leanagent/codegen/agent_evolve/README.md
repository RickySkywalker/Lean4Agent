# agent_evolve — Layer 3 Auto-Annotation + Plan-Evolution Package

Automates two consecutive stages of the Layer-3 evaluation experiment.

**Step 2** (`run_agent_evolve.py` + `annotate_layer3.yaml`): given a SWE-agent run's
trajectory + SWE-bench evaluation results + a reference Layer 2 IR, produce an
annotated Layer 3 JSON IR, render it to Lean, and run the Lean REPL to emit a
per-instance `layer3_query.json`.

**Step 3** (`run_plan_evolve.py` + `evolve_plan.yaml`): given step 2's
`layer3_query.json` + the original SWE-bench YAML plan, rewrite each falsified
step's `instruction:` block in place with the Lean-derived re-roll guidance
welded seamlessly into natural prose. Confirmed steps stay byte-identical.

This is a sibling package to `leanagent/codegen/lean_verifier/` (which handles Layer 1+2). It is designed to run in
the YAML-agent sandbox Docker; **no Lean toolchain is required anywhere in the pipeline**
because Lean *source* is emitted by pure-Python codegen (`ir_to_lean.py` → `layer3_v2_codegen.py`),
not by invoking `lake`/`lean`.

## Pipeline

```
 Inputs (per instance):
   outputs/<model>/<bench>/<plan>/<instance>_agent_events.log       (event log)
   outputs/<model>/<bench>/<plan>/<instance>_full.log               (optional)
   benchmark_results/…/<instance>/report.json                       (eval verdict)
   benchmark_results/…/<instance>/test_output.txt                   (pytest output)
   reference Layer 2 IR JSON (e.g. passed_workflow_1_v2.ir.json)
                              │
                              ▼
 Phase 1 (deterministic, shell-only from YAML):
   trace_segmenter.py  → trace_index.json + per-step excerpts + per-step summaries
   eval_forensics.py   → eval_evidence.json
   layer3_ir_init.py   → layer3_ir.json  (exec_state=[], llm_injections=[], dyn_nodes pre-filled)
                              │
                              ▼
 Phase 2–3 (YAML for_each per step, LLM + EditJson):
   For each step i: LLM reads (per-step summary + Layer 2 node + eval_evidence),
                    emits (exec_state_entries + llm_injections) verdicts,
                    persists them to layer3_ir.json via EditJson --list_append
                              │
                              ▼
 Phase 4 (YAML, single LLM pass):
   cross-step consistency review; small patch list via EditJson --set
                              │
                              ▼
 Output from YAML:
   layer3_ir.json (fully annotated)
                              │
                              ▼
 Post-processing (host Python, outside YAML):
   ir_to_lean.py → per_step.lean  (pure-Python string emission; no Lean binary)
```

## Package contents

### Step 2 — Layer 3 auto-annotation

| File | Role |
|---|---|
| `annotate_layer3.yaml` | Per-instance YAML task plan (deterministic prep + per-step annotation loop + consistency pass) |
| `run_agent_evolve.py` | Step-2 batch driver |
| `trace_segmenter.py` | Parse `*_agent_events.log` into per-step excerpts + `trace_index.json` + Markdown summaries |
| `eval_forensics.py` | Extract compact `eval_evidence.json` from `report.json` + `test_output.txt` |
| `layer3_ir_init.py` | Seed the Layer 3 IR from a reference Layer 2 IR + trace metadata |
| `ir_to_lean.py` | Pure-Python codegen: Layer 3 IR JSON → `.lean` via the codegen (`layer3_v2_codegen.generate_layer3_v2_lean`) |
| `summarize_ir.py` | One-line status summary (used inside the YAML) |
| `EditJson.py` | Path-based JSON mutation CLI (copy of `leanagent/codegen/lean_verifier/EditJson.py`) |

### Step 3 — Lean-guided plan evolution

| File | Role |
|---|---|
| `evolve_plan.yaml` | Per-instance YAML task plan: prep + per-step edit loop + whole-plan consistency review + validator |
| `run_plan_evolve.py` | Step-3 batch driver |
| `lean_report_loader.py` | Convert step 2's `layer3_query.json` into a compact per-step digest |
| `EditYaml.py` | Surgical YAML instruction-block editor (preserves byte-identity on unchanged sections) |
| `plan_validator.py` | 9-check structural validator → `validation_report.json` |

### Shared

| File | Role |
|---|---|
| `staging_paths.py` | Directory-layout constants & path helpers shared between step 2 and step 3 |

## Quickstart

### Single instance (end-to-end)

```bash
python leanagent/codegen/agent_evolve/run_agent_evolve.py \
    --outputs_root /.../outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \
    --eval_root /.../benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/logs/run_evaluation/passed_workflow_1/gpt-5.2 \
    --layer2_ir /.../FormalAgentLib/VerificationExamples/layer3_ir/passed_workflow_1_v2.ir.json \
    --plan_name passed_workflow_1 \
    --results_dir leanagent/codegen/agent_evolve/outputs \
    --staging_root leanagent/codegen/agent_evolve/staging \
    --single_instance django__django-14140 \
    --skip_resolved
```

### Batch over all unresolved instances

Omit `--single_instance`; the driver finds every `<id>_agent_events.log` and skips the
resolved ones.

### Smoke test the deterministic prep (no LLM, no AgentSPEX)

```bash
# Segment the trace
python leanagent/codegen/agent_evolve/trace_segmenter.py \
    --event_log /.../outputs/.../django__django-14140_agent_events.log \
    --staging_dir /tmp/agent_evolve_smoke/django__django-14140 \
    --instance_id django__django-14140

# Extract eval evidence
python leanagent/codegen/agent_evolve/eval_forensics.py \
    --report /.../benchmark_results/.../django__django-14140/report.json \
    --test_output /.../benchmark_results/.../django__django-14140/test_output.txt \
    --staging_dir /tmp/agent_evolve_smoke/django__django-14140 \
    --instance_id django__django-14140

# Seed Layer 3 IR
python leanagent/codegen/agent_evolve/layer3_ir_init.py \
    --layer2_ir /.../FormalAgentLib/VerificationExamples/layer3_ir/passed_workflow_1_v2.ir.json \
    --trace_index /tmp/agent_evolve_smoke/django__django-14140/trace_index.json \
    --instance_id django__django-14140 \
    --plan_name passed_workflow_1 \
    --event_log_path /.../django__django-14140_agent_events.log \
    --report_path /.../django__django-14140/report.json \
    --out /tmp/agent_evolve_smoke/django__django-14140/layer3_ir.json

# Emit Lean (pure Python — no Lean toolchain needed)
python leanagent/codegen/agent_evolve/ir_to_lean.py \
    --ir /tmp/agent_evolve_smoke/django__django-14140/layer3_ir.json \
    --out /tmp/agent_evolve_smoke/django__django-14140/per_step.lean
```

The resulting `.lean` will have empty `exec_state` and `llm_injections` (since the
per-step LLM annotation step was skipped), but should still typecheck structurally
and match the shape of a Layer-3 per-step verification spec.

## Design notes

- **No Lean binary required.** `ir_to_lean.py` (via `layer3_v2_codegen`) emits Lean source
  as a Python string; we never call `lake`/`lean`. The sandbox Docker therefore does
  not need Lean installed.
- **Context discipline.** Every per-step LLM call only loads (a) the per-step Markdown
  summary (~6 KB), (b) the Layer 2 semantic node for that index (~1 KB), and (c) the
  eval evidence (~4 KB). The full 800 K-token trajectory is never loaded into a single
  LLM context.
- **Idempotent prep.** Phase 1 scripts are pure functions of their inputs, so re-running
  the YAML replays safely.
- **Batch driver.** `run_agent_evolve.py` serializes instances through `scripts/run_agent.sh`
  and records a summary JSON with per-instance status. Parallelism is easy to add later
  via `ThreadPoolExecutor` (mirrors `experiments/SWE_bench_verified/run.py`).

## Step 3 — Lean-guided plan evolution

### Pipeline

```
 Inputs (per instance, from step 2):
   <staging_gpt52>/lean_repl/passed_workflow_1_<inst>.json          (Layer 3 Lean query result)
   <staging_gpt52>/staging/<inst>/eval_evidence.json          (eval evidence from step 2)
   experiments/SWE_bench_verified/passed_workflow_1.yaml         (original plan)
                              │
                              ▼
 Phase 1 (deterministic, shell-only):
   cp original_plan.yaml working_plan.yaml
   lean_report_loader.py → plan_evolve_digest.json
   cp step 2's eval_evidence.json into step 3's staging dir
                              │
                              ▼
 Phase 2 (structural load): count digest, cat digest + eval_evidence
                              │
                              ▼
 Phase 3 (per-step edit loop, while i < num_steps):
   For each step i: LLM reads digest[i] + original instruction; if
   verdict=confirmed, SKIPPED. Otherwise rewrite the instruction (hard
   rules: no audit-trail leakage, preserve templates / structural tags,
   additions not deletions, ±30% length). Persist via EditYaml.py --set.
                              │
                              ▼
 Phase 4 (whole-plan consistency review, single LLM pass):
   LLM reads full evolved plan + digest + eval_evidence; emits JSON array
   of corrections (may narrow scope, may delete contradictions; NOT add
   new templates or commands). Applied via EditYaml.py --set.
                              │
                              ▼
 Phase 5 (final validation):
   plan_validator.py → validation_report.json (9 structural checks).
   On pass: cp working_plan.yaml → outputs/<inst>/evolved_plan.yaml.
                              │
                              ▼
 Outer driver (run_plan_evolve.py):
   Copy validated output to the durable smoke-test location:
   experiments/SWE_bench_verified/layer3_smoke_test/Lean_guided_modification/
       passed_workflow_1_<inst>_lean.yaml
```

### Quickstart (step 3)

```bash
# Single instance
python leanagent/codegen/agent_evolve/run_plan_evolve.py \
    --source_staging_root workspace/agent_evolve_run/staging_gpt52 \
    --staging_root        workspace/agent_evolve_run/staging_gpt52_evolve \
    --plan_name           passed_workflow_1 \
    --original_plan_yaml  experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --yaml_plan           leanagent/codegen/agent_evolve/evolve_plan.yaml \
    --single_instance     django__django-14140

# Batch over all instances for which step 2 produced a layer3_query.json
python leanagent/codegen/agent_evolve/run_plan_evolve.py \
    --source_staging_root workspace/agent_evolve_run/staging_gpt52 \
    --staging_root        workspace/agent_evolve_run/staging_gpt52_evolve \
    --plan_name           passed_workflow_1 \
    --original_plan_yaml  experiments/SWE_bench_verified/passed_workflow_1.yaml \
    --limit 10 --max_parallel 3 --resume
```

### Resume semantics

An instance is considered complete iff

  - `<smoke_test_output_dir>/passed_workflow_1_<inst>_lean.yaml` exists, AND
  - `<staging_root>/outputs/<inst>/validation_report.json` shows
    `summary.pass: true`

Otherwise the driver restarts that instance from Phase 1 (idempotent: the YAML
begins with `cp original_plan.yaml → working_plan.yaml` which overwrites any
partial state from a prior interrupted run).

### Per-instance staging tree

```
staging_gpt52_evolve/
  package/                   # EditYaml.py, EditJson.py, lean_report_loader.py, plan_validator.py
  inputs/<inst>/             # original_plan.yaml, layer3_query.json, eval_evidence.json
  staging/<inst>/            # working_plan.yaml, plan_evolve_digest.json, eval_evidence.json
  outputs/<inst>/            # evolved_plan.yaml, validation_report.json
  runtime/<inst>/            # driver.log
```

## Relation to upstream skills

- `trace-to-layer3` (one-shot Claude skill) — `annotate_layer3.yaml` is the
  executable equivalent.
- `lean-guided-plan-evolve` (one-shot Claude skill) — `evolve_plan.yaml` is the
  batch, per-node executable equivalent.
- `baseline-plan-evolve` — the control arm for the smoke-test A/B (pure LLM,
  no Layer 2, no Layer 3). Writes to the sibling `layer3_smoke_test/baseline/`
  directory.

## Relation to the Lean framework

The generated `.lean` imports and discharges the per-step move analysis (`PerStepView`)
from `FormalAgentLib/AgentVerifier/DynamicVerification/`. Running the `.lean` on a host with Lean
(optional, out of scope here) produces a per-step per-predicate verdict report that the
downstream `lean-guided-plan-evolve` skill parses into YAML rewrite guidance.
