# Lean4Agent

This is the official repository for *Lean4Agent: Formal Modeling and Verification for Agent Workflow and Trajectory*.

![MainPlot](./assets/figure/MainPlot.png)

## Introduction

We introduce **Lean4Agent**, to the best of our knowledge, the first framework that uses Lean4 to model and verify agent behavior. **Lean4Agent** introduces **FormalAgentLib**, an extensible Lean4 library for formally modeling and verifying agent workflows’ semantic consistency under explicit assumptions and localizing execution-time failures revealed by trajectories. Building on **FormalAgentLib**, we further develop **LeanEvolve**, which applies the results in **FormalAgentLib** to revise workflows and enhance their capabilities. Extensive experiments on a hard problem subset of SWE-Bench-Verified and a subset of ELAIP-Bench across 5 leading LLMs indicate that the verification-passing workflows outperform the failing ones by an average of **11.94%**, and **LeanEvolve** further improves SWE performance by **7.47%** on average. Furthermore, **Lean4Agent** establishes a foundation for a new field of using expressive dependent-type formal languages to formally model and verify agent behavior.

## Quickstart

### 1. Install dependencies

```bash
conda create -n Lean4Agent_env python=3.11
conda activate Lean4Agent_env
pip install -r requirements.txt
cd AgentSPEX
pip install -e .
cd ../
```

Then create your LLM credentials file from the shipped template (real `*.env` files are git-ignored, so every clone needs this once):

```bash
cp configs/LLM-config.env.example configs/LLM-config.env
```

### 2. Run a verification-passing workflow and compare it with a verification-failing one

#### 2.1 SWE-Bench 50-problem subset

`experiments/SWE_bench_verified/` ships paired SWE-Bench workflows: `passed_workflow_{1,2,3}.yaml` **pass** FormalAgentLib's Layer-2 semantic verification, while `failed_workflow_{1,2,3}.yaml` **fail** it. Running a passing and a failing workflow with the *same* model on the *same* instances and comparing how many issues each resolves reproduces the paper's core finding: verification-passing workflows outperform failing ones.

The example below uses **GLM-5 on AWS Bedrock**. Beyond Step 1, you also need a running **Docker** daemon (each instance is solved within its SWE-Bench container) and access to AWS Bedrock for `zai.glm-5` in `us-west-2`.

```bash
# the LLM/Bedrock config created in Step 1
source ./configs/LLM-config.env

DATA=./data/SWE_bench_verified_50problems_subset
INST=astropy__astropy-12907

# (a) verification-PASSING workflow  — swap in failed_workflow_1.yaml for the failing arm
python experiments/SWE_bench_verified/run.py \
  --workflow-file experiments/SWE_bench_verified/passed_workflow_1.yaml \
  --model "bedrock/zai.glm-5" \
  --dataset "$DATA" \
  --split test \
  --instance-ids "$INST" \
  --max-parallel 1 \
  --save-logs \
  --output-dir tmp/runs/passed_workflow_1

# (b) score each predictions.jsonl with the SWE-bench harness; compare `resolved` counts
python -m swebench.harness.run_evaluation --dataset_name "$DATA" \
  --predictions_path tmp/runs/passed_workflow_1/predictions.jsonl --run_id passed_1 --max_workers 4
```

#### 2.2 ELAIP-Bench 100-problem subset

**ELAIP-Bench** works the same way with `experiments/elaipbench/`: `passed_workflow_{1,2,3}.yaml` **pass** Layer-2 verification while `failed_workflow_{1,2,3}.yaml` **fails** it. Evaluation is integrated into `run.py`, so there is no separate scoring step.

```bash
source ./configs/LLM-config.env         # same glm-5 Bedrock config
DATA=./data/ELAIPBench_100problems_subset

# verification-PASSING workflow — swap in failed_workflow_1.yaml for the failing arm
python experiments/elaipbench/run.py \
  --workflow-file experiments/elaipbench/passed_workflow_1.yaml \
  --model "bedrock/zai.glm-5" \
  --dataset "$DATA" \
  --max-parallel 20 \
  --output-dir tmp/runs/elaip_passed_workflow_1
```

### 3. Try LeanEvolve

#### 3.1 LeanEvolve with environment feedback

On SWE tasks, the environment provides feedback (test results), which allows us to perform both LLM-based and Lean-based workflow evolution. `experiments/SWE_bench_LeanEvolve/` merges the two arms into one **correction cascade**: for every instance on which a workflow previously **failed**, it first re-rolls the workflow with **LeanEvolve** (Lean-formal-guided: annotate → evolve → rerun) and evaluates; each instance still failing is then re-rolled with the **LLMEvolve** baseline and evaluated. A problem counts as an *additional pass* if either arm resolves it. Both arms reuse their resumable staging trees, so the wrapper picks up prior work and re-runs only what is missing.

Prerequisites match Section 2.1 (a running **Docker** daemon and **AWS Bedrock** access to `zai.glm-5`), plus the AgentSPEX MCP sandbox for the evolve stages.

```bash
source ./configs/LLM-config.env

python -u experiments/SWE_bench_LeanEvolve/run.py \
  --plan-name passed_workflow_1 \
  --source-outputs-root tmp/runs/passed_workflow_1 \
  --source-eval-root tmp/runs/baseline_eval/logs/run_evaluation/glm5_baseline/bedrock__zai.glm-5 \
  --source-layer2-ir FormalAgentLib/VerificationExamples/layer2_v2_ir/passed_workflow_1_layer2_v2.ir.json \
  --dataset data/SWE_bench_verified_50problems_subset \
  --split test \
  --model "bedrock/zai.glm-5" \
  --conda-env Lean4Agent_env \
  --max-parallel 8
```

#### 3.2 LeanEvolve without environment feedback

Unlike SWE, ELAIP-Bench consists of multiple-choice questions, so there is no environment feedback to help fix errors. We therefore use the Lean-only LeanEvolve mode. The pipeline reuses a resumable staging tree, so re-launching picks up prior work and re-runs only what is missing. The evolving LLM sees **only the trajectory and the Lean diagnosis** — the evaluation outcome, the gold answer, and the raw model response never enter the prompt — so no answer or evaluation signal can leak into the evolved workflow.

```bash
source ./configs/LLM-config.env

python -u experiments/elaip_LeanEvolve/run.py \
  --plan-name passed_workflow_1 \
  --source-outputs-root tmp/runs/elaip_passed_workflow_1 \
  --source-layer2-ir FormalAgentLib/VerificationExamples/elaipbench_layer2/passed_workflow_1_layer2_v2.ir.json \
  --dataset data/ELAIPBench_100problems_subset \
  --model "bedrock/zai.glm-5" \
  --conda-env Lean4Agent_env \
  --no-use-yaml-workflow \
  --max-parallel 8 \
  --unified-staging-root tmp/runs/elaip_LeanEvolve_passed_workflow_1 \
  --summary tmp/runs/elaip_LeanEvolve_passed_workflow_1/_summary.json
```

## Lean verification examples

### 1. Layer-2 (Static Semantic Verification) examples

The SWE-Bench workflows live in `experiments/SWE_bench_verified/*.yaml` and the ELAIP-Bench workflows in `experiments/elaipbench/*.yaml`. Their formalized Layer-2 versions are in `FormalAgentLib/StaticSemanticWorkflowExamples/`. To check one in Lean (requires the Lean 4 toolchain via [`elan`](https://github.com/leanprover/elan); the version pinned in `FormalAgentLib/lean-toolchain` is picked up automatically):

```bash
cd FormalAgentLib
lake exe cache get   # fetch the prebuilt Mathlib cache (first time only)
lake build StaticSemanticWorkflowExamples.«ELAIP-Bench».passed_workflow_1
```

### 2. Layer-3 (Dynamic Verification) examples

The examples for our dynamic verification are in `FormalAgentLib/DynamicLayerExamples/*.lean`. Each file formalizes one recorded SWE-Bench trajectory and discharges the per-step verification obligations, ending with an `#eval` that prints the full three-channel Layer-3 report.

## Reference

```bibtex
@misc{wang2026lean4agent,
      title={Lean4Agent: Formal Modeling and Verification for Agent Workflow and Trajectory},
      author={Ruida Wang and Jerry Huang and Pengcheng Wang and Xuanqing Liu and Luyang Kong and Tong Zhang},
      year={2026},
      eprint={2606.06523},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2606.06523},
}
```
