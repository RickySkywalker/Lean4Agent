#!/usr/bin/env python3
"""
elaip_LeanEvolve/run.py — End-to-end Lean-formal-guided plan evolution
for ELAIP-Bench.

Stages (per (plan, qid) pair, all resumable via per-stage sentinels):

  A.1 trace_segmenter        -> staging/<pair>/trace_index.json
  A.2 question_meta          -> staging/<pair>/question_meta.json (redacted)
  A.3 layer3_ir.seed.json    -> staging/<pair>/layer3_ir.seed.json
  A.4 layer3_ir.json         -> staging/<pair>/layer3_ir.json (LLM-annotated;
                                if --skip-annotate is set, equals the seed)
  A.5 per_step.lean          -> Verifier/.../ElaipExamples/<plan>_q<qid>_per_step.lean
  A.6 lean_diagnosis.txt     -> staging/<pair>/lean_diagnosis.txt
  A.7 layer3_query.json      -> staging/<pair>/layer3_query.json
  B.1 evolve_prompt.txt      -> staging/<pair>/evolve_prompt.txt
  B.2 evolved_plan.yaml      -> staging/<pair>/<plan>_q<qid>_lean.yaml
  B.3 validation_report.json -> staging/<pair>/validation_report.json
  B.4 durable evolved YAML   -> outputs/elaip_LeanEvolve/<model>/<plan>/evolved_plans/...
  C.1 stage_c_rerun          -> outputs/elaip_LeanEvolve/.../stage_c_rerun/runs/<qid>.json

`--resume` is the default; `--fresh` disables it. Resume sentinels propagate
through every sub-stage.

Filter: by default only (plan, qid) pairs where the source `runs/<qid>.json`
shows `is_correct == False` are enqueued. `--question-ids` overrides.
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

import yaml

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "FormalAgentLib").is_dir() and (p / "leanagent").is_dir())
HERE = Path(__file__).resolve().parent
PACKAGE_FILES = HERE / "package_files"
DEFAULT_LAYER2_IR_DIR = REPO_ROOT / "FormalAgentLib/VerificationExamples/elaipbench_layer2_v2_ir"
DEFAULT_LEAN_EXAMPLES_DIR = (REPO_ROOT
    / "FormalAgentLib/AgentVerifier/DynamicVerification/ElaipBench/ElaipExamples")
DEFAULT_PLANS_DIR = REPO_ROOT / "experiments/elaipbench"
LAKE_BUILD_TIMEOUT = int(os.environ.get("ELAIP_LAKE_TIMEOUT", "900"))

# The MCP sandbox VM mounts <REPO_ROOT>/workspace -> /workspace (rw). Anything
# the YAML's shell_run touches MUST live under that mount, and any path passed
# into the YAML's parameters must be in container view (/workspace/<rel>).
WORKSPACE_HOST_ROOT = (REPO_ROOT / "workspace").resolve()
WORKSPACE_VM_PREFIX = "/workspace"


def host_to_container_path(host_path: Path | str) -> str:
    """Translate a host absolute path under <REPO_ROOT>/workspace/ to its
    container-visible /workspace/<rel> equivalent. Used when populating env
    vars for the YAML agent so its shell_run sees the right files.

    Raises ValueError if the path is outside the workspace mount, because
    the MCP VM cannot reach it."""
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

def discover_failed_pairs(source_outputs_root: Path,
                          question_ids: set[int] | None,
                          question_type: str | None,
                          limit: int | None) -> list[dict]:
    """Walk source_outputs_root/runs/<qid>.json. Default behaviour: keep
    pairs where status==completed AND is_correct==False (no usable trajectory
    is dropped). When `question_ids` is supplied, every pair in the set is
    kept regardless of correctness."""
    runs_dir = source_outputs_root / "runs"
    if not runs_dir.exists():
        log(f"ERROR: source runs dir not found: {runs_dir}")
        return []
    out: list[dict] = []
    for path in sorted(runs_dir.glob("*.json")):
        if not re.match(r"^\d+\.json$", path.name):
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        qid = int(d.get("question_id", path.stem))
        if question_ids is not None and qid not in question_ids:
            continue
        if question_type and d.get("question_type") != question_type:
            continue
        if question_ids is None:
            # Default filter: only failed completed runs
            if d.get("status") != "completed":
                continue
            if d.get("is_correct"):
                continue
        out.append({"qid": qid, "info": d})
        if limit is not None and len(out) >= limit:
            break
    return out


def event_log_for(source_outputs_root: Path, qid: int) -> Path:
    return source_outputs_root / "runs" / "logs" / f"question_{qid}" / "agent_events.log"


# --------------------------------------------------------------------------- #
# Stage helpers — all idempotent: skip if sentinel exists (unless --fresh)
# --------------------------------------------------------------------------- #

def run_stage_a_segmenter(staging: Path, event_log: Path, qid: int, fresh: bool) -> bool:
    sentinel = staging / "trace_index.json"
    if sentinel.exists() and not fresh:
        return True
    cmd = [sys.executable, str(PACKAGE_FILES / "trace_segmenter.py"),
           "--event_log", str(event_log),
           "--staging_dir", str(staging),
           "--instance_id", f"q{qid}"]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and sentinel.exists()


def run_stage_a_redact(staging: Path, runs_json_path: Path, fresh: bool) -> bool:
    sentinel = staging / "question_meta.json"
    if sentinel.exists() and not fresh:
        return True
    src = json.loads(runs_json_path.read_text(encoding="utf-8"))
    redacted = {
        "question_id": src.get("question_id"),
        "question": src.get("question"),
        "question_type": src.get("question_type"),
        "paper_id": src.get("paper_id"),
        "status": src.get("status"),
    }
    sentinel.write_text(json.dumps(redacted, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return True


def run_stage_a_seed_ir(staging: Path, layer2_ir: Path, event_log: Path,
                        plan_name: str, qid: int, fresh: bool) -> bool:
    sentinel = staging / "layer3_ir.seed.json"
    if sentinel.exists() and not fresh:
        return True
    # Persist the source event log path on a sidecar file so the annotator
    # YAML can pick it up via the EVENT_LOG_PATH env var without needing
    # the host driver to re-thread it through every helper.
    (staging / "_source_event_log.txt").write_text(str(event_log.resolve()) + "\n",
                                                    encoding="utf-8")
    cmd = [sys.executable, str(PACKAGE_FILES / "elaip_layer3_ir_init.py"),
           "--layer2_ir", str(layer2_ir),
           "--event_log", str(event_log),
           "--question_id", str(qid),
           "--plan_name", plan_name,
           "--out", str(sentinel),
           "--banner_title", f"ELAIP {plan_name} × q{qid}"]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and sentinel.exists()


def run_stage_a_annotate(staging: Path, fresh: bool,
                          skip: bool = False,
                          model: str = "gpt-5.2",
                          plan_name: str = "passed_workflow_1",
                          qid: int = 0,
                          conda_env: str = "agent_env",
                          timeout_sec: int = 1200,
                          idle_timeout_sec: int = 600,
                          failure_patterns_path: Path | None = None) -> bool:
    """Stage A.4 — spawn `annotate_layer3_elaip.yaml` to fill llm_injections
    in the Layer-3 IR. Mirrors SWE's `annotate_layer3.yaml` structure with
    ELAIP-specific gates (no harness; JSON-shape rules instead).

    `skip=True` short-circuits: copies layer3_ir.seed.json -> layer3_ir.json
    so downstream phases can run without an annotator (useful for smoke
    tests or when LLM API is unavailable; the Lean+Tool verdicts still
    catch JSON-shape predicate violations on their own)."""
    sentinel = staging / "layer3_ir.json"
    if sentinel.exists() and not fresh:
        return True
    seed = staging / "layer3_ir.seed.json"
    if not seed.exists():
        return False
    if skip:
        sentinel.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
        return True
    # Otherwise: spawn the annotator YAML. Pre-stage the IR by copying the
    # seed (the YAML's per-step loop fills llm_injections by EditJson append).
    sentinel.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")

    # Preflight: every path the annotator's load tasks reference must exist.
    missing = validate_required_paths([
        ("trace_index.json", staging / "trace_index.json"),
        ("OUTPUT_IR_PATH (layer3_ir.json)", sentinel),
        ("QUESTION_META_PATH", staging / "question_meta.json"),
        ("PACKAGE_DIR", PACKAGE_FILES),
    ])
    if missing:
        log(f"  [Stage A.4 preflight] FAIL — missing inputs:")
        for m in missing:
            log(f"    - {m}")
        return sentinel.exists()  # seed IR survives so downstream still has something to read

    # Compute num_steps from the seeded IR's dyn_nodes count.
    try:
        ir = json.loads(sentinel.read_text(encoding="utf-8"))
        num_steps = len(ir.get("dyn_nodes") or [])
    except Exception:
        num_steps = 0
    if num_steps <= 0:
        log(f"  [Stage A.4 prep] dyn_nodes empty in seed IR — falling back to "
            f"seed IR without LLM annotations.")
        return True

    runtime_dir = staging / "annotate_runtime"
    # The annotator only reads files inside STAGING_DIR (already under the
    # workspace mount thanks to process_pair). EVENT_LOG_PATH and
    # LAYER2_IR_PATH live OUTSIDE workspace/ so we don't reference them from
    # the YAML — Stage A.1/A.3 (Python) already consumed them. Copy
    # package_files into workspace every spawn so edits to package_files/
    # (e.g. a new EditJson.py --list_extend mode) propagate without
    # requiring users to manually remove the cached workspace dir.
    workspace_pkg_dir = WORKSPACE_HOST_ROOT / "elaip_LeanEvolve_pkg"
    workspace_pkg_dir.mkdir(parents=True, exist_ok=True)
    for f in PACKAGE_FILES.iterdir():
        if f.is_file():
            shutil.copy2(f, workspace_pkg_dir / f.name)

    workspace_failure_patterns = staging / "failure_patterns.md"
    if failure_patterns_path and Path(failure_patterns_path).exists():
        shutil.copyfile(failure_patterns_path, workspace_failure_patterns)
    else:
        workspace_failure_patterns.write_text("", encoding="utf-8")

    env = {
        "MODEL_NAME": model,
        "PAIR_ID": f"{plan_name}__q{qid}",
        "PLAN_NAME": plan_name,
        "QID": str(qid),
        # The annotator YAML no longer touches EVENT_LOG_PATH or LAYER2_IR_PATH
        # — Stage A.1 / A.3 (Python) already consumed them. Pass empty strings
        # so any leftover ${...} references resolve to harmless empties.
        "EVENT_LOG_PATH": "",
        "LAYER2_IR_PATH": "",
        "QUESTION_META_PATH": host_to_container_path(staging / "question_meta.json"),
        "STAGING_DIR": host_to_container_path(staging),
        "OUTPUT_IR_PATH": host_to_container_path(sentinel),
        "PACKAGE_DIR": host_to_container_path(workspace_pkg_dir),
        "FAILURE_PATTERNS_PATH": host_to_container_path(workspace_failure_patterns),
        "NUM_STEPS": str(num_steps),
    }
    log(f"  [Stage A.4] annotate_layer3_elaip.yaml for {plan_name} q{qid} "
        f"(num_steps={num_steps})")
    rc = run_yaml_agent(
        yaml_path=HERE / "annotate_layer3_elaip.yaml",
        env_overrides=env,
        runtime_dir=runtime_dir,
        timeout_sec=timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        conda_env=conda_env,
        resume=not fresh,
        log_label=f"annotate-{plan_name}__q{qid}",
    )
    if rc != 0:
        log(f"  [Stage A.4] annotator rc={rc} (see {runtime_dir / 'driver.log'}). "
            f"Falling back to seed IR (Lean+Tool verdicts only).")
        sentinel.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
    return sentinel.exists()


def _resolve_layer2_ir(plan_name: str) -> Path:
    return (REPO_ROOT / "FormalAgentLib/VerificationExamples/elaipbench_layer2_v2_ir"
            / f"{plan_name}_layer2_v2.ir.json").resolve()


def run_stage_a_codegen(staging: Path, lean_out: Path, fresh: bool) -> bool:
    if lean_out.exists() and not fresh:
        return True
    layer3_ir = staging / "layer3_ir.json"
    if not layer3_ir.exists():
        return False
    cmd = [sys.executable, str(HERE / "elaip_layer3_codegen.py"),
           "--ir", str(layer3_ir),
           "--out", str(lean_out)]
    rc = subprocess.run(cmd, check=False).returncode
    return rc == 0 and lean_out.exists()


def lean_module_for_lean_path(lean_path: Path) -> str:
    """Translate a path under FormalAgentLib/AgentVerifier/... to its Lean module name."""
    verifier_root = REPO_ROOT / "FormalAgentLib"
    rel = lean_path.relative_to(verifier_root).with_suffix("")
    return ".".join(rel.parts)


def run_stage_a_lake_build(staging: Path, lean_path: Path, fresh: bool) -> bool:
    sentinel = staging / "lean_diagnosis.txt"
    if sentinel.exists() and not fresh and sentinel.stat().st_size > 0:
        return True
    if not lean_path.exists():
        return False
    module = lean_module_for_lean_path(lean_path)
    verifier_dir = REPO_ROOT / "FormalAgentLib"
    cmd = ["lake", "build", module]
    log(f"  lake build {module}")
    proc = subprocess.run(cmd, cwd=str(verifier_dir),
                          capture_output=True, text=True, timeout=LAKE_BUILD_TIMEOUT,
                          check=False)
    out = (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or "")
    sentinel.write_text(out, encoding="utf-8")
    if proc.returncode != 0:
        log(f"  lake build returned {proc.returncode}; partial output saved")
    return sentinel.stat().st_size > 0


_VACUOUS_LEAN_REASONS = (
    "pending external verification",
    "no result injected",
    "variable absent in post-state",
)


def _is_vacuous_falsification(root_cause: str) -> bool:
    """A 'vacuous' falsification is one driven by missing information rather
    than concrete refutation. Triggers:

      - root_cause mentions ONLY `[Lean]` (i.e. tool & LLM didn't flag) AND
        the Lean reason is one of the vacuous markers (no rule available,
        variable not captured, or no LLM injection forwarded).

    These should be downgraded to UNCERTAIN at the step level so Stage B
    doesn't spuriously rewrite steps the verifier has no evidence about.
    Concrete falsifications (e.g. JSON shape gate, enum violation, list
    overflow flagged by tool/LLM) are NOT downgraded."""
    if not root_cause:
        return False
    has_tool = "[Tool]" in root_cause
    has_llm = "[LLM]" in root_cause
    has_lean = "[Lean]" in root_cause
    if has_tool or has_llm:
        return False  # at least one non-Lean method has concrete falsification
    if not has_lean:
        return False  # nothing parsed; play safe
    lean_reason = root_cause.lower()
    return any(marker in lean_reason for marker in _VACUOUS_LEAN_REASONS)


def parse_lean_diagnosis(diagnosis: str) -> dict:
    """Parse the markdown-style report from `renderFullReport` into a
    structure compatible with `lean_report_loader.py`. Only the fields the
    downstream evolver reads are populated.

    Post-process: when ALL falsified predicates of a step are 'vacuous'
    (driven only by Lean's `pending external verification` / `no result
    injected` / `variable absent in post-state` with no Tool or LLM
    counter-evidence), downgrade the step verdict from `falsified` to
    `uncertain`. Stage B treats `falsified` as a rewrite mandate; vacuous
    falsifications were generating spurious mandates that drowned the
    real signal."""
    per_node: list[dict] = []
    step_re = re.compile(r"^Step\s+(\d+)\s+\((.+?)\)\s*$", re.MULTILINE)
    composite_re = re.compile(
        r"⇒ STEP COMPOSITE:\s*(✓ CONFIRMED|✗ FALSIFIED on predicate\(s\): (.+?)|\? UNKNOWN)"
        r"(?:\s*\n\s*RE-ROLL:\s*(.+?))?(?=\n\s*\n|\n\s*Step\s+\d|\Z)",
        re.DOTALL,
    )
    # NOTE: each `(.+?)` is followed by `\n` so it stops at end-of-line; the
    # final `composite` group is anchored to end-of-line so root_cause text
    # like "[Lean] pending external verification (no result injected)" is
    # captured in full instead of truncating to a single character.
    falsified_pred_re = re.compile(
        r"\[(\d+)\]\s+([^\s:]+)\s*:\s*([^\n]+)\n"
        r"\s*\[Lean\]\s+([✓✗])\s+([^\n]+)\n"
        r"\s*\[Tool\]\s+([✓✗])\s+([^\n]+)\n"
        r"\s*\[LLM\s*\]\s+([✓✗])\s+([^\n]*)\n"
        r"\s*⇒\s*(✗ FALSIFIED — [^\n]+|✓ CONFIRMED|\(sentinel\))",
    )

    matches = list(step_re.finditer(diagnosis))
    for i, m in enumerate(matches):
        sid = m.group(1)
        sname = m.group(2)
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(diagnosis)
        block = diagnosis[block_start:block_end]

        composite_m = composite_re.search(block)
        verdict = "uncertain"
        failed_preds: list[str] = []
        re_roll: str | None = None
        if composite_m:
            label = composite_m.group(1)
            if label.startswith("✓ CONFIRMED"):
                verdict = "confirmed"
            elif label.startswith("✗ FALSIFIED"):
                verdict = "falsified"
                failed_csv = composite_m.group(2) or ""
                failed_preds = [p.strip() for p in failed_csv.split(",") if p.strip()]
            elif label.startswith("? UNKNOWN"):
                verdict = "uncertain"
            re_roll = (composite_m.group(3) or "").strip() or None

        falsified_details: list[dict] = []
        for fm in falsified_pred_re.finditer(block):
            comp_label = fm.group(10) or ""
            if not comp_label.startswith("✗"):
                continue
            falsified_details.append({
                "var_name": fm.group(2),
                "predicate_type": fm.group(3).strip(),
                "lean_verdict": {"passed": fm.group(4) == "✓",
                                 "detail": fm.group(5).strip()},
                "tool_verdict": {"passed": fm.group(6) == "✓",
                                 "detail": fm.group(7).strip()},
                "llm_verdict": {"passed": fm.group(8) == "✓",
                                "detail": fm.group(9).strip()},
                "root_cause": comp_label.replace("✗ FALSIFIED — ", "").strip(),
            })

        # Vacuous-falsification downgrade. Two-pass: try the parsed
        # `falsified_details` first (richest), fall back to a regex scan
        # over the raw block when the regex couldn't capture all three
        # method lines (some predicates only emit [Lean]).
        if verdict == "falsified":
            if falsified_details:
                all_vacuous = all(_is_vacuous_falsification(d.get("root_cause", ""))
                                  for d in falsified_details)
            else:
                # Block-level scan: extract every "FALSIFIED — ..." root_cause and
                # check vacuousness on each.
                rc_re = re.compile(
                    r"⇒\s*✗\s*FALSIFIED\s+—\s+(.+?)(?=\n\s*\n|\n\s*\[\d+\]|\n\s*Step\s+\d|\Z)",
                    re.DOTALL,
                )
                root_causes = [m.group(1).strip() for m in rc_re.finditer(block)]
                all_vacuous = bool(root_causes) and all(
                    _is_vacuous_falsification(rc) for rc in root_causes)
            if all_vacuous:
                verdict = "uncertain"
                # Keep `failed_preds` and `re_roll` for diagnostic visibility,
                # but Stage B's per-step rewrite trigger is `verdict == "falsified"`,
                # so this downgrade silences spurious rewrites.

        per_node.append({
            "step_index": int(sid),
            "step_name": sname.strip(),
            "verdict": verdict,
            "failed_predicates": failed_preds,
            "re_roll_suggestion": re_roll,
            "falsified_predicate_details": falsified_details,
        })

    return {"per_node_results": per_node}


def run_stage_a_parse(staging: Path, fresh: bool) -> bool:
    sentinel = staging / "layer3_query.json"
    if sentinel.exists() and not fresh:
        return True
    diag = staging / "lean_diagnosis.txt"
    if not diag.exists():
        return False
    parsed = parse_lean_diagnosis(diag.read_text(encoding="utf-8"))
    sentinel.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# Stage B — LLM evolution
# --------------------------------------------------------------------------- #

# YAML workflow runner
sys.path.insert(0, str(PACKAGE_FILES))
from yaml_runner import run_yaml_agent  # type: ignore
from staging_prep import prepare_evolve_staging, validate_required_paths  # type: ignore

EVOLVE_PLAN_YAML = HERE / "evolve_plan_elaip.yaml"


def run_stage_b_via_yaml(staging: Path, original_yaml_path: Path,
                          durable_yaml_path: Path, model: str, plan_name: str,
                          qid: int, failure_patterns_path: Path | None,
                          conda_env: str, timeout_sec: int,
                          idle_timeout_sec: int, fresh: bool) -> bool:
    durable_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    working_yaml = staging / "working_plan.yaml"
    report_path = staging / "validation_report.json"
    runtime_dir = staging / "runtime"

    if (durable_yaml_path.exists() and report_path.exists() and not fresh):
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            if r.get("summary", {}).get("pass"):
                return True
        except Exception:
            pass

    # Deterministic prep: cp original->working, build_digest, seed_digest.
    # Doing this in Python (not via shell_run inside the YAML) avoids the
    # Qwen-style "directory doesn't exist" hallucinations we saw when the
    # agent tried to interpret SWE-flavoured `workspace_persistent/` paths.
    prep_ok, prep_info = prepare_evolve_staging(
        arm="lean", staging=staging, original_plan_yaml=original_yaml_path,
        layer3_query_path=staging / "layer3_query.json",
    )
    if not prep_ok:
        log(f"  [Stage B prep] FAIL: {prep_info.get('error')}")
        return False
    num_steps = int(prep_info.get("num_steps") or 0)
    if num_steps <= 0:
        log(f"  [Stage B prep] FAIL: num_steps=0 — empty plan_evolve_digest.json")
        return False

    # Preflight: every path the YAML's load_context phase will `cat` MUST exist
    # before we spawn the agent. If anything is missing we abort cleanly with
    # a concrete error instead of letting the LLM hallucinate filesystems.
    missing = validate_required_paths([
        ("ORIGINAL_PLAN_YAML", original_yaml_path),
        ("WORKING_PLAN_YAML", staging / "working_plan.yaml"),
        ("LAYER3_QUERY_PATH", staging / "layer3_query.json"),
        ("LEAN_DIAGNOSIS_PATH", staging / "lean_diagnosis.txt"),
        ("QUESTION_META_PATH", staging / "question_meta.json"),
        ("plan_evolve_digest.json", staging / "plan_evolve_digest.json"),
        ("amendments_digest.json", staging / "amendments_digest.json"),
        ("PACKAGE_DIR", PACKAGE_FILES),
    ])
    if missing:
        log(f"  [Stage B preflight] FAIL — missing inputs:")
        for m in missing:
            log(f"    - {m}")
        return False

    # Stage everything the YAML touches under the MCP-mounted workspace so
    # shell_run can actually `cat`/`cp` the files. Original plan YAML and
    # package_files live OUTSIDE workspace/, so we copy them in before
    # spawning. The YAML sees container paths (/workspace/<rel>); Python on
    # the host still uses the resolved host paths. Always re-copy so edits
    # to package_files/ (new flags, bugfixes) propagate without --fresh.
    workspace_pkg_dir = WORKSPACE_HOST_ROOT / "elaip_LeanEvolve_pkg"
    workspace_pkg_dir.mkdir(parents=True, exist_ok=True)
    for f in PACKAGE_FILES.iterdir():
        if f.is_file():
            shutil.copy2(f, workspace_pkg_dir / f.name)

    workspace_original_yaml = staging / "original_plan.yaml"
    shutil.copyfile(original_yaml_path, workspace_original_yaml)

    workspace_failure_patterns = staging / "failure_patterns.md"
    if failure_patterns_path and Path(failure_patterns_path).exists():
        shutil.copyfile(failure_patterns_path, workspace_failure_patterns)
    else:
        workspace_failure_patterns.write_text("", encoding="utf-8")

    # The durable YAML (which the YAML's cp writes via shell_run) is already
    # under the workspace mount thanks to process_pair re-rooting staging_root
    # under workspace/. The host-side outputs/ mirror is created by the
    # caller (process_pair) after this function returns.

    env = {
        "MODEL_NAME": model,
        "PAIR_ID": f"{plan_name}__q{qid}",
        "PLAN_NAME": plan_name,
        "QID": str(qid),
        "ORIGINAL_PLAN_YAML": host_to_container_path(workspace_original_yaml),
        "WORKING_PLAN_YAML": host_to_container_path(working_yaml),
        "DURABLE_YAML_PATH": host_to_container_path(durable_yaml_path),
        "LEAN_DIAGNOSIS_PATH": host_to_container_path(staging / "lean_diagnosis.txt"),
        "LAYER3_QUERY_PATH": host_to_container_path(staging / "layer3_query.json"),
        "QUESTION_META_PATH": host_to_container_path(staging / "question_meta.json"),
        "STAGING_DIR": host_to_container_path(staging),
        "INSTANCE_OUTPUT_DIR": host_to_container_path(staging),
        "PACKAGE_DIR": host_to_container_path(workspace_pkg_dir),
        "FAILURE_PATTERNS_PATH": host_to_container_path(workspace_failure_patterns),
        "NUM_STEPS": str(num_steps),
    }
    if failure_patterns_path and failure_patterns_path.exists():
        env["FAILURE_PATTERNS_PATH"] = str(failure_patterns_path.resolve())
    else:
        env["FAILURE_PATTERNS_PATH"] = ""

    log(f"  [Stage B] evolve_plan_elaip.yaml for {plan_name} q{qid} (model={model})")
    rc = run_yaml_agent(
        yaml_path=EVOLVE_PLAN_YAML,
        env_overrides=env,
        runtime_dir=runtime_dir,
        timeout_sec=timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        conda_env=conda_env,
        resume=not fresh,
        log_label=f"{plan_name}__q{qid}",
    )
    if rc != 0:
        log(f"  [Stage B] yaml agent rc={rc} (driver.log in {runtime_dir})")
    if not durable_yaml_path.exists():
        return False
    if report_path.exists():
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            return bool(r.get("summary", {}).get("pass"))
        except Exception:
            return False
    return False


EVOLVE_SYSTEM_PROMPT = """You are an expert at editing YAML agent workflow plans.

You will receive (1) the original YAML plan, (2) a structured Layer-3
diagnostic report listing which workflow steps had falsified postconditions
plus a re-roll suggestion per step, and (3) trajectory summaries.

Your job: rewrite ONLY the failing steps' `instruction:` text to address
the falsified predicate. Preserve every {{template}} reference, every step
name, every save_as, the system_prompt, parameters, and config. Output
the FULL rewritten YAML plan.

HARD RULES:
- DO NOT mention `is_correct`, `parsed_answer`, `correct_answer`, "ground
  truth", "Lean said", "predicate failed", "previously incorrect", "audit
  trail", or any reference to verification artefacts. The agent that runs
  the evolved plan must not see eval signal.
- DO NOT make assertions like "the correct answer is X" or "option B is
  right" — never leak option letters as answer claims.
- KEEP every {{templated}} variable that appears in the original instruction.
- KEEP step names and save_as fields byte-identical.
- Stay within roughly ±50% of the original instruction's length per step.
- Output the FULL evolved YAML, ready to be parsed by `yaml.safe_load`.
"""


def build_evolve_prompt(original_yaml: str, query: dict, summaries_block: str,
                        failure_patterns: str = "") -> str:
    failed = [
        n for n in query.get("per_node_results", [])
        if n.get("verdict") == "falsified"
    ]
    parts: list[str] = []
    parts.append("# Layer-3 diagnosis")
    parts.append(f"\n{len(failed)} step(s) had at least one falsified postcondition predicate:\n")
    for n in failed:
        parts.append(f"- Step {n['step_index']} `{n['step_name']}` — failed: "
                     f"{', '.join(n['failed_predicates']) or '(unknown)'}")
        if n.get("re_roll_suggestion"):
            parts.append(f"    RE-ROLL: {n['re_roll_suggestion']}")
        for d in n.get("falsified_predicate_details", [])[:5]:
            parts.append(f"    [{d['var_name']} : {d['predicate_type']}]"
                         f" lean={d.get('lean_verdict', {}).get('detail', '')[:120]}"
                         f" | tool={d.get('tool_verdict', {}).get('detail', '')[:120]}")

    parts.append("\n# Trajectory step summaries (compact)\n" + summaries_block)
    if failure_patterns:
        parts.append("\n# Reference failure patterns (data-derived; check whether any apply)\n"
                     + failure_patterns)

    parts.append("\n# Original YAML\n" + "```yaml\n" + original_yaml + "\n```\n")
    parts.append("\nReturn the FULL evolved YAML inside a single ```yaml fenced block. "
                 "Do not include any prose outside the fence.")
    return "\n".join(parts)


def llm_call(model: str, system: str, user: str, max_tokens: int = 16000,
             temperature: float = 0.3, timeout: int = 600) -> str:
    """Direct litellm call. Returns assistant text or raises."""
    # Lazy import so the package can be discovered without litellm.
    sys.path.insert(0, str(REPO_ROOT / "AgentSPEX" / "src"))
    from harness.llms.client import LLMClient, LLMConfig, normalize_model_name
    client = LLMClient(LLMConfig(timeout=timeout, num_retries=3,
                                  temperature=temperature))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    # NB: LLMClient.completion() returns the litellm response object directly
    # (it normalizes the model id internally); the (response, usage) 2-tuple is
    # only returned by completion_with_usage(). Unpacking the single response
    # here raised "too many values to unpack (expected 2)".
    resp = client.completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, KeyError):
        return str(resp)


def extract_yaml_from_response(text: str) -> str | None:
    m = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1)
    # Fallback: assume the whole response is YAML.
    if text.strip().startswith(("name:", "goal:", "system_prompt:")):
        return text
    return None


def collect_summaries_block(staging: Path, max_steps: int = 8,
                            max_per_summary: int = 1500) -> str:
    """Concatenate per-step summary markdowns with truncation."""
    out: list[str] = []
    for idx, p in enumerate(sorted(staging.glob("step_*_summary.md"))):
        if idx >= max_steps:
            break
        s = p.read_text(encoding="utf-8")
        if len(s) > max_per_summary:
            s = s[:max_per_summary] + "\n... [truncated]"
        out.append(f"## {p.name}\n{s}")
    return "\n\n".join(out)


def run_stage_b(staging: Path, original_yaml_path: Path, durable_yaml_path: Path,
                model: str, plan_name: str, qid: int,
                failure_patterns: str, fresh: bool) -> bool:
    """Stage B: build prompt -> LLM -> save evolved YAML -> validate -> repair."""
    durable_yaml_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_path = staging / "evolve_prompt.txt"
    response_path = staging / "evolve_response.txt"
    evolved_path = staging / f"{plan_name}_q{qid}_lean.yaml"
    report_path = staging / "validation_report.json"

    if (durable_yaml_path.exists() and report_path.exists() and not fresh):
        try:
            r = json.loads(report_path.read_text(encoding="utf-8"))
            if r.get("summary", {}).get("pass"):
                return True
        except Exception:
            pass

    if not prompt_path.exists() or fresh:
        query = json.loads((staging / "layer3_query.json").read_text(encoding="utf-8"))
        original_yaml = original_yaml_path.read_text(encoding="utf-8")
        summaries = collect_summaries_block(staging)
        prompt = build_evolve_prompt(original_yaml, query, summaries, failure_patterns)
        prompt_path.write_text(prompt, encoding="utf-8")

    if not response_path.exists() or fresh:
        log(f"  [Stage B] LLM evolve call for {plan_name} q{qid} (model={model})")
        prompt = prompt_path.read_text(encoding="utf-8")
        try:
            resp = llm_call(model, EVOLVE_SYSTEM_PROMPT, prompt)
        except Exception as e:
            log(f"  [Stage B] LLM call failed: {e}")
            response_path.write_text(f"# LLM error: {e}\n", encoding="utf-8")
            return False
        response_path.write_text(resp, encoding="utf-8")

    if not evolved_path.exists() or fresh:
        resp = response_path.read_text(encoding="utf-8")
        evolved = extract_yaml_from_response(resp)
        if evolved is None:
            log(f"  [Stage B] could not extract YAML from LLM response")
            return False
        # Validate it's parseable YAML
        try:
            yaml.safe_load(evolved)
        except yaml.YAMLError as e:
            log(f"  [Stage B] YAML parse failed: {e}")
            return False
        evolved_path.write_text(evolved, encoding="utf-8")

    # Validate
    cmd = [sys.executable, str(PACKAGE_FILES / "plan_validator.py"),
           "--working", str(evolved_path),
           "--original", str(original_yaml_path),
           "--report", str(report_path),
           "--repair"]
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        log(f"  [Stage B] plan_validator returned {rc}")
        return False

    # Copy to durable.
    durable_yaml_path.write_text(evolved_path.read_text(encoding="utf-8"),
                                  encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# Stage C — rerun on the single failed question
# --------------------------------------------------------------------------- #

def run_stage_c(durable_yaml: Path, qid: int, dataset: str | None,
                rerun_dir: Path, fresh: bool) -> bool:
    sentinel = rerun_dir / "runs" / f"{qid}.json"
    if sentinel.exists() and not fresh:
        try:
            d = json.loads(sentinel.read_text(encoding="utf-8"))
            if d.get("status") == "completed":
                return True
        except Exception:
            pass
    rerun_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable,
           str(REPO_ROOT / "experiments/elaipbench/run.py"),
           "--workflow-file", str(durable_yaml),
           "--question-ids", str(qid),
           "--output-dir", str(rerun_dir),
           "--max-parallel", "1",
           "--skip-eval", "--resume"]
    if dataset:
        cmd += ["--dataset", str(dataset)]
    log(f"  [Stage C] rerun: {' '.join(shlex.quote(c) for c in cmd[-6:])}")
    proc = subprocess.run(cmd, check=False)
    return sentinel.exists()


# --------------------------------------------------------------------------- #
# Per-pair orchestration
# --------------------------------------------------------------------------- #

def process_pair(args: argparse.Namespace, plan_name: str, qid: int,
                 source_outputs_root: Path) -> dict:
    pair_id = f"{plan_name}__q{qid}"
    # Default unified_staging_root MUST be under workspace/ so the MCP-mounted
    # sandbox VM can read/write files via shell_run. The user can override
    # with --unified-staging-root, but we re-resolve and refuse to spawn the
    # YAML if the override falls outside workspace/.
    default_root = (WORKSPACE_HOST_ROOT / "elaip_LeanEvolve" / args.model
                    / plan_name).resolve()
    staging_root = (Path(args.unified_staging_root).resolve()
                    if args.unified_staging_root else default_root)
    if not str(staging_root).startswith(str(WORKSPACE_HOST_ROOT)):
        log(f"WARNING: --unified-staging-root {staging_root} is OUTSIDE "
            f"{WORKSPACE_HOST_ROOT}; the YAML's shell_run cannot reach it. "
            f"Re-rooting under {default_root} instead.")
        staging_root = default_root
    staging = staging_root / "stage_a" / pair_id
    staging.mkdir(parents=True, exist_ok=True)
    # Durable evolved YAMLs now also live under the workspace tree (so the
    # YAML's `cp working durable` works); the host-side outputs/ tree gets a
    # mirrored copy post-Stage-B for cross-arm comparison.
    durable_dir = staging_root / "stage_b_evolved_plans"
    durable_dir.mkdir(parents=True, exist_ok=True)
    durable_yaml = durable_dir / f"{plan_name}_q{qid}_lean.yaml"
    host_outputs_durable_dir = (REPO_ROOT / "outputs" / "elaip_LeanEvolve"
                                 / args.model / plan_name / "evolved_plans")
    rerun_dir = staging_root / "stage_c_rerun"
    rerun_dir.mkdir(parents=True, exist_ok=True)
    lean_path = (Path(args.lean_examples_dir) / f"{plan_name}_q{qid}_per_step.lean").resolve()

    fresh = bool(args.fresh)
    result: dict[str, Any] = {
        "pair_id": pair_id, "plan_name": plan_name, "qid": qid,
        "stages": {}, "errors": [],
    }

    try:
        # A.1 trace_segmenter
        ok = run_stage_a_segmenter(staging, event_log_for(source_outputs_root, qid),
                                    qid, fresh=fresh)
        result["stages"]["A.1_segmenter"] = ok
        if not ok:
            result["errors"].append("A.1 trace_segmenter failed")
            return result
        # A.2 question_meta
        ok = run_stage_a_redact(staging,
                                 source_outputs_root / "runs" / f"{qid}.json",
                                 fresh=fresh)
        result["stages"]["A.2_redact"] = ok
        # A.3 seed IR
        layer2_ir = Path(args.source_layer2_ir or
                          (DEFAULT_LAYER2_IR_DIR / f"{plan_name}_layer2_v2.ir.json")).resolve()
        ok = run_stage_a_seed_ir(staging, layer2_ir,
                                   event_log_for(source_outputs_root, qid),
                                   plan_name, qid, fresh=fresh)
        result["stages"]["A.3_seed_ir"] = ok
        if not ok:
            result["errors"].append("A.3 seed IR failed")
            return result
        # A.4 annotate (LLM-driven if --use-yaml-workflow; stub if --skip-annotate)
        fp_path = Path(args.failure_patterns).resolve() if args.failure_patterns else None
        annotate_skip = bool(args.skip_annotate) and not args.use_yaml_workflow
        # Stage A annotate gets the FULL --per-instance-timeout-sec budget.
        # Halving it (the previous behaviour) was a bug: Stage B (evolve) is a
        # separate subprocess with its own timeout and was not actually
        # consuming half of the wall-clock budget; meanwhile Qwen3.5 / Gemma4
        # annotations need ~10–15 min minimum on contention, so a 15-min half
        # budget killed every instance just before it could finish.
        ok = run_stage_a_annotate(
            staging, fresh=fresh, skip=annotate_skip,
            model=args.model, plan_name=plan_name, qid=qid,
            conda_env=args.conda_env,
            timeout_sec=args.per_instance_timeout_sec,
            idle_timeout_sec=args.idle_timeout_sec,
            failure_patterns_path=fp_path,
        )
        result["stages"]["A.4_annotate"] = ok
        # A.5 codegen
        ok = run_stage_a_codegen(staging, lean_path, fresh=fresh)
        result["stages"]["A.5_codegen"] = ok
        if not ok:
            result["errors"].append("A.5 codegen failed")
            return result
        # A.6 lake build
        ok = run_stage_a_lake_build(staging, lean_path, fresh=fresh)
        result["stages"]["A.6_lake_build"] = ok
        if not ok:
            result["errors"].append("A.6 lake build failed")
            return result
        # A.7 parse diagnosis
        ok = run_stage_a_parse(staging, fresh=fresh)
        result["stages"]["A.7_parse"] = ok
        if not ok:
            result["errors"].append("A.7 parse diagnosis failed")
            return result

        if args.only_stage in ("A", "annotate", "stage_a"):
            return result

        # Stage B
        original_yaml = (Path(args.original_plan_yaml).resolve() if args.original_plan_yaml
                         else DEFAULT_PLANS_DIR / f"{plan_name}.yaml")
        if not original_yaml.exists():
            result["errors"].append(f"original YAML missing: {original_yaml}")
            return result
        if args.use_yaml_workflow:
            fp_path = Path(args.failure_patterns).resolve() if args.failure_patterns else None
            ok = run_stage_b_via_yaml(
                staging, original_yaml, durable_yaml,
                args.model, plan_name, qid, fp_path,
                args.conda_env, args.per_instance_timeout_sec,
                args.idle_timeout_sec, fresh=fresh,
            )
        else:
            ok = run_stage_b(staging, original_yaml, durable_yaml,
                              args.model, plan_name, qid,
                              args.failure_patterns_text, fresh=fresh)
        result["stages"]["B_evolve"] = ok
        # Mirror the workspace-side durable YAML to host-side outputs/ for
        # cross-arm comparison. Best-effort.
        if ok and durable_yaml.exists():
            try:
                host_outputs_durable_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(durable_yaml,
                                host_outputs_durable_dir
                                / f"{plan_name}_q{qid}_lean.yaml")
            except Exception as _e:
                log(f"  [Stage B post-copy] warning: {_e}")
        if not ok:
            result["errors"].append("B evolve failed")
            # Fail-safe salvage: when Stage B validation fails, copy the original
            # YAML verbatim to the durable path so Stage C still runs with
            # *something* — without this, validation_failed instances never reach
            # Stage C and we lose all downstream signal.
            if getattr(args, "fail_safe_salvage", True):
                try:
                    durable_yaml.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original_yaml, durable_yaml)
                    result["salvage"] = {
                        "mode": "full_fallback",
                        "reason": "Stage B did not produce a validated evolved plan; "
                                  "copied original verbatim so Stage C has something to rerun",
                    }
                    log(f"  [Stage B salvage] copied {original_yaml} -> {durable_yaml}")
                    # Mirror durable to host-side outputs/ for cross-arm comparison.
                    try:
                        host_outputs_durable_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(durable_yaml,
                                        host_outputs_durable_dir
                                        / f"{plan_name}_q{qid}_lean.yaml")
                    except Exception as _e:
                        log(f"  [Stage B post-salvage-copy] warning: {_e}")
                    # Fall through to Stage C with the salvaged durable_yaml.
                except Exception as e:
                    result["salvage"] = {"mode": "salvage_failed",
                                          "reason": f"{type(e).__name__}: {e}"}
                    return result
            else:
                return result

        if args.only_stage in ("B", "evolve", "stage_b"):
            return result

        # Stage C
        ok = run_stage_c(durable_yaml, qid, args.dataset, rerun_dir, fresh=fresh)
        result["stages"]["C_rerun"] = ok
        if not ok:
            result["errors"].append("C rerun did not produce runs/<qid>.json")
            return result
        # Read the rerun outcome
        rerun_path = rerun_dir / "runs" / f"{qid}.json"
        if rerun_path.exists():
            try:
                rd = json.loads(rerun_path.read_text(encoding="utf-8"))
                result["rerun_status"] = rd.get("status")
                result["rerun_is_correct"] = rd.get("is_correct")
                result["rerun_parsed_answer"] = rd.get("parsed_answer")
            except Exception:
                pass
    except Exception as e:
        result["errors"].append(f"unhandled exception: {e}\n{traceback.format_exc()}")

    return result


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--plan-name", required=True,
                   help="ELAIP plan name (e.g. passed_workflow_1)")
    p.add_argument("--source-outputs-root", required=True,
                   help="Path to outputs/<model>/<run>/<plan>/ from a prior elaipbench run.")
    p.add_argument("--source-layer2-ir", default="",
                   help="Override Layer-2 IR JSON (default: "
                        "FormalAgentLib/VerificationExamples/elaipbench_layer2_v2_ir/<plan>_layer2_v2.ir.json)")
    p.add_argument("--original-plan-yaml", default="",
                   help="Override original plan YAML (default: experiments/elaipbench/<plan>.yaml)")
    p.add_argument("--dataset", default="",
                   help="Local parquet dataset for the rerun stage (default: HuggingFace stream).")
    p.add_argument("--model", default="gpt-5.2",
                   help="LLM model for Stage B evolution and Stage C rerun.")

    p.add_argument("--question-ids", nargs="*", default=None,
                   help="Whitelist of qids (overrides default is_correct=False filter).")
    p.add_argument("--question-type", choices=["SA-MCQ", "MA-MCQ"], default=None)
    p.add_argument("--limit", type=int, default=0,
                   help="Cap on incomplete pairs (0 = no cap).")
    p.add_argument("--max-parallel", type=int, default=1)

    p.add_argument("--unified-staging-root", default="",
                   help="Single staging+outputs root. "
                        "Default: outputs/elaip_LeanEvolve/<model>/<plan>/")
    p.add_argument("--lean-examples-dir", default=str(DEFAULT_LEAN_EXAMPLES_DIR),
                   help="Where Layer-3 .lean files are written (default: ElaipBench/ElaipExamples/)")
    p.add_argument("--failure-patterns", default="",
                   help="Optional path to FAILURE_PATTERNS.md to inject into the evolve prompt")

    p.add_argument("--fresh", action="store_true", help="Disable --resume; re-run every sub-stage.")
    p.add_argument("--only-stage", choices=["A", "B", "C", "annotate", "evolve", "rerun"], default="")
    p.add_argument("--skip-annotate", action="store_true", default=True,
                   help="Skip the LLM annotator (default; the seed IR is used directly).")
    p.add_argument("--summary", default="", help="Path to write a JSON summary at the end.")
    p.add_argument("--use-yaml-workflow", action="store_true", default=True,
                   help="Default: spawn evolve_plan_elaip.yaml via scripts/run_agent.sh.")
    p.add_argument("--no-use-yaml-workflow", dest="use_yaml_workflow",
                   action="store_false")
    p.add_argument("--conda-env", default=os.environ.get("CONDA_DEFAULT_ENV", "agent_env"))
    p.add_argument("--per-instance-timeout-sec", type=int, default=1800)
    p.add_argument("--idle-timeout-sec", type=int, default=600)
    p.add_argument("--fail-safe-salvage", dest="fail_safe_salvage",
                   action="store_true", default=True,
                   help="When Stage B fails to produce a validated evolved plan, "
                        "copy the original YAML verbatim to the durable path so "
                        "Stage C still runs. Default ON.")
    p.add_argument("--no-fail-safe-salvage", dest="fail_safe_salvage",
                   action="store_false",
                   help="Strict behavior: drop pairs whose Stage B validation fails.")
    args = p.parse_args()

    if args.question_ids:
        flat: list[int] = []
        for chunk in args.question_ids:
            for s in chunk.split(","):
                s = s.strip()
                if s.isdigit():
                    flat.append(int(s))
        args.question_ids = set(flat) if flat else None
    else:
        args.question_ids = None

    if args.failure_patterns and Path(args.failure_patterns).exists():
        args.failure_patterns_text = Path(args.failure_patterns).read_text(encoding="utf-8")
    else:
        args.failure_patterns_text = ""

    return args


def main() -> int:
    args = parse_args()
    source_outputs_root = Path(args.source_outputs_root).resolve()
    pairs = discover_failed_pairs(source_outputs_root,
                                   args.question_ids,
                                   args.question_type,
                                   args.limit if args.limit else None)
    if not pairs:
        log("No (plan, qid) pairs to evolve.")
        return 0
    log(f"Discovered {len(pairs)} pair(s) to process; max_parallel={args.max_parallel}")

    summary: list[dict] = []
    if args.max_parallel > 1:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as ex:
            futures = {
                ex.submit(process_pair, args, args.plan_name, p["qid"], source_outputs_root): p["qid"]
                for p in pairs
            }
            for fut in as_completed(futures):
                summary.append(fut.result())
                log(f"[done] {summary[-1]['pair_id']}: {summary[-1].get('rerun_status')} "
                    f"(correct={summary[-1].get('rerun_is_correct')})")
    else:
        for p in pairs:
            r = process_pair(args, args.plan_name, p["qid"], source_outputs_root)
            summary.append(r)
            log(f"[done] {r['pair_id']}: stages={list(r['stages'].keys())} "
                f"errors={len(r['errors'])} rerun_correct={r.get('rerun_is_correct')}")

    log(f"\n{'='*60}\nSUMMARY ({len(summary)} pair(s) processed)")
    by_status: dict[str, int] = {}
    for r in summary:
        s = r.get("status") or "unknown"
        by_status[s] = by_status.get(s, 0) + 1
    for s, n in sorted(by_status.items()):
        log(f"  {s}: {n}")
    correct_after = sum(1 for r in summary if r.get("rerun_is_correct"))
    log(f"  rerun_is_correct=True: {correct_after}/{len(summary)}")

    if args.summary:
        Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
        log(f"summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
