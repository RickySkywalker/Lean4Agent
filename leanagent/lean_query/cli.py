"""CLI entry point for the Lean verification query tool."""

import argparse
import sys
import json

from lean_query.config import VerifierConfig
from lean_query.runner import run_lean_query


def main():
    parser = argparse.ArgumentParser(
        description="Query the Lean formal verifier for structured JSON results.",
        prog="lean_query",
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to YAML config file",
    )
    parser.add_argument(
        "--lean-project",
        help="Path to Verifier/ directory (overrides config)",
    )
    parser.add_argument(
        "--target",
        help="Target .lean file path relative to lean-project (overrides config)",
    )
    parser.add_argument(
        "--layer",
        type=int, choices=[1, 2, 3],
        help="Verification layer to run (overrides config)",
    )
    parser.add_argument(
        "--channel",
        choices=["process", "runtime"], default=None,
        help="layer-3 sub-channel: 'process' (per-step beta, default) or 'runtime' "
             "(per-turn gamma — the RuntimePredicates fine-grained tool-call verdicts)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file (stdout if not specified)",
    )
    parser.add_argument(
        "--timeout",
        type=int, default=300,
        help="Timeout in seconds for Lean execution (default: 300)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON (no indentation)",
    )
    # Per-field overrides
    parser.add_argument("--workflow-graph", help="Override workflow_graph name")
    parser.add_argument("--semantic-graph", help="Override semantic_graph name")
    parser.add_argument("--goal-spec", help="Override goal_spec name")
    parser.add_argument("--dynamic-graph", help="Override dynamic_graph name")
    parser.add_argument("--step-id-map", help="Override step_id_map name")
    parser.add_argument("--llm-injections", help="Override llm_injections name")
    parser.add_argument("--exec-state", help="Override exec_state name")
    parser.add_argument("--runtime-facts", help="Override runtimeFacts def name (runtime channel, legacy digested form)")
    parser.add_argument("--runtime-inputs", help="Override runtimeInputs def name (runtime channel, zero-axiom raw form)")

    args = parser.parse_args()

    # Build config
    if args.config:
        config = VerifierConfig.from_yaml(args.config)
    elif args.lean_project and args.target and args.layer:
        config = VerifierConfig(
            lean_project_path=args.lean_project,
            target_file=args.target,
            layer=args.layer,
        )
    else:
        parser.error("Either --config or (--lean-project, --target, --layer) required")

    # Apply CLI overrides
    if args.lean_project:
        config.lean_project_path = args.lean_project
    if args.target:
        config.target_file = args.target
    if args.layer:
        config.layer = args.layer
    if args.channel:
        config.channel = args.channel
    if args.runtime_facts:
        config.runtime_facts = args.runtime_facts
    if args.runtime_inputs:
        config.runtime_inputs = args.runtime_inputs
    if args.output:
        config.output_file = args.output
    if args.timeout:
        config.timeout_seconds = args.timeout
    if args.compact:
        config.pretty_print = False
    if args.workflow_graph:
        config.workflow_graph = args.workflow_graph
    if args.semantic_graph:
        config.semantic_graph = args.semantic_graph
    if args.goal_spec:
        config.goal_spec = args.goal_spec
    if args.dynamic_graph:
        config.dynamic_graph = args.dynamic_graph
    if args.step_id_map:
        config.step_id_map = args.step_id_map
    if args.llm_injections:
        config.llm_injections = args.llm_injections
    if args.exec_state:
        config.exec_state = args.exec_state

    # Run
    result = run_lean_query(config)

    # Output
    output_json = result.to_json(config.pretty_print)
    if config.output_file:
        print(f"Results written to {config.output_file}")
    else:
        print(output_json)

    # Exit code
    sys.exit(0 if not result.errors else 1)


if __name__ == "__main__":
    main()
