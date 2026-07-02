"""Trajectory-evidence builder for the ELAIP evolve arms.

Builds per-step "what the agent actually saved" signals (saved-var json_valid,
list_length, keys_present, …) from a segmented trace index. Lives in the shared
`package_files/` next to `yaml_runner`/`staging_prep`.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import yaml


def _build_step_saved_var_map(original_yaml_path: Path) -> dict[str, str]:
    """Walk the original plan YAML and return a step_name -> save_as map.

    Authoritative — the YAML's actual `save_as:` fields are the source of
    truth, not a hand-curated table. Plans that introduce new step names
    don't need a code change here.
    """
    if not original_yaml_path or not original_yaml_path.exists():
        return {}
    try:
        d = yaml.safe_load(original_yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, str] = {}

    def walk(seq):
        for it in seq or []:
            if not isinstance(it, dict):
                continue
            for key, val in it.items():
                if key in ("task", "step") and isinstance(val, dict):
                    nm, sa = val.get("name"), val.get("save_as")
                    if nm and sa:
                        out[nm] = sa
                elif key in ("for_each", "while") and isinstance(val, dict):
                    walk(val.get("steps"))
                elif key == "if" and isinstance(val, dict):
                    walk(val.get("then"))
                    walk(val.get("else"))
                elif key == "switch" and isinstance(val, dict):
                    cases = val.get("cases") or {}
                    if isinstance(cases, dict):
                        for cs in cases.values():
                            walk(cs)
                    elif isinstance(cases, list):
                        for c in cases:
                            walk((c or {}).get("steps"))
                    walk(val.get("default"))
                elif key == "parallel" and isinstance(val, dict):
                    for br in val.get("branches") or []:
                        walk((br or {}).get("steps"))
    walk(d.get("workflow"))
    return out


def _try_parse_json_or_python(s: str) -> Any:
    """Strict JSON first; fall back to ast.literal_eval for the common case
    where the agent saved a dict with single quotes."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        return ast.literal_eval(s)
    except Exception:
        return None


def _trajectory_evidence_for_step(step_meta: dict, saved_var_value: str | None,
                                   saved_var_name: str) -> dict:
    parsed = _try_parse_json_or_python(saved_var_value or "")
    json_valid = parsed is not None
    keys_present: list[str] = []
    list_length: int | None = None
    if isinstance(parsed, dict):
        keys_present = sorted(parsed.keys())[:20]
        for k in ("evidence_snippets", "items", "snippets"):
            if k in parsed and isinstance(parsed[k], list):
                list_length = len(parsed[k])
                break
    elif isinstance(parsed, list):
        list_length = len(parsed)
    return {
        "step_id":                 step_meta.get("step_id", ""),
        "step_name":               step_meta.get("step_name", ""),
        "step_type":               step_meta.get("step_type", ""),
        "num_events":              step_meta.get("num_events", 0),
        "num_tool_calls":          step_meta.get("num_tool_calls", 0),
        "saved_var_name":          saved_var_name,
        "saved_var_value_truncated": (saved_var_value or "")[:1500],
        "saved_var_json_valid":    json_valid,
        "saved_var_keys_present":  keys_present,
        "list_length":             list_length,
    }


def _saved_vars_from_excerpts(trace_index: dict,
                               step_saved_var_map: dict[str, str]) -> dict[str, str]:
    """Walk per-step excerpt JSONLs and harvest the saved-variable value for
    each step. The next step's `step_start.data.variables` map captures the
    previous step's writes; fall back to the step's own excerpt when there
    is no next step.
    """
    saved: dict[str, str] = {}
    steps = trace_index.get("steps") or []
    for i, step in enumerate(steps):
        var_name = step_saved_var_map.get(step.get("step_name", ""))
        if not var_name:
            continue
        # Try the NEXT step's excerpt first.
        if i + 1 < len(steps):
            nx = Path(steps[i + 1].get("excerpt_path") or "")
            v = _read_var_from_step_start(nx, var_name)
            if v is not None:
                saved[step["step_id"]] = v
                continue
        # Fallback: the step's own excerpt may include a step_end with vars.
        own = Path(step.get("excerpt_path") or "")
        v = _read_var_from_step_start(own, var_name)
        if v is not None:
            saved[step["step_id"]] = v
    return saved


def _read_var_from_step_start(excerpt: Path, var_name: str) -> str | None:
    if not excerpt.exists():
        return None
    try:
        with excerpt.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "step_start":
                    continue
                v = (ev.get("data") or {}).get("variables") or {}
                if var_name in v:
                    val = v[var_name]
                    return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    except Exception:
        return None
    return None


def run_stage_a_trajectory_evidence(staging: Path, original_yaml_path: Path,
                                      fresh: bool) -> bool:
    sentinel = staging / "trajectory_evidence.json"
    if sentinel.exists() and not fresh:
        return True
    trace_index_path = staging / "trace_index.json"
    if not trace_index_path.exists():
        return False
    trace_index = json.loads(trace_index_path.read_text(encoding="utf-8"))
    step_saved_var_map = _build_step_saved_var_map(original_yaml_path)
    saved_vars = _saved_vars_from_excerpts(trace_index, step_saved_var_map)
    out = {
        "instance_id": trace_index.get("instance_id"),
        "model": trace_index.get("model"),
        "step_saved_var_map": step_saved_var_map,
        "steps": [
            _trajectory_evidence_for_step(
                s, saved_vars.get(s["step_id"], ""),
                step_saved_var_map.get(s.get("step_name", ""), ""))
            for s in trace_index.get("steps") or []
        ],
    }
    sentinel.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return True
