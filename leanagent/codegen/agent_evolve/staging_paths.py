#!/usr/bin/env python3
"""
staging_paths.py - Shared constants and path helpers for the agent_evolve package.

Both step 2's driver (`run_agent_evolve.py`, the Layer-3 auto-annotation pipeline)
and step 3's driver (`run_plan_evolve.py`, the Lean-guided YAML plan evolution)
read/write into the same `<staging_root>/` directory tree. This module is the
single source of truth for that layout so the two drivers cannot drift.
"""

from __future__ import annotations

from pathlib import Path

# --- step 2 artifacts: the Lean-query JSON mirror ---
LEAN_REPL_SUBDIR = "lean_repl"
LEAN_GENERATED_SUBDIR = "agent_evolve_generated"  # under VerificationExamples/

# --- per-instance subdirs (shared between step 2 and step 3) ---
PACKAGE_SUBDIR = "package"
INPUTS_SUBDIR = "inputs"
STAGING_SUBDIR = "staging"
OUTPUTS_SUBDIR = "outputs"
RUNTIME_SUBDIR = "runtime"

# --- step 3 input / derived / output filenames (per-instance) ---
STEP3_INPUT_ORIGINAL_YAML = "original_plan.yaml"
STEP3_INPUT_LAYER3_QUERY = "layer3_query.json"
STEP3_INPUT_EVAL_EVIDENCE = "eval_evidence.json"
STEP3_STAGING_WORKING_YAML = "working_plan.yaml"
STEP3_STAGING_DIGEST = "plan_evolve_digest.json"
STEP3_OUTPUT_EVOLVED_YAML = "evolved_plan.yaml"
STEP3_OUTPUT_VALIDATION_REPORT = "validation_report.json"

# --- durable step-3 output (where step 4 reads evolved plans from) ---
SMOKE_TEST_LEAN_GUIDED_SUBDIR = (
    "experiments/SWE_bench_verified/layer3_smoke_test/Lean_guided_modification"
)


def lean_repl_staging_path(staging_root: Path, plan_name: str, instance_id: str) -> Path:
    """Canonical mirror path under <staging_root>/lean_repl/ for an instance's
    layer3_query.json. Step 2 writes here; step 3 reads from here."""
    return staging_root / LEAN_REPL_SUBDIR / f"{plan_name}_{instance_id}.json"


def step2_eval_evidence_path(staging_root: Path, instance_id: str) -> Path:
    """Step 2 writes eval_evidence.json here via eval_forensics.py. Step 3
    consumes it in Phase 1 to feed the whole-plan consistency review."""
    return staging_root / STAGING_SUBDIR / instance_id / "eval_evidence.json"


def step3_instance_inputs_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / INPUTS_SUBDIR / instance_id


def step3_instance_staging_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / STAGING_SUBDIR / instance_id


def step3_instance_outputs_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / OUTPUTS_SUBDIR / instance_id


def step3_instance_runtime_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / RUNTIME_SUBDIR / instance_id


def durable_evolved_plan_path(repo_root: Path, plan_name: str, instance_id: str) -> Path:
    """Where the validated evolved plan lands for step 4 to consume.
    Mirrors the naming of the five reference files already in that directory."""
    return (repo_root / SMOKE_TEST_LEAN_GUIDED_SUBDIR
            / f"{plan_name}_{instance_id}_lean.yaml")
