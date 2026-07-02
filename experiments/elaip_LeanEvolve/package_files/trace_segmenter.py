#!/usr/bin/env python3
"""
trace_segmenter.py - Split a SWE-agent `agent_events.log` into per-step excerpts.

The event log uses one event per line, delimited by `<<<EVENT>>>{json}<<</EVENT>>>`
tokens. Events belonging to one workflow step are bracketed by `step_start` /
`step_end` events sharing the same `step_id`. This script groups events by
`step_id`, writes a full JSONL excerpt per step, and writes a compact
human-readable Markdown summary per step that subsequent LLM annotation can
load inside a single context window (target <=~6 KB).

Outputs (under --staging_dir):
  trace_index.json              Top-level index; schema described below.
  step_<sid>_excerpt.jsonl      Full event stream for that step (one JSON object per line).
  step_<sid>_summary.md         Compact Markdown summary for LLM consumption.
  workflow_header.json          workflow_start event and final totals.

trace_index.json schema:
{
  "instance_id": "django__django-14140",
  "event_log_path": "...",
  "full_log_path": "...",
  "model": "gpt-5.2",
  "total_events": 261,
  "total_steps": 5,
  "step_ids": ["1","2","3","4","5"],
  "steps": [
    { "step_id": "1",
      "step_name": "explore_repository",
      "step_type": "task",
      "num_events": 60,
      "num_iterations": 8,
      "num_tool_calls": 7,
      "excerpt_path": ".../step_1_excerpt.jsonl",
      "summary_path": ".../step_1_summary.md" },
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

EVENT_RE = re.compile(r"<<<EVENT>>>(.*?)<<</EVENT>>>", re.DOTALL)


def iter_events(event_log_path: Path):
    """Yield parsed event dicts from an agent_events.log, skipping non-event lines."""
    with event_log_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            m = EVENT_RE.search(raw)
            if not m:
                continue
            body = m.group(1).strip()
            try:
                yield json.loads(body)
            except json.JSONDecodeError as e:
                print(f"[trace_segmenter] WARN: failed to parse event: {e}", file=sys.stderr)


def truncate(s: str, limit: int = 300) -> str:
    s = s if s is not None else ""
    if len(s) <= limit:
        return s
    return s[:limit] + f"... [truncated {len(s) - limit} chars]"


def summarize_step(step_id: str,
                   step_name: str,
                   step_type: str,
                   step_start_data: dict,
                   events: list[dict]) -> str:
    """Render a compact Markdown summary for one step."""
    lines: list[str] = []
    lines.append(f"# Step {step_id}: {step_name}")
    lines.append("")
    lines.append(f"- step_type: `{step_type}`")

    problem_statement = ""
    try:
        problem_statement = step_start_data.get("variables", {}).get("problem_statement", "") or ""
    except AttributeError:
        pass
    if problem_statement:
        lines.append("")
        lines.append("## Problem statement (from workflow variables)")
        lines.append("")
        lines.append("```")
        lines.append(truncate(problem_statement, 600))
        lines.append("```")

    iterations: list[dict] = []
    tool_calls: list[dict] = []
    last_llm_response: str | None = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_reasoning_tokens = 0

    for ev in events:
        typ = ev.get("type", "")
        data = ev.get("data", {})
        if typ == "agent_iteration":
            iterations.append(data)
        elif typ == "messages_end":
            usage = data.get("usage") or {}
            total_prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            total_completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            total_reasoning_tokens += int(usage.get("reasoning_tokens", 0) or 0)
        elif typ == "llm_response":
            content = data.get("content") or data.get("text") or data.get("message") or ""
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            if content:
                last_llm_response = str(content)
        elif typ == "tool_call_start":
            tool_calls.append({
                "iteration": data.get("iteration"),
                "call": data.get("call"),
                "name": data.get("name"),
                "args": data.get("args"),
                "result": None,
                "returncode": None,
            })
        elif typ == "tool_call_end":
            if tool_calls:
                for tc in reversed(tool_calls):
                    if (tc["iteration"] == data.get("iteration")
                            and tc["call"] == data.get("call")
                            and tc["result"] is None):
                        tc["result"] = data.get("result")
                        try:
                            parsed = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                            if isinstance(parsed, dict):
                                tc["returncode"] = parsed.get("returncode")
                        except Exception:
                            pass
                        break

    lines.append("")
    lines.append("## Counts")
    lines.append(f"- events: {len(events)}")
    lines.append(f"- LLM iterations: {len(iterations)}")
    lines.append(f"- tool calls: {len(tool_calls)}")
    lines.append(f"- tokens (prompt/completion/reasoning): "
                 f"{total_prompt_tokens}/{total_completion_tokens}/{total_reasoning_tokens}")

    if tool_calls:
        lines.append("")
        lines.append("## Tool calls (chronological)")
        for i, tc in enumerate(tool_calls, 1):
            args_str = tc.get("args")
            if isinstance(args_str, str):
                try:
                    parsed = json.loads(args_str)
                    args_str = parsed.get("text", args_str) if isinstance(parsed, dict) else args_str
                except Exception:
                    pass
            rc = tc.get("returncode")
            rc_str = f"rc={rc}" if rc is not None else "rc=?"
            lines.append(f"- **#{i}** `{tc.get('name')}` [{rc_str}, iter={tc.get('iteration')}]: "
                         f"`{truncate(str(args_str), 220)}`")
            result = tc.get("result")
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        out = parsed.get("output") or parsed.get("stdout") or parsed.get("text") or ""
                        result = out if out else result
                except Exception:
                    pass
            if result:
                lines.append(f"    output: `{truncate(str(result), 300)}`")

    if last_llm_response:
        lines.append("")
        lines.append("## Final LLM response (truncated)")
        lines.append("")
        lines.append("```")
        lines.append(truncate(last_llm_response, 1200))
        lines.append("```")

    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description="Split agent_events.log into per-step excerpts + summaries.")
    p.add_argument("--event_log", required=True, help="Path to <instance>_agent_events.log")
    p.add_argument("--full_log", required=False, default="", help="(optional) path to full.log for cross-reference")
    p.add_argument("--staging_dir", required=True, help="Output directory (will be created)")
    p.add_argument("--instance_id", default="", help="Override instance_id (default: inferred from filename)")
    args = p.parse_args()

    event_log_path = Path(args.event_log).resolve()
    if not event_log_path.exists():
        print(f"ERROR: event log not found: {event_log_path}", file=sys.stderr)
        sys.exit(1)

    staging = Path(args.staging_dir).resolve()
    staging.mkdir(parents=True, exist_ok=True)

    instance_id = args.instance_id
    if not instance_id:
        stem = event_log_path.name
        if stem.endswith("_agent_events.log"):
            instance_id = stem[: -len("_agent_events.log")]
        else:
            instance_id = event_log_path.stem

    workflow_header: dict[str, Any] = {}
    model: str | None = None
    current_step_id: str | None = None
    step_metadata: dict[str, dict[str, Any]] = {}
    step_events: dict[str, list[dict[str, Any]]] = {}
    ordered_step_ids: list[str] = []
    total_events = 0

    # Extras we emit into trace_index.json so layer3_ir_init.py can seed
    # exec_state deterministically (parameters + tools), without an LLM call.
    workflow_parameters: dict[str, str] = {}  # first sighting wins
    observed_tools: list[str] = []
    observed_tools_set: set[str] = set()

    for ev in iter_events(event_log_path):
        total_events += 1
        typ = ev.get("type", "")
        data = ev.get("data", {}) or {}

        if typ == "workflow_start":
            workflow_header["workflow_start"] = ev
            model = data.get("model", model)
            for k, v in (data.get("variables") or {}).items():
                if k not in workflow_parameters and isinstance(v, (str, int, float, bool)):
                    workflow_parameters[k] = str(v)
            continue
        if typ == "workflow_end":
            workflow_header["workflow_end"] = ev
            continue

        if typ == "step_start":
            sid = str(data.get("step_id", ""))
            if not sid:
                continue
            # Harvest workflow-parameter values from the first step's variables.
            for k, v in (data.get("variables") or {}).items():
                if k not in workflow_parameters and isinstance(v, (str, int, float, bool)):
                    workflow_parameters[k] = str(v)
            if sid not in step_events:
                ordered_step_ids.append(sid)
                step_events[sid] = []
            step_metadata[sid] = {
                "step_id": sid,
                "step_name": data.get("name", ""),
                "step_type": data.get("step_type", ""),
                "step_start_data": data,
            }
            current_step_id = sid
            step_events[sid].append(ev)
            continue

        if typ == "tool_call_start":
            tname = data.get("name", "")
            if tname and tname not in observed_tools_set:
                observed_tools_set.add(tname)
                observed_tools.append(tname)

        if typ == "step_end":
            sid = str(data.get("step_id", ""))
            if sid and sid in step_events:
                step_events[sid].append(ev)
                if current_step_id == sid:
                    current_step_id = None
            continue

        sid = str(data.get("step_id", "")) if isinstance(data, dict) else ""
        if sid and sid in step_events:
            step_events[sid].append(ev)
        elif current_step_id is not None:
            step_events[current_step_id].append(ev)

    steps_out: list[dict[str, Any]] = []
    for sid in ordered_step_ids:
        meta = step_metadata.get(sid, {"step_id": sid, "step_name": "", "step_type": "", "step_start_data": {}})
        evs = step_events.get(sid, [])
        num_iter = sum(1 for e in evs if e.get("type") == "agent_iteration")
        num_tc = sum(1 for e in evs if e.get("type") == "tool_call_start")

        excerpt_path = staging / f"step_{sid}_excerpt.jsonl"
        with excerpt_path.open("w", encoding="utf-8") as f:
            for ev in evs:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        summary_md = summarize_step(sid, meta["step_name"], meta["step_type"],
                                    meta.get("step_start_data", {}), evs)
        summary_path = staging / f"step_{sid}_summary.md"
        summary_path.write_text(summary_md, encoding="utf-8")

        steps_out.append({
            "step_id": sid,
            "step_name": meta["step_name"],
            "step_type": meta["step_type"],
            "num_events": len(evs),
            "num_iterations": num_iter,
            "num_tool_calls": num_tc,
            "excerpt_path": str(excerpt_path),
            "summary_path": str(summary_path),
        })

    # Light normalisation for the params we emit so they don't explode the IR
    # when serialised (problem_statement can be several KB).
    def _clip(s: str, n: int = 200) -> str:
        s = s if isinstance(s, str) else str(s)
        return s if len(s) <= n else s[:n] + "…"

    clipped_params = {k: _clip(v, 200) for k, v in workflow_parameters.items()}

    index = {
        "instance_id": instance_id,
        "event_log_path": str(event_log_path),
        "full_log_path": str(Path(args.full_log).resolve()) if args.full_log else "",
        "model": model or "",
        "total_events": total_events,
        "total_steps": len(ordered_step_ids),
        "step_ids": ordered_step_ids,
        "steps": steps_out,
        "workflow_parameters": clipped_params,
        "observed_tools": observed_tools,
    }
    (staging / "trace_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (staging / "workflow_header.json").write_text(
        json.dumps(workflow_header, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"OK: segmented {total_events} events into {len(ordered_step_ids)} step(s) -> {staging}")


if __name__ == "__main__":
    main()
