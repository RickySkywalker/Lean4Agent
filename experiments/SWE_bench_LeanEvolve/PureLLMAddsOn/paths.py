#!/usr/bin/env python3
"""
staging_paths.py - Shared constants and path helpers for the llm_evolve package.

Mirrors `leanagent/codegen/agent_evolve/staging_paths.py` so the batch driver and the YAML
task plan cannot drift on layout. The staging tree lives under `<staging_root>`
(which must itself be inside `<workspace_root>` so Docker mounts it under
/workspace/...).
"""

from __future__ import annotations

from pathlib import Path


# --- per-instance subdirs of <staging_root>/ ---
PACKAGE_SUBDIR = "package"
INPUTS_SUBDIR = "inputs"
STAGING_SUBDIR = "staging"
OUTPUTS_SUBDIR = "outputs"
RUNTIME_SUBDIR = "runtime"

# --- per-instance filenames under inputs/<inst>/ ---
INPUT_ORIGINAL_YAML = "original_plan.yaml"
INPUT_EVENT_LOG = "agent_events.log"        # copied as-is (name rewritten)
INPUT_REPORT_JSON = "report.json"
INPUT_TEST_OUTPUT = "test_output.txt"

# --- per-instance filenames under staging/<inst>/ ---
STAGING_WORKING_YAML = "working_plan.yaml"
STAGING_TRACE_INDEX = "trace_index.json"
STAGING_EVAL_EVIDENCE = "eval_evidence.json"
STAGING_AMENDMENTS_DIGEST = "amendments_digest.json"

# --- per-instance filenames under outputs/<inst>/ ---
OUTPUT_EVOLVED_YAML = "evolved_plan.yaml"
OUTPUT_VALIDATION_REPORT = "validation_report.json"

# --- durable output subdir (where step-4 re-inference reads from) ---
# Sibling of `layer3_smoke_test/baseline/` (skill-produced) and
# `layer3_smoke_test/Lean_guided_modification/` (Lean-guided arm).
DURABLE_OUTPUT_SUBDIR = (
    "experiments/SWE_bench_verified/layer3_smoke_test/LLM_only_evolve"
)

# Filename suffix (mirrors `_lean.yaml` convention of the Lean arm).
DURABLE_YAML_SUFFIX = "_llm.yaml"


def instance_inputs_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / INPUTS_SUBDIR / instance_id


def instance_staging_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / STAGING_SUBDIR / instance_id


def instance_outputs_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / OUTPUTS_SUBDIR / instance_id


def instance_runtime_dir(staging_root: Path, instance_id: str) -> Path:
    return staging_root / RUNTIME_SUBDIR / instance_id


def package_dir(staging_root: Path) -> Path:
    return staging_root / PACKAGE_SUBDIR


def durable_output_dir(repo_root: Path) -> Path:
    return repo_root / DURABLE_OUTPUT_SUBDIR


def durable_yaml_path(repo_root: Path, plan_name: str, instance_id: str) -> Path:
    return (durable_output_dir(repo_root) /
            f"{plan_name}_{instance_id}{DURABLE_YAML_SUFFIX}")


def instance_event_log_path(staging_root: Path, instance_id: str) -> Path:
    """Canonical staged event log filename under inputs/<inst>/. The original
    file in `--outputs_root` is named `<inst>_agent_events.log`; we rename it
    to a stable `agent_events.log` inside the staging tree so the YAML plan
    doesn't need to know the instance id."""
    return instance_inputs_dir(staging_root, instance_id) / INPUT_EVENT_LOG


def instance_report_json_path(staging_root: Path, instance_id: str) -> Path:
    return instance_inputs_dir(staging_root, instance_id) / INPUT_REPORT_JSON


def instance_test_output_path(staging_root: Path, instance_id: str) -> Path:
    return instance_inputs_dir(staging_root, instance_id) / INPUT_TEST_OUTPUT


def instance_original_yaml_path(staging_root: Path, instance_id: str) -> Path:
    return instance_inputs_dir(staging_root, instance_id) / INPUT_ORIGINAL_YAML


def instance_working_yaml_path(staging_root: Path, instance_id: str) -> Path:
    return instance_staging_dir(staging_root, instance_id) / STAGING_WORKING_YAML


def instance_amendments_digest_path(staging_root: Path, instance_id: str) -> Path:
    return (instance_staging_dir(staging_root, instance_id)
            / STAGING_AMENDMENTS_DIGEST)


def instance_validation_report_path(staging_root: Path, instance_id: str) -> Path:
    return (instance_outputs_dir(staging_root, instance_id)
            / OUTPUT_VALIDATION_REPORT)


def instance_evolved_yaml_path(staging_root: Path, instance_id: str) -> Path:
    return (instance_outputs_dir(staging_root, instance_id)
            / OUTPUT_EVOLVED_YAML)
