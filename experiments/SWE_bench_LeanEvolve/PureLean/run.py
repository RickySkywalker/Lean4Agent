#!/usr/bin/env python3
"""
SWE_bench_LeanEvolve/PureLean/run.py — End-to-end Lean-formal-guided plan evolution
for SWE-Bench-Verified.

Self-contained A->B->C orchestrator, mirroring the ARCHITECTURE of
experiments/elaip_LeanEvolve/run.py while preserving SWE-Bench DOMAIN
behavior. Replaces the old `run_e2e.py` (now a thin deprecation shim) and the
two leanagent/codegen/agent_evolve drivers (run_agent_evolve.py +
run_plan_evolve.py); the per-instance stage logic is ported here and dispatches
the two YAML workflows via package_files/yaml_runner.run_yaml_agent instead of
an inline PTY spawn.

Stages (per instance, resumable via per-stage sentinels):

  A.1 trace_segmenter        -> staging/<inst>/trace_index.json
  A.2 eval_forensics         -> staging/<inst>/eval_evidence.json
  A.3 layer3_ir.seed.json    -> outputs/<inst>/layer3_ir.json (seed, in-place)
  A.4 annotate_layer3.yaml   -> outputs/<inst>/layer3_ir.json (LLM-annotated;
                                if --skip-annotate, equals the seed)
  A.5 ir_to_lean        -> results/<plan>_<inst>/per_step.lean
  A.6 lake build             -> compiled olean in FormalAgentLib/
  A.7 lean_query             -> results/<plan>_<inst>/layer3_query.json
                                + lean_repl/<plan>_<inst>.json (mirror)
  B.1 lean_report_loader     -> staging/<inst>/plan_evolve_digest.json
  B.2 evolve_plan.yaml       -> outputs/<inst>/evolved_plan.yaml
  B.3 plan_validator (gate)  -> outputs/<inst>/validation_report.json
  B.4 durable evolved YAML   -> <durable-plans-dir>/<plan>_<inst>_lean.yaml
  C   rerun.py               -> <stage-c-output-dir>/predictions.jsonl + *.diff

Stage C is dispatched ONCE over the directory of evolved per-instance plans by
spawning the sibling `rerun.py` (the SWE-bench Docker rerun runner). This is the
deliberate SWE-vs-elaip structural divergence: elaip reruns per-(plan,qid) with
its in-process benchmark, whereas the SWE rerun runner is directory-oriented and
manages its own per-instance SWE-bench Docker containers, watchdogs, and
ThreadPool parallelism. Running Stage A/B per-instance then Stage C once over the
durable plans dir preserves that SWE behavior.

`--resume` is the default; `--fresh` disables it. Stage A/B sub-stage sentinels
mirror the resume model of the original run_agent_evolve / run_plan_evolve.

Filter: by default only instances whose prior SWE-bench eval `report.json`
shows `resolved == False` are enqueued. `--instance-ids` overrides;
`--skip-resolved` is implied by the default filter.

Invocation (typical):

    source ./experiments/SWE_bench_verified/gpt5.2_config.env
    python -u experiments/SWE_bench_LeanEvolve/PureLean/run.py \\
        --plan-name passed_workflow_1 \\
        --original-plan-yaml ./experiments/SWE_bench_verified/passed_workflow_1.yaml \\
        --source-outputs-root ./outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1 \\
        --source-eval-root   ./benchmark_results/.../logs/run_evaluation/passed_workflow_1/gpt-5.2 \\
        --source-layer2-ir   ./FormalAgentLib/VerificationExamples/layer2_v2_ir/passed_workflow_1_layer2_v2.ir.json \\
        --dataset ./data/test_dataset/SWE_bench_verified_50problems_subset \\
        --split   test --model gpt-5.2 \\
        --stage-c-output-dir outputs/gpt-5.2/SWE_bench_verified_50problems_subset/passed_workflow_1_regen \\
        --limit 10 --max-parallel 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = next(p for p in Path(__file__).resolve().parents
                 if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
HERE = Path(__file__).resolve().parent
PACKAGE_FILES = HERE / "package_files"

DEFAULT_LAYER2_IR_DIR = REPO_ROOT / "FormalAgentLib/VerificationExamples/layer2_v2_ir"
DEFAULT_PLANS_DIR = REPO_ROOT / "experiments/SWE_bench_verified"
DEFAULT_VERIFIER_DIR = REPO_ROOT / "FormalAgentLib"
LAKE_BUILD_TIMEOUT = int(os.environ.get("SWE_LEAN_LAKE_TIMEOUT", "600"))

# The MCP sandbox VM mounts <REPO_ROOT>/workspace -> /workspace (rw). Anything
# the YAML's shell_run touches MUST live under that mount, and any path passed
# into the YAML's parameters must be in container view (/workspace/<rel>).
WORKSPACE_HOST_ROOT = (REPO_ROOT / "workspace").resolve()
WORKSPACE_VM_PREFIX = "/workspace"

# Mirror leanagent/codegen/agent_evolve/staging_paths.py constants so the
# durable-results layout matches the original SWE pipeline (Stage B reads
# lean_repl/<plan>_<inst>.json that Stage A writes).
sys.path.insert(0, str(PACKAGE_FILES))
from yaml_runner import run_yaml_agent  # type: ignore  # noqa: E402
from staging_paths import (  # type: ignore  # noqa: E402
    LEAN_GENERATED_SUBDIR,
    lean_repl_staging_path,
)


def host_to_container_path(host_path: Path | str) -> str:
    """Translate a host absolute path under <REPO_ROOT>/workspace/ to its
    container-visible /workspace/<rel> equivalent. Raises ValueError if the
    path is outside the workspace mount (the MCP VM cannot reach it)."""
    host_resolved = Path(host_path).resolve()
    try:
        rel = host_resolved.relative_to(WORKSPACE_HOST_ROOT)
    except ValueError as e:
        raise ValueError(
            f"path is outside the MCP-mounted workspace and would not be "
            f"visible to shell_run inside the sandbox VM: {host_resolved} "
            f"(must live under {WORKSPACE_HOST_ROOT})"
        ) from e
    if str(rel) == ".":
        return WORKSPACE_VM_PREFIX
    return f"{WORKSPACE_VM_PREFIX}/{rel.as_posix()}"


_STDOUT_LOCK = threading.Lock()


def log(msg: str) -> None:
    with _STDOUT_LOCK:
        print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Filtering / discovery
# --------------------------------------------------------------------------- #

def find_instances(outputs_root: Path) -> list[str]:
    """Enumerate instances by the prior run's <inst>_agent_events.log files."""
    out: list[str] = []
    for p in sorted(outputs_root.glob("*_agent_events.log")):
        name = p.name
        if name.endswith("_agent_events.log"):
            out.append(name[: -len("_agent_events.log")])
    return out


def is_resolved(report_path: Path, instance_id: str) -> bool | None:
    """Read a SWE-bench eval report.json and return its `resolved` flag, or
    None if the report is missing / unparseable / lacks the instance key."""
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    block = data.get(instance_id) or (next(iter(data.values())) if len(data) == 1 else None)
    if not block:
        return None
    return bool(block.get("resolved", False))


def discover_failed_instances(source_outputs_root: Path, source_eval_root: Path,
                              instance_ids: set[str] | None,
                              limit: int | None) -> list[str]:
    """Walk source_outputs_root/*_agent_events.log. Default behaviour: keep
    instances whose prior eval report.json shows resolved==False (no usable
    trajectory is dropped). When `instance_ids` is supplied, every requested
    instance present in the prior run is kept regardless of resolution."""
    available = find_instances(source_outputs_root)
    if not available:
        log(f"ERROR: no instances found under {source_outputs_root} "
            f"(expected <inst>_agent_events.log files)")
        return []

    if instance_ids is not None:
        requested = [i for i in available if i in instance_ids]
        missing = sorted(instance_ids - set(available))
        if missing:
            log(f"WARNING: {len(missing)} requested instance(s) not in prior run "
                f"{source_outputs_root}: {missing}")
        out = requested
    else:
        out = []
        for inst in available:
            resolved = is_resolved(source_eval_root / inst / "report.json", inst)
            # Default filter: keep unresolved (resolved is False) instances.
            # resolved is None (no report) is kept too — a missing eval still
            # has a trajectory worth re-rolling.
            if resolved is True:
                continue
            out.append(inst)

    if limit is not None:
        out = out[:limit]
    return out


# --------------------------------------------------------------------------- #
# Stage A — annotate (ported from run_agent_evolve.run_instance)
# --------------------------------------------------------------------------- #

def _sanitize_for_lean_module(s: str) -> str:
    """Convert 'django__django-14140' -> 'django_django_14140' so it's a valid
    Lean module-name component."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return re.sub(r"_+", "_", out).strip("_")


def stage_a_dirs(staging_root: Path, instance_id: str) -> dict:
    """Per-instance Stage A workspace layout under staging_root (which lives
    under workspace/ so the MCP VM can read it). Mirrors run_agent_evolve's
    package/, inputs/<inst>/, staging/<inst>/, outputs/<inst>/ layout."""
    pkg = staging_root / "package"
    inputs = staging_root / "inputs" / instance_id
    staging = staging_root / "staging" / instance_id
    outputs = staging_root / "outputs" / instance_id
    for p in (pkg, inputs, staging, outputs):
        p.mkdir(parents=True, exist_ok=True)
    return {"pkg": pkg, "inputs": inputs, "staging": staging, "outputs": outputs}


def sync_package_files(pkg_dir: Path) -> None:
    """Copy package_files/*.py + the JSON template into the workspace package
    dir every spawn so edits to package_files/ propagate without --fresh."""
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for f in PACKAGE_FILES.iterdir():
        if f.is_file() and (f.suffix in (".py", ".json")):
            shutil.copy2(f, pkg_dir / f.name)


def run_stage_a_segmenter(staging: Path, event_log: Path, full_log: Path | None,
                          instance_id: str, fresh: bool) -> bool:
    sentinel = staging / "trace_index.json"
    if sentinel.exists() and not fresh:
        return True
    cmd = [sys.executable, str(PACKAGE_FILES / "trace_segmenter.py"),
           "--event_log", str(event_log),
           "--staging_dir", str(staging),
           "--instance_id", instance_id]
    if full_log and full_log.exists():
        cmd += ["--full_log", str(full_log)]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and sentinel.exists()


def run_stage_a_forensics(staging: Path, report: Path, test_output: Path,
                          instance_id: str, fresh: bool) -> bool:
    sentinel = staging / "eval_evidence.json"
    if sentinel.exists() and not fresh:
        return True
    cmd = [sys.executable, str(PACKAGE_FILES / "eval_forensics.py"),
           "--report", str(report),
           "--test_output", str(test_output),
           "--staging_dir", str(staging),
           "--instance_id", instance_id]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and sentinel.exists()


def run_stage_a_seed_ir(staging: Path, output_ir: Path, layer2_ir: Path,
                        instance_id: str, plan_name: str,
                        host_event_log: Path, host_report: Path,
                        prefix: str, suffix: str, fresh: bool) -> bool:
    """Seed the Layer-3 IR (empty exec_state/llm_injections). The annotate YAML
    fills it in per step. The HOST paths are embedded into the IR's report_path/
    event_log_path so `lake env lean` resolves them on the host (Stage A.6/A.7)."""
    if output_ir.exists() and not fresh:
        return True
    cmd = [sys.executable, str(PACKAGE_FILES / "layer3_ir_init.py"),
           "--layer2_ir", str(layer2_ir),
           "--trace_index", str(staging / "trace_index.json"),
           "--instance_id", instance_id,
           "--plan_name", plan_name,
           "--event_log_path", str(host_event_log.resolve()),
           "--report_path", str(host_report.resolve()),
           "--out", str(output_ir),
           "--prefix", prefix,
           "--suffix", suffix,
           "--banner_title", f"PER-STEP MOVE ANALYSIS — {instance_id}",
           "--banner_subtitle", "Layer 3 auto-annotated (SWE lean_evolve)"]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and output_ir.exists()


def run_stage_a_annotate(d: dict, output_ir: Path, instance_id: str,
                         plan_name: str, host_event_log: Path, host_report: Path,
                         prefix: str, suffix: str, model: str, conda_env: str,
                         timeout_sec: int, idle_timeout_sec: int,
                         skip: bool, fresh: bool) -> bool:
    """Stage A.4 — spawn annotate_layer3.yaml via run_yaml_agent to fill the
    Layer-3 IR's exec_state + llm_injections. The seed IR (run_stage_a_seed_ir)
    is the input; the YAML appends to it in place via EditJson.

    Sentinel: a non-empty llm_injections list in the IR. `skip=True` (or a
    failed agent) short-circuits to the seed IR so downstream phases still run
    (the Lean+Tool verdicts catch predicate violations on their own)."""

    def _has_injections() -> bool:
        try:
            ir = json.loads(output_ir.read_text(encoding="utf-8"))
            return len(ir.get("llm_injections") or []) > 0
        except Exception:
            return False

    if not output_ir.exists():
        return False
    if _has_injections() and not fresh:
        return True
    if skip:
        # Seed IR already at output_ir; nothing to do — Lean+Tool verdicts only.
        return True

    # Compute num_steps from the seeded IR's dyn_nodes count.
    try:
        ir = json.loads(output_ir.read_text(encoding="utf-8"))
        num_steps = len(ir.get("dyn_nodes") or [])
    except Exception:
        num_steps = 0
    if num_steps <= 0:
        log(f"  [Stage A.4 prep] dyn_nodes empty in seed IR for {instance_id}; "
            f"falling back to seed IR without LLM annotations.")
        return True

    sync_package_files(d["pkg"])

    runtime_dir = d["staging"] / "annotate_runtime"
    env = {
        "INSTANCE_ID": instance_id,
        "PLAN_NAME": plan_name,
        # Container-view paths the YAML's shell_run reads.
        "EVENT_LOG_PATH": host_to_container_path(d["inputs"] / "agent_events.log"),
        "FULL_LOG_PATH": (host_to_container_path(d["inputs"] / "full.log")
                          if (d["inputs"] / "full.log").exists() else ""),
        "REPORT_PATH": host_to_container_path(d["inputs"] / "report.json"),
        "TEST_OUTPUT_PATH": host_to_container_path(d["inputs"] / "test_output.txt"),
        "LAYER2_IR_PATH": host_to_container_path(d["inputs"] / "layer2_ir.json"),
        "STAGING_DIR": host_to_container_path(d["staging"]),
        "OUTPUT_IR_PATH": host_to_container_path(output_ir),
        "PACKAGE_DIR": host_to_container_path(d["pkg"]),
        # HOST-view paths embedded into the IR so Lean resolves them on the host.
        "HOST_EVENT_LOG_PATH": str(host_event_log.resolve()),
        "HOST_REPORT_PATH": str(host_report.resolve()),
        "PREFIX": prefix,
        "SUFFIX": suffix,
        "BANNER_TITLE": f"PER-STEP MOVE ANALYSIS — {instance_id}",
        "BANNER_SUBTITLE": "Layer 3 auto-annotated (SWE lean_evolve)",
        "MODEL_NAME": model,
    }
    log(f"  [Stage A.4] annotate_layer3.yaml for {instance_id} "
        f"(num_steps={num_steps}, model={model})")
    rc = run_yaml_agent(
        yaml_path=HERE / "annotate_layer3.yaml",
        env_overrides=env,
        runtime_dir=runtime_dir,
        timeout_sec=timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        conda_env=conda_env,
        resume=not fresh,
        log_label=f"annotate-{instance_id}",
    )
    if rc != 0:
        log(f"  [Stage A.4] annotator rc={rc} for {instance_id} "
            f"(see {runtime_dir / 'driver.log'}). Using seed/partial IR "
            f"(Lean+Tool verdicts only).")
    return output_ir.exists()


def run_stage_a_codegen(output_ir: Path, lean_out: Path, fresh: bool) -> bool:
    """Stage A.5 — ir_to_lean (pure-Python, codegen)."""
    if lean_out.exists() and not fresh:
        return True
    if not output_ir.exists():
        return False
    cmd = [sys.executable, str(PACKAGE_FILES / "ir_to_lean.py"),
           "--ir", str(output_ir), "--out", str(lean_out)]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and lean_out.exists()


def run_stage_a_lean(output_ir: Path, lean_out: Path, results_dir: Path,
                     staging_root: Path, plan_name: str, instance_id: str,
                     verifier_dir: Path, lean_timeout: int, fresh: bool) -> dict:
    """Stage A.6 + A.7 — copy the .lean into the Verifier tree, `lake build`
    the module, then run lean_query to emit a structured layer3_query.json.
    Ported from run_agent_evolve._run_lean_pipeline. Returns a result dict; the
    canonical sentinel is results_dir/layer3_query.json with per_node_results."""
    out: dict = {
        "lean_build_returncode": None,
        "lean_query_returncode": None,
        "lean_query_json": None,
        "lean_query_json_staging": None,
        "lean_error": None,
    }
    query_json = results_dir / "layer3_query.json"
    lean_repl_json = lean_repl_staging_path(staging_root, plan_name, instance_id)

    def _query_complete(p: Path) -> bool:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("errors"):
                return False
            # v2 schema emits `per_step`; legacy V1 emitted `per_node_results`.
            return len(d.get("per_step") or d.get("per_node_results") or []) > 0
        except Exception:
            return False

    if not fresh and _query_complete(query_json):
        out["lean_query_json"] = str(query_json)
        out["lean_build_returncode"] = 0
        out["lean_query_returncode"] = 0
        return out
    if not fresh and _query_complete(lean_repl_json):
        shutil.copy2(lean_repl_json, query_json)
        out["lean_query_json"] = str(query_json)
        out["lean_build_returncode"] = 0
        out["lean_query_returncode"] = 0
        return out

    try:
        ir_raw = json.loads(output_ir.read_text(encoding="utf-8"))
        prefix = ir_raw.get("prefix") or ""
        suffix = ir_raw.get("suffix") or ""
        if not prefix:
            raise ValueError("IR missing 'prefix'")
    except Exception as e:
        out["lean_error"] = f"failed to read IR for lean config: {e}"
        return out

    base_name = _sanitize_for_lean_module(f"{plan_name}_{instance_id}_per_step")

    # Verifier-tree copy (must be inside a lean_lib glob for lake to build it).
    verifier_subdir = verifier_dir / "VerificationExamples" / LEAN_GENERATED_SUBDIR
    verifier_subdir.mkdir(parents=True, exist_ok=True)
    gitignore_path = verifier_subdir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(
            "# Auto-generated by experiments/SWE_bench_LeanEvolve/PureLean/run.py\n"
            "*\n!.gitignore\n", encoding="utf-8")
    verifier_lean = verifier_subdir / f"{base_name}.lean"
    shutil.copy2(lean_out, verifier_lean)
    module_name = f"VerificationExamples.{LEAN_GENERATED_SUBDIR}.{base_name}"

    build_env = os.environ.copy()
    build_env.pop("COLUMNS", None)
    build_env.pop("LINES", None)
    build_env.setdefault("FORCE_COLOR", "1")
    build_env.setdefault("CLICOLOR_FORCE", "1")
    # lean_query lives under leanagent/; expose it so `python -m lean_query.cli`
    # resolves even though we run with cwd=FormalAgentLib (the Lean project).
    build_env["PYTHONPATH"] = (f"{REPO_ROOT / 'leanagent'}{os.pathsep}"
                               f"{build_env.get('PYTHONPATH', '')}")

    # --- lake build ---
    log(f"  [Stage A.6] lake build {module_name}")
    try:
        bp = subprocess.run(["lake", "build", module_name],
                            cwd=str(verifier_dir), capture_output=True, text=True,
                            timeout=lean_timeout, check=False, env=build_env)
    except subprocess.TimeoutExpired:
        out["lean_build_returncode"] = -1
        out["lean_error"] = f"lake build timed out after {lean_timeout}s"
        return out
    build_log = results_dir / "lake_build.log"
    build_log.write_text((bp.stdout or "") + "\n--- STDERR ---\n" + (bp.stderr or ""),
                         encoding="utf-8")
    out["lean_build_returncode"] = bp.returncode
    if bp.returncode != 0:
        out["lean_error"] = f"lake build failed (exit {bp.returncode}); see {build_log}"
        return out

    # --- lean_query ---
    config_yaml = results_dir / "lean_query_config.yaml"
    config_yaml.write_text("\n".join([
        f"lean_project_path: {verifier_dir}",
        f"target_file: VerificationExamples/{LEAN_GENERATED_SUBDIR}/{base_name}.lean",
        "layer: 3",
        f"workflow_graph: {prefix}Graph",
        f"semantic_graph: {prefix}SemanticGraph",
        f"goal_spec: {prefix}_goalSpec",
        f"dynamic_graph: dynamicGraph{suffix}",
        f"step_id_map: stepIdMap{suffix}",
        f"llm_injections: llmInjections{suffix}",
        f"exec_state: execState{suffix}",
        f"report_path_var: reportPath{suffix}",
        f"event_log_path_var: eventLogPath{suffix}",
        f"timeout_seconds: {lean_timeout}",
        "pretty_print: true",
    ]) + "\n", encoding="utf-8")

    query_log = results_dir / "lean_query.log"
    lean_repl_json.parent.mkdir(parents=True, exist_ok=True)
    out["lean_query_json_staging"] = str(lean_repl_json)

    log(f"  [Stage A.7] lean_query on {module_name}")
    try:
        qp = subprocess.run(
            [sys.executable, "-m", "lean_query.cli",
             "--config", str(config_yaml),
             "--timeout", str(lean_timeout),
             "--output", str(query_json)],
            cwd=str(verifier_dir), capture_output=True, text=True,
            timeout=lean_timeout + 30, env=build_env)
    except subprocess.TimeoutExpired:
        out["lean_query_returncode"] = -1
        out["lean_error"] = f"lean_query timed out after {lean_timeout}s"
        return out

    if not query_json.exists() and qp.stdout:
        query_json.write_text(qp.stdout, encoding="utf-8")
    query_log.write_text(qp.stderr or "", encoding="utf-8")
    if query_json.exists():
        shutil.copy2(query_json, lean_repl_json)
    out["lean_query_returncode"] = qp.returncode
    out["lean_query_json"] = str(query_json)
    if qp.returncode != 0:
        out["lean_error"] = f"lean_query failed (exit {qp.returncode}); see {query_log}"
    return out


# --------------------------------------------------------------------------- #
# Stage B — evolve (ported from run_plan_evolve.run_instance)
# --------------------------------------------------------------------------- #

def run_stage_b_digest(staging: Path, layer3_query: Path, eval_evidence: Path,
                       fresh: bool) -> bool:
    """Stage B.1 — build the per-step digest deterministically (Python, not via
    shell_run) so the LLM never has to interpret SWE workspace paths."""
    sentinel = staging / "plan_evolve_digest.json"
    if sentinel.exists() and not fresh:
        return True
    if not layer3_query.exists():
        return False
    cmd = [sys.executable, str(PACKAGE_FILES / "lean_report_loader.py"),
           "--layer3_query", str(layer3_query),
           "--out", str(sentinel)]
    if eval_evidence.exists():
        cmd += ["--eval_evidence", str(eval_evidence)]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and sentinel.exists()


def run_stage_b_evolve(d: dict, instance_id: str, plan_name: str,
                       original_yaml: Path, layer3_query: Path,
                       eval_evidence: Path, durable_yaml: Path,
                       shared_ledger: Path, template_frequency_cap: int,
                       model: str, conda_env: str, timeout_sec: int,
                       idle_timeout_sec: int, fresh: bool) -> bool:
    """Stage B.2 + B.3 — spawn evolve_plan.yaml via run_yaml_agent, then gate the
    durable copy on validation_report.json showing pass=true. Returns True iff a
    validated evolved plan was written to the staging outputs dir."""
    outputs = d["outputs"]
    working_yaml = d["staging"] / "working_plan.yaml"
    evolved_yaml = outputs / "evolved_plan.yaml"
    validation_report = outputs / "validation_report.json"

    def _validated() -> bool:
        try:
            rep = json.loads(validation_report.read_text(encoding="utf-8"))
            return bool((rep.get("summary") or {}).get("pass"))
        except Exception:
            return False

    if not fresh and evolved_yaml.exists() and _validated():
        return True

    # Stage everything the YAML touches under the workspace mount. The original
    # plan YAML and eval_evidence live OUTSIDE workspace/, so copy them in.
    sync_package_files(d["pkg"])
    ws_original = d["inputs"] / "original_plan.yaml"
    ws_query = d["inputs"] / "layer3_query.json"
    ws_eval = d["inputs"] / "eval_evidence.json"
    shutil.copy2(original_yaml, ws_original)
    if layer3_query.exists():
        shutil.copy2(layer3_query, ws_query)
    if eval_evidence.exists():
        shutil.copy2(eval_evidence, ws_eval)
    shared_ledger.mkdir(parents=True, exist_ok=True)

    runtime_dir = d["staging"] / "evolve_runtime"
    env = {
        "INSTANCE_ID": instance_id,
        "PLAN_NAME": plan_name,
        "ORIGINAL_PLAN_YAML": host_to_container_path(ws_original),
        "WORKING_PLAN_YAML": host_to_container_path(working_yaml),
        "LAYER3_QUERY_PATH": host_to_container_path(ws_query),
        "SOURCE_EVAL_EVIDENCE": host_to_container_path(ws_eval),
        "STAGING_DIR": host_to_container_path(d["staging"]),
        "INSTANCE_OUTPUT_DIR": host_to_container_path(outputs),
        "PACKAGE_DIR": host_to_container_path(d["pkg"]),
        "SHARED_LEDGER_DIR": host_to_container_path(shared_ledger),
        "TEMPLATE_FREQUENCY_CAP": str(template_frequency_cap),
        "MODEL_NAME": model,
    }
    log(f"  [Stage B] evolve_plan.yaml for {instance_id} (model={model})")
    rc = run_yaml_agent(
        yaml_path=HERE / "evolve_plan.yaml",
        env_overrides=env,
        runtime_dir=runtime_dir,
        timeout_sec=timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        conda_env=conda_env,
        resume=not fresh,
        log_label=f"evolve-{instance_id}",
    )
    if rc != 0:
        log(f"  [Stage B] yaml agent rc={rc} for {instance_id} "
            f"(driver.log in {runtime_dir})")

    if not evolved_yaml.exists():
        log(f"  [Stage B] evolved_plan.yaml not produced at {evolved_yaml}")
        return False
    if not validation_report.exists():
        log(f"  [Stage B] validation_report.json not found at {validation_report}")
        return False
    if not _validated():
        try:
            rep = json.loads(validation_report.read_text(encoding="utf-8"))
            fc = (rep.get("summary") or {}).get("failing_checks")
        except Exception:
            fc = "(unreadable)"
        log(f"  [Stage B] validation did not pass for {instance_id} "
            f"(failing_checks={fc})")
        return False

    # All good — copy to durable location for Stage C.
    durable_yaml.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(evolved_yaml, durable_yaml)
    return True


# --------------------------------------------------------------------------- #
# Per-instance orchestration (Stage A + Stage B)
# --------------------------------------------------------------------------- #

def process_instance(args: argparse.Namespace, instance_id: str,
                     source_outputs_root: Path, source_eval_root: Path,
                     staging_root: Path, results_dir: Path,
                     durable_plans_dir: Path, layer2_ir: Path,
                     original_yaml: Path, verifier_dir: Path) -> dict:
    plan_name = args.plan_name
    result: dict[str, Any] = {
        "instance_id": instance_id, "plan_name": plan_name,
        "stages": {}, "errors": [], "durable_output": None,
    }
    fresh = bool(args.fresh)

    # Prior-run inputs (forensics sources).
    event_log = source_outputs_root / f"{instance_id}_agent_events.log"
    full_log = source_outputs_root / f"{instance_id}_full.log"
    report = source_eval_root / instance_id / "report.json"
    test_output = source_eval_root / instance_id / "test_output.txt"
    for required in (event_log, report, test_output, layer2_ir):
        if not required.exists():
            result["errors"].append(f"missing input: {required}")
            result["stages"]["preflight"] = False
            return result

    d = stage_a_dirs(staging_root, instance_id)
    # Stage the per-instance forensics inputs into the workspace (the annotate
    # YAML's shell_run reads container-view copies under inputs/<inst>/).
    shutil.copy2(event_log, d["inputs"] / "agent_events.log")
    if full_log.exists():
        shutil.copy2(full_log, d["inputs"] / "full.log")
    shutil.copy2(report, d["inputs"] / "report.json")
    shutil.copy2(test_output, d["inputs"] / "test_output.txt")
    shutil.copy2(layer2_ir, d["inputs"] / "layer2_ir.json")

    output_ir = d["outputs"] / "layer3_ir.json"
    results_inst = results_dir / f"{plan_name}_{instance_id}"
    results_inst.mkdir(parents=True, exist_ok=True)
    lean_out = results_inst / "per_step.lean"
    layer3_query = results_inst / "layer3_query.json"
    eval_evidence = d["staging"] / "eval_evidence.json"
    prefix = f"{plan_name}_v2"
    suffix = ""  # let layer3_ir_init derive the numeric-tail suffix

    try:
        # --- Stage A ---
        ok = run_stage_a_segmenter(d["staging"], event_log,
                                   full_log if full_log.exists() else None,
                                   instance_id, fresh)
        result["stages"]["A.1_segmenter"] = ok
        if not ok:
            result["errors"].append("A.1 trace_segmenter failed")
            return result

        ok = run_stage_a_forensics(d["staging"], report, test_output,
                                   instance_id, fresh)
        result["stages"]["A.2_forensics"] = ok
        if not ok:
            result["errors"].append("A.2 eval_forensics failed")
            return result

        ok = run_stage_a_seed_ir(d["staging"], output_ir, layer2_ir, instance_id,
                                 plan_name, event_log, report, prefix, suffix, fresh)
        result["stages"]["A.3_seed_ir"] = ok
        if not ok:
            result["errors"].append("A.3 seed IR failed")
            return result

        annotate_skip = bool(args.skip_annotate)
        ok = run_stage_a_annotate(
            d, output_ir, instance_id, plan_name, event_log, report,
            prefix, suffix, args.model, args.conda_env,
            args.per_instance_timeout_sec, args.idle_timeout_sec,
            skip=annotate_skip, fresh=fresh)
        result["stages"]["A.4_annotate"] = ok

        ok = run_stage_a_codegen(output_ir, lean_out, fresh)
        result["stages"]["A.5_codegen"] = ok
        if not ok:
            result["errors"].append("A.5 ir_to_lean failed")
            return result

        if args.no_run_lean:
            result["stages"]["A.6_A.7_lean"] = "skipped"
        else:
            lean_res = run_stage_a_lean(
                output_ir, lean_out, results_inst, staging_root, plan_name,
                instance_id, verifier_dir, args.lean_timeout, fresh)
            result["lean"] = lean_res
            lean_ok = (lean_res.get("lean_query_returncode") == 0
                       and Path(layer3_query).exists())
            result["stages"]["A.6_A.7_lean"] = lean_ok
            if not lean_ok:
                result["errors"].append(
                    f"A.6/A.7 lean pipeline failed: {lean_res.get('lean_error')}")
                return result

        if args.only_stage in ("A", "annotate"):
            return result

        # --- Stage B ---
        ok = run_stage_b_digest(d["staging"], layer3_query, eval_evidence, fresh)
        result["stages"]["B.1_digest"] = ok
        if not ok:
            result["errors"].append("B.1 lean_report_loader (digest) failed")
            return result

        durable_yaml = durable_plans_dir / f"{plan_name}_{instance_id}_lean.yaml"
        shared_ledger = staging_root / "shared_ledger"
        ok = run_stage_b_evolve(
            d, instance_id, plan_name, original_yaml, layer3_query, eval_evidence,
            durable_yaml, shared_ledger, args.template_frequency_cap,
            args.model, args.conda_env, args.per_instance_timeout_sec,
            args.idle_timeout_sec, fresh)
        result["stages"]["B_evolve"] = ok
        if ok:
            result["durable_output"] = str(durable_yaml)
        else:
            result["errors"].append("B evolve failed (no validated evolved plan)")
            # Fail-safe salvage: copy the original verbatim so Stage C still
            # has something to rerun.
            if getattr(args, "fail_safe_salvage", True):
                try:
                    durable_yaml.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original_yaml, durable_yaml)
                    result["salvage"] = {
                        "mode": "full_fallback",
                        "reason": "Stage B did not produce a validated evolved "
                                  "plan; copied original verbatim so Stage C has "
                                  "something to rerun",
                    }
                    result["durable_output"] = str(durable_yaml)
                    log(f"  [Stage B salvage] copied {original_yaml.name} -> "
                        f"{durable_yaml.name}")
                except Exception as e:
                    result["salvage"] = {"mode": "salvage_failed",
                                         "reason": f"{type(e).__name__}: {e}"}
    except Exception as e:
        result["errors"].append(f"unhandled exception: {e}\n{traceback.format_exc()}")
    return result


# --------------------------------------------------------------------------- #
# Stage C — spawn rerun.py over the directory of evolved plans
# --------------------------------------------------------------------------- #

def run_stage_c(args: argparse.Namespace, durable_plans_dir: Path,
                stage_c_output_dir: Path, instance_ids: list[str]) -> int:
    """Stage C is directory-oriented: spawn the sibling rerun.py once over the
    durable evolved-plans dir. rerun.py manages its own per-instance SWE-bench
    Docker containers, watchdogs, and ThreadPool parallelism — preserving the
    SWE rerun behavior verbatim (this mirrors the old run_e2e.py Stage C)."""
    rerun = HERE / "rerun.py"
    if not rerun.exists():
        log(f"ERROR: Stage C runner not found: {rerun}")
        return 1
    stage_c_output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", str(rerun),
           "--task-plans-dir", str(durable_plans_dir),
           "--dataset", str(args.dataset),
           "--split", args.split,
           "--model", args.model,
           "--output-dir", str(stage_c_output_dir),
           "--max-parallel", str(args.max_parallel)]
    if instance_ids:
        cmd += ["--instance-ids", ",".join(instance_ids)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.save_logs:
        cmd += ["--save-logs"]
    if args.no_exclude:
        cmd += ["--no-exclude"]
    if args.per_instance_timeout_sec:
        cmd += ["--per-instance-timeout-sec", str(args.per_instance_timeout_sec)]
    if args.idle_timeout_sec is not None:
        cmd += ["--idle-timeout-sec", str(args.idle_timeout_sec)]
    if not args.fresh:
        cmd += ["--resume"]
    log(f"  [Stage C] $ {' '.join(shlex.quote(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=str(REPO_ROOT), check=False).returncode


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _model_slug(model: str) -> str:
    return "".join(ch for ch in model.lower() if ch.isalnum())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    # --- what plan we're evolving ---
    p.add_argument("--plan-name", required=True,
                   help="E.g. passed_workflow_1. Prefix for Lean/digest/evolved filenames.")
    p.add_argument("--original-plan-yaml", default="",
                   help="Original SWE-bench plan YAML being evolved "
                        "(default: experiments/SWE_bench_verified/<plan>.yaml).")

    # --- inputs from the prior SWE-bench run ---
    p.add_argument("--source-outputs-root", required=True,
                   help="Prior run's outputs dir with <inst>_agent_events.log "
                        "(+ optional <inst>_full.log) per instance.")
    p.add_argument("--source-eval-root", required=True,
                   help="Prior run's eval dir with <inst>/report.json + "
                        "<inst>/test_output.txt.")
    p.add_argument("--source-layer2-ir", default="",
                   help="Plan-level Layer-2 IR JSON (default: "
                        "FormalAgentLib/VerificationExamples/layer2_v2_ir/"
                        "<plan>_layer2_v2.ir.json).")

    # --- SWE-bench dataset + model ---
    p.add_argument("--dataset", required=True, help="HuggingFace dataset name or local path.")
    p.add_argument("--split", default="test")
    p.add_argument("--model", default="gpt-5.2",
                   help="LLM model for Stage A annotate / Stage B evolve / Stage C rerun.")

    # --- selection / concurrency ---
    p.add_argument("--instance-ids", nargs="*", default=None,
                   help="Whitelist of instance ids (overrides default resolved=False filter).")
    p.add_argument("--limit", type=int, default=0, help="Cap on instances (0 = no cap).")
    p.add_argument("--max-parallel", type=int, default=1)

    # --- staging / outputs ---
    p.add_argument("--unified-staging-root", default="",
                   help="Single staging+outputs root (MUST be under "
                        "<repo>/workspace/ so the MCP sandbox can read Stage A/B "
                        "files). Default: workspace/swe_lean_evolve/<model>/<plan>.")
    p.add_argument("--results-dir", default="",
                   help="Durable dir for Stage A layer3_ir.json / per_step.lean / "
                        "layer3_query.json. Default: <unified-root>/stage_a_results.")
    p.add_argument("--durable-plans-dir", default="",
                   help="Durable dir for evolved plans (input to Stage C). "
                        "Default: <unified-root>/stage_b_evolved_plans.")
    p.add_argument("--stage-c-output-dir", default="",
                   help="Where Stage C writes diffs + predictions.jsonl. "
                        "Default: <unified-root>/stage_c_rerun.")
    p.add_argument("--verifier-dir", default=str(DEFAULT_VERIFIER_DIR),
                   help="FormalAgentLib project (has lakefile.toml) for lake build + lean_query.")

    # --- stage knobs ---
    p.add_argument("--only-stage", choices=["A", "B", "annotate", "evolve"], default="",
                   help="Run only Stage A (annotate) or up to Stage B (evolve); "
                        "stop before Stage C.")
    p.add_argument("--skip-annotate", action="store_true",
                   help="Skip the LLM annotator; use the seed IR directly "
                        "(Lean+Tool verdicts only).")
    p.add_argument("--no-run-lean", action="store_true",
                   help="Skip the lake build + lean_query post-step (Stage A.6/A.7). "
                        "Stage B then has no layer3_query.json and is skipped.")
    p.add_argument("--lean-timeout", type=int, default=LAKE_BUILD_TIMEOUT,
                   help=f"Timeout (s) for lake build + lean_query (default: {LAKE_BUILD_TIMEOUT}).")
    p.add_argument("--template-frequency-cap", type=int, default=3,
                   help="Cross-instance classifier frequency cap passed to evolve_plan.yaml.")

    # --- Stage C passthrough ---
    p.add_argument("--save-logs", action="store_true", default=True,
                   help="Stage C: save full agent logs (default on).")
    p.add_argument("--no-save-logs", dest="save_logs", action="store_false")
    p.add_argument("--no-exclude", action="store_true", default=True,
                   help="Stage C: don't filter by excluded_instances.txt (default on).")
    p.add_argument("--per-instance-timeout-sec", type=int, default=10800,
                   help="Per-instance wallclock watchdog (s). Applies to Stage A/B "
                        "YAML agents and Stage C SWE-bench agents (default: 10800).")
    p.add_argument("--idle-timeout-sec", type=int, default=7200,
                   help="Idle watchdog (s); fires when an event log stops growing "
                        "(default: 7200; 0 disables).")
    p.add_argument("--conda-env", default=os.environ.get("CONDA_DEFAULT_ENV", "agent_env"))

    # --- orchestration ---
    p.add_argument("--fresh", action="store_true",
                   help="Disable --resume; re-run every sub-stage (does not delete artifacts).")
    p.add_argument("--fail-safe-salvage", dest="fail_safe_salvage",
                   action="store_true", default=True,
                   help="When Stage B fails validation, copy the original YAML "
                        "verbatim to the durable path so Stage C still runs (default on).")
    p.add_argument("--no-fail-safe-salvage", dest="fail_safe_salvage", action="store_false")
    p.add_argument("--summary", default="", help="Path to write a JSON summary at the end.")

    args = p.parse_args()

    # Flatten + normalize instance ids.
    if args.instance_ids:
        flat: list[str] = []
        for chunk in args.instance_ids:
            flat.extend(s.strip() for s in chunk.split(",") if s.strip())
        args.instance_ids = set(flat) if flat else None
    else:
        args.instance_ids = None

    return args


def _resolve_paths(args: argparse.Namespace) -> dict:
    """Resolve staging / results / durable / stage-c dirs. Staging MUST be under
    workspace/ (MCP-visible); we re-root it there if an override falls outside."""
    model_slug = _model_slug(args.model)
    default_unified = (WORKSPACE_HOST_ROOT / "swe_lean_evolve" / model_slug
                       / args.plan_name).resolve()
    unified = (Path(args.unified_staging_root).resolve()
               if args.unified_staging_root else default_unified)
    if not str(unified).startswith(str(WORKSPACE_HOST_ROOT)):
        log(f"WARNING: --unified-staging-root {unified} is OUTSIDE "
            f"{WORKSPACE_HOST_ROOT}; the YAML's shell_run cannot reach it. "
            f"Re-rooting under {default_unified} instead.")
        unified = default_unified

    staging_root = unified / "stage_ab"
    results_dir = (Path(args.results_dir).resolve() if args.results_dir
                   else unified / "stage_a_results")
    durable_plans_dir = (Path(args.durable_plans_dir).resolve() if args.durable_plans_dir
                         else unified / "stage_b_evolved_plans")
    stage_c_output_dir = (Path(args.stage_c_output_dir).resolve() if args.stage_c_output_dir
                          else unified / "stage_c_rerun")
    for pth in (staging_root, results_dir, durable_plans_dir, stage_c_output_dir):
        pth.mkdir(parents=True, exist_ok=True)
    return {
        "unified": unified,
        "staging_root": staging_root,
        "results_dir": results_dir,
        "durable_plans_dir": durable_plans_dir,
        "stage_c_output_dir": stage_c_output_dir,
    }


def main() -> int:
    args = parse_args()

    if not WORKSPACE_HOST_ROOT.exists():
        WORKSPACE_HOST_ROOT.mkdir(parents=True, exist_ok=True)

    source_outputs_root = Path(args.source_outputs_root).resolve()
    source_eval_root = Path(args.source_eval_root).resolve()
    layer2_ir = Path(args.source_layer2_ir).resolve() if args.source_layer2_ir \
        else (DEFAULT_LAYER2_IR_DIR / f"{args.plan_name}_layer2_v2.ir.json").resolve()
    original_yaml = Path(args.original_plan_yaml).resolve() if args.original_plan_yaml \
        else (DEFAULT_PLANS_DIR / f"{args.plan_name}.yaml").resolve()
    verifier_dir = Path(args.verifier_dir).resolve()

    if not layer2_ir.exists():
        log(f"ERROR: Layer-2 IR not found: {layer2_ir}")
        return 1
    if not original_yaml.exists():
        log(f"ERROR: original plan YAML not found: {original_yaml}")
        return 1
    if not args.no_run_lean and not (verifier_dir / "lakefile.toml").is_file():
        log(f"ERROR: --verifier-dir has no lakefile.toml: {verifier_dir}. "
            f"Pass --no-run-lean to skip the lake build + lean_query step.")
        return 1

    paths = _resolve_paths(args)
    instances = discover_failed_instances(
        source_outputs_root, source_eval_root,
        args.instance_ids, args.limit if args.limit else None)
    if not instances:
        log("No instances to evolve.")
        return 0
    log(f"Discovered {len(instances)} instance(s) to process; "
        f"max_parallel={args.max_parallel}")
    log(f"  unified staging root: {paths['unified']}")
    log(f"  durable plans dir:    {paths['durable_plans_dir']}")

    # --- Stage A + Stage B (per instance) ---
    summary: list[dict] = []
    if args.max_parallel > 1:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as ex:
            futures = {
                ex.submit(process_instance, args, inst, source_outputs_root,
                          source_eval_root, paths["staging_root"],
                          paths["results_dir"], paths["durable_plans_dir"],
                          layer2_ir, original_yaml, verifier_dir): inst
                for inst in instances
            }
            for fut in as_completed(futures):
                inst = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"instance_id": inst, "stages": {}, "durable_output": None,
                         "errors": [f"{type(e).__name__}: {e}"]}
                summary.append(r)
                log(f"[done] {r['instance_id']}: stages={list(r['stages'].keys())} "
                    f"errors={len(r['errors'])} durable={bool(r.get('durable_output'))}")
    else:
        for inst in instances:
            r = process_instance(args, inst, source_outputs_root, source_eval_root,
                                 paths["staging_root"], paths["results_dir"],
                                 paths["durable_plans_dir"], layer2_ir,
                                 original_yaml, verifier_dir)
            summary.append(r)
            log(f"[done] {r['instance_id']}: stages={list(r['stages'].keys())} "
                f"errors={len(r['errors'])} durable={bool(r.get('durable_output'))}")

    # --- Stage C (once, over the durable plans dir) ---
    stage_c_rc = None
    evolved_instances = [r["instance_id"] for r in summary if r.get("durable_output")]
    if args.only_stage in ("A", "B", "annotate", "evolve"):
        log(f"\n--only-stage={args.only_stage}: stopping before Stage C.")
    elif not evolved_instances:
        log("\nNo durable evolved plans produced; skipping Stage C.")
    else:
        log(f"\n{'='*60}\nSTAGE C: rerun {len(evolved_instances)} evolved plan(s)")
        stage_c_rc = run_stage_c(args, paths["durable_plans_dir"],
                                 paths["stage_c_output_dir"], evolved_instances)

    # --- Summary ---
    log(f"\n{'='*60}\nSUMMARY ({len(summary)} instance(s) processed)")
    n_durable = sum(1 for r in summary if r.get("durable_output"))
    n_errors = sum(1 for r in summary if r.get("errors"))
    log(f"  durable evolved plans: {n_durable}/{len(summary)}")
    log(f"  instances with errors: {n_errors}/{len(summary)}")
    if stage_c_rc is not None:
        log(f"  stage C returncode: {stage_c_rc}")

    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(
            json.dumps({"instances": summary, "stage_c_returncode": stage_c_rc},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"summary -> {args.summary}")

    return 0 if (stage_c_rc in (None, 0)) else stage_c_rc


if __name__ == "__main__":
    sys.exit(main())
