#!/usr/bin/env python3
"""
staging_prep.py — Deterministic Stage-B prep for ELAIP evolve pipelines.

The SWE evolve YAMLs put `cp original -> working`, `lean_report_loader.py`,
`seed_digest.py`, `count_steps`, etc. inside the YAML so the agent runs them
via shell_run. In ELAIP that pattern caused the LLM (especially Qwen-3.5)
to hallucinate fictional `workspace_persistent/` paths and refuse to follow
the YAML's instructions when any one of those shell calls hiccupped.

The clean fix: do all deterministic prep IN PYTHON before spawning the YAML
agent. The agent then only does LLM-judgment steps with paths it can trust.

Helpers:
  * prepare_evolve_staging — runs the cp/build_digest/seed_digest sequence
    for the lean / predicate / llm arms (selected via the `arm` argument).
  * validate_required_paths — preflight: check that every input the YAML
    will reference exists on disk. Returns a list of missing paths (empty
    on success).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def _run(cmd: list[str], label: str) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def prepare_evolve_staging(
    *,
    arm: str,
    staging: Path,
    original_plan_yaml: Path,
    layer3_query_path: Path | None,  # lean arm only
) -> tuple[bool, dict]:
    """Run cp + (lean: build_digest) + seed_digest deterministically.

    Returns (ok, info). On ok=False the YAML must NOT be spawned.
    """
    info: dict = {"arm": arm}
    staging.mkdir(parents=True, exist_ok=True)

    working_plan_yaml = staging / "working_plan.yaml"
    if not original_plan_yaml.exists():
        return False, {"error": f"original plan YAML not found: {original_plan_yaml}", **info}
    shutil.copyfile(original_plan_yaml, working_plan_yaml)
    info["working_plan_yaml"] = str(working_plan_yaml)

    if arm == "lean":
        if not layer3_query_path or not layer3_query_path.exists():
            return False, {"error": f"layer3_query.json missing: {layer3_query_path}", **info}
        digest_path = staging / "plan_evolve_digest.json"
        rc, _out, err = _run(
            [sys.executable, str(PACKAGE_DIR / "lean_report_loader.py"),
             "--layer3_query", str(layer3_query_path),
             "--out", str(digest_path)],
            "lean_report_loader",
        )
        if rc != 0:
            return False, {"error": f"lean_report_loader failed rc={rc}: {err[:400]}", **info}
        info["plan_evolve_digest"] = str(digest_path)
        try:
            digest = json.loads(digest_path.read_text(encoding="utf-8"))
            info["num_steps"] = len(digest)
        except Exception as e:
            return False, {"error": f"plan_evolve_digest.json malformed: {e}", **info}

    elif arm == "predicate":
        # predicate_evolve consumes predicates.json (already produced by Stage A)
        # and trajectory_evidence.json. Nothing new to compute here.
        pred_path = staging / "predicates.json"
        traj_path = staging / "trajectory_evidence.json"
        if not pred_path.exists() or not traj_path.exists():
            return False, {"error": "predicates.json or trajectory_evidence.json missing",
                            "predicates": str(pred_path), "trajectory_evidence": str(traj_path),
                            **info}
        info["num_steps"] = _count_executable_steps(pred_path)

    elif arm == "llm":
        traj_path = staging / "trajectory_evidence.json"
        if not traj_path.exists():
            return False, {"error": f"trajectory_evidence.json missing: {traj_path}", **info}
        info["num_steps"] = _count_steps_from_traj(traj_path)

    elif arm == "annotate":
        # The annotator runs as Stage A.4. Its prep is Stage A.1-A.3, already
        # done by run.py before this helper is called. No-op here.
        info["num_steps"] = _count_dyn_nodes(staging / "layer3_ir.seed.json")

    else:
        return False, {"error": f"unknown arm: {arm}", **info}

    rc, _out, err = _run(
        [sys.executable, str(PACKAGE_DIR / "seed_digest.py"),
         "--yaml", str(original_plan_yaml),
         "--out", str(staging / "amendments_digest.json")],
        "seed_digest",
    )
    if rc != 0:
        return False, {"error": f"seed_digest failed rc={rc}: {err[:400]}", **info}
    info["amendments_digest"] = str(staging / "amendments_digest.json")
    return True, info


def _count_executable_steps(predicates_path: Path) -> int:
    try:
        d = json.loads(predicates_path.read_text(encoding="utf-8"))
        return len(d.get("steps") or [])
    except Exception:
        return 0


def _count_steps_from_traj(traj_path: Path) -> int:
    try:
        d = json.loads(traj_path.read_text(encoding="utf-8"))
        return len(d.get("steps") or [])
    except Exception:
        return 0


def _count_dyn_nodes(ir_path: Path) -> int:
    try:
        d = json.loads(ir_path.read_text(encoding="utf-8"))
        return len(d.get("dyn_nodes") or [])
    except Exception:
        return 0


def validate_required_paths(paths: list[tuple[str, Path]]) -> list[str]:
    """Each entry is (label, path). Return a list of '<label>: <path>' for
    every missing path; empty list means everything is present."""
    missing: list[str] = []
    for label, p in paths:
        if not p or not Path(p).exists():
            missing.append(f"{label}: {p}")
    return missing
