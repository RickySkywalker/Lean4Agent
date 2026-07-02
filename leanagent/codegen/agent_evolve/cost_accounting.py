#!/usr/bin/env python3
"""Self-guided-evolve cost accounting.

Reads every `*_agent_events.log` under one or more roots, finds each log's
final `workflow_end` event, and tallies prompt_tokens + completion_tokens.

Pricing (USD per 1M tokens, fixed for this experiment):
    input  : $0.50
    output : $2.50

Usage:
    python cost_accounting.py [<root> ...]
        --price-input  0.50  (default)
        --price-output 2.50  (default)

If no roots are given, defaults to:
    workspace/lean_evolve/kimi-k2.5/
    workspace_persistent/outputs/llm_evolve/kimi-k2.5/

Prints a per-instance breakdown and a grand total. Exits non-zero if total
cost exceeds the budget (50 USD by default; pass --budget-usd to override).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_workflow_end(log_path: Path) -> dict | None:
    """Return the parsed `data` of the LAST workflow_end event in the log,
    or None if absent."""
    last: dict | None = None
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"workflow_end"' not in line:
                    continue
                start = line.find("<<<EVENT>>>")
                end = line.find("<<</EVENT>>>")
                if start < 0 or end < 0:
                    continue
                try:
                    ev = json.loads(line[start + len("<<<EVENT>>>"):end])
                except Exception:
                    continue
                if ev.get("type") == "workflow_end":
                    last = ev.get("data") or {}
    except FileNotFoundError:
        return None
    return last


def collect(roots: list[Path]) -> list[dict]:
    rows: list[dict] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        # Match both `<inst>_agent_events.log` (Stage C convention) and
        # `agent_events.log` (Stage A/B convention nested under
        # `<root>/stage_<x>/runtime/<inst>/`).
        candidates = list(root.rglob("*_agent_events.log"))
        candidates += list(root.rglob("agent_events.log"))
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            data = parse_workflow_end(p)
            if not data:
                rows.append({
                    "log": str(p),
                    "instance": _infer_instance(p),
                    "stage": _stage_label(p),
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "synthetic_timeout": True,
                    "missing_workflow_end": True,
                })
                continue
            rows.append({
                "log": str(p),
                "instance": _infer_instance(p),
                "stage": _stage_label(p),
                "prompt_tokens": int(data.get("prompt_tokens") or 0),
                "completion_tokens": int(data.get("completion_tokens") or 0),
                "reasoning_tokens": int(data.get("reasoning_tokens") or 0),
                "synthetic_timeout": bool(data.get("synthetic_timeout")),
                "missing_workflow_end": False,
            })
    return rows


def _stage_label(p: Path) -> str:
    # Best-effort labeling so the per-instance summary tells you which stage
    # each charge came from.
    s = str(p)
    if "/stage_a/" in s or "/stage_a_results" in s:
        return "stage_a"
    if "/stage_b/" in s or "/stage_b_evolved" in s:
        return "stage_b"
    if "/stage_c_rerun" in s:
        return "stage_c"
    return "?"


def _infer_instance(p: Path) -> str:
    name = p.name
    if name.endswith("_agent_events.log"):
        return name[: -len("_agent_events.log")]
    # Stage A/B: agent_events.log under .../<inst>/agent_events.log
    return p.parent.name


def cost_usd(prompt: int, completion: int, p_in: float, p_out: float) -> float:
    return prompt * p_in / 1_000_000 + completion * p_out / 1_000_000


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("roots", nargs="*", type=Path, default=None,
                   help="Directories to scan for *_agent_events.log")
    p.add_argument("--price-input", type=float, default=0.50,
                   help="USD per 1M input (prompt) tokens. Default 0.50.")
    p.add_argument("--price-output", type=float, default=2.50,
                   help="USD per 1M output (completion) tokens. Default 2.50.")
    p.add_argument("--budget-usd", type=float, default=80.0,
                   help="Hard ceiling. Exit code 2 if total exceeds.")
    p.add_argument("--instance", default="",
                   help="Filter to one instance (matches *_agent_events.log basename prefix).")
    p.add_argument("--json", action="store_true",
                   help="Emit a JSON object instead of human-readable.")
    args = p.parse_args()

    default_roots = [
        Path("workspace/lean_evolve/kimi-k2.5"),
        Path("workspace_persistent/outputs/llm_evolve/kimi-k2.5"),
    ]
    roots = args.roots if args.roots else default_roots

    rows = collect(roots)
    if args.instance:
        rows = [r for r in rows if r["instance"].startswith(args.instance)]
    rows.sort(key=lambda r: (r["stage"], r["instance"], r["log"]))

    total_p, total_c = 0, 0
    per_instance: dict[str, dict[str, int]] = {}
    for r in rows:
        total_p += r["prompt_tokens"]
        total_c += r["completion_tokens"]
        key = r["instance"]
        agg = per_instance.setdefault(key, {"prompt": 0, "completion": 0, "logs": 0})
        agg["prompt"] += r["prompt_tokens"]
        agg["completion"] += r["completion_tokens"]
        agg["logs"] += 1

    total_cost = cost_usd(total_p, total_c, args.price_input, args.price_output)

    if args.json:
        print(json.dumps({
            "total_prompt_tokens": total_p,
            "total_completion_tokens": total_c,
            "total_cost_usd": round(total_cost, 4),
            "budget_usd": args.budget_usd,
            "remaining_usd": round(args.budget_usd - total_cost, 4),
            "logs_scanned": len(rows),
            "per_instance": per_instance,
        }, indent=2))
    else:
        print(f"Scanned {len(rows)} *_agent_events.log files under {len(roots)} root(s).")
        print(f"  prices: ${args.price_input}/M input  ${args.price_output}/M output")
        print()
        print(f"{'instance':<46} {'logs':>5} {'prompt_tok':>12} {'compl_tok':>11} {'usd':>8}")
        print("-" * 90)
        for inst in sorted(per_instance):
            agg = per_instance[inst]
            c = cost_usd(agg["prompt"], agg["completion"],
                         args.price_input, args.price_output)
            print(f"{inst[:46]:<46} {agg['logs']:>5} "
                  f"{agg['prompt']:>12,} {agg['completion']:>11,} {c:>8.3f}")
        print("-" * 90)
        print(f"{'TOTAL':<46} {len(rows):>5} "
              f"{total_p:>12,} {total_c:>11,} {total_cost:>8.3f} USD")
        print(f"Budget: ${args.budget_usd:.2f}  Remaining: "
              f"${args.budget_usd - total_cost:.2f}")
        if total_cost > args.budget_usd:
            print("OVER BUDGET", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
