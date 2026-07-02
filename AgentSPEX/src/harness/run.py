import argparse
import os

from dotenv import find_dotenv, load_dotenv

from harness.agent import AgentSPEX

from .parsing.yaml_parser import YAMLTaskParser


def parse_args():
    parser = argparse.ArgumentParser(description="Run agent")

    parser.add_argument(
        "--mode",
        type=str,
        default="simple",
        help="Valid modes include simple, plan, loop",
    )
    parser.add_argument(
        "--workflow_file", type=str, default=None, help="Path to the workflow file."
    )
    parser.add_argument(
        "--max_tokens_per_step",
        type=int,
        default=None,
        help="Maximum tokens per step. If not specified, uses YAML config or default (100000).",
    )
    parser.add_argument(
        "--max_tool_calls_per_step",
        type=int,
        default=None,
        help="Maximum tool calls per step. If not specified, uses YAML config or default (10).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use. If not specified, uses YAML config or default (gpt-4.1-mini).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="temperature. If not specified, uses YAML config or default (0.2).",
    )
    parser.add_argument(
        "--plan_revision_max_steps",
        type=int,
        default=None,
        help="The max number of steps to revise plan. If not specified, uses YAML config or default (0).",
    )
    parser.add_argument(
        "--mcp_url",
        type=str,
        default="http://localhost:7002/mcp",
        help="Remote MCP server url",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Override output directory (default: outputs/<task_name>).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint.json (skips completed steps).",
    )
    parser.add_argument(
        "--checkpoint_path",
        type=str,
        default=None,
        help="Override checkpoint path (default: <output_dir>/checkpoint.json).",
    )
    parser.add_argument(
        "--trace_path",
        type=str,
        default=None,
        help="Override trace path (default: <output_dir>/trace.jsonl).",
    )
    parser.add_argument(
        "--replay_trace",
        type=str,
        default=None,
        help="Replay tool outputs from a trace.jsonl (no real tool calls).",
    )
    args = parser.parse_args()
    return args


def load_yaml_config(workflow_file: str) -> dict:
    """
    Load config section from YAML file.

    Args:
        workflow_file: Path to the YAML workflow file

    Returns:
        Dictionary with config values from YAML
    """
    parser = YAMLTaskParser()
    yaml_data = parser.load_task(workflow_file)
    return parser.get_config_with_defaults(yaml_data)


def apply_yaml_config_fallback(args, yaml_config: dict):
    """
    Apply YAML config as fallback for unset CLI arguments.

    Args:
        args: Parsed CLI arguments
        yaml_config: Config from YAML file

    This modifies args in-place, setting values from yaml_config
    only if the CLI argument was not provided (is None).
    """
    # Map of args attribute -> yaml config key
    config_mapping = {
        "model": "model",
        "max_tokens_per_step": "max_tokens_per_step",
        "max_tool_calls_per_step": "max_tool_calls_per_step",
        "temperature": "temperature",
        "model_kwargs": "model_kwargs",
        "plan_revision_max_steps": "plan_revision_max_steps",
    }

    for arg_name, config_key in config_mapping.items():
        if getattr(args, arg_name, None) is None:
            setattr(args, arg_name, yaml_config.get(config_key))


def main():
    load_dotenv(find_dotenv(), override=True)
    args = parse_args()

    if args.mode == "loop":
        from harness.agentic_loop.run_loop import main as loop_main

        return loop_main()

    workflow_path = args.workflow_file or ""
    yaml_config = load_yaml_config(workflow_path)

    apply_yaml_config_fallback(args, yaml_config)

    agent = AgentSPEX(mcp_url=args.mcp_url)
    agent.run(args)


if __name__ == "__main__":
    main()
