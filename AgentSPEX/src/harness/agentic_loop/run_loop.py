"""CLI entry point for the AgentSPEX Agentic Loop."""

import argparse
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from harness.llms.client import LLMClient
from mcp_client.client import MCPClient
from mcp_client.logger import Logger

from .loop import AgenticLoop
from .session import LoopConfig


def parse_args():
    parser = argparse.ArgumentParser(description="AgentSPEX Agentic Loop")
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Task description. If not provided, enters interactive REPL mode.",
    )
    parser.add_argument("--model", type=str, default="claude-opus-4-5")
    parser.add_argument("--mcp_url", type=str, default=None)
    parser.add_argument("--output_dir", type=str, default=None)
    parser.add_argument("--max_turns", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument(
        "--plan_generator_model",
        type=str,
        default="gpt-5",
        help="Model for YAML plan generation (default: gpt-5)",
    )
    parser.add_argument(
        "--plan_executor_model",
        type=str,
        default="claude-sonnet-4-6",
        help="Model for executing generated YAML plans (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--plan_mode",
        action="store_true",
        default=False,
        help="Enable plan mode: decompose task into subtasks, generate YAML plans",
    )
    return parser.parse_args()


def run_loop(
    model: str = "claude-sonnet-4-5",
    mcp_url: str = "http://localhost:7002/mcp",
    output_dir: str = "outputs/agentic_loop",
    temperature: float = 0.2,
) -> None:
    """Start the interactive agentic loop against a running sandbox VM."""
    load_dotenv(find_dotenv(), override=True)
    os.makedirs(output_dir, exist_ok=True)

    config = LoopConfig(
        model=model,
        mcp_url=mcp_url,
        temperature=temperature,
        output_dir=output_dir,
    )

    mcp_client = MCPClient(url=config.mcp_url)
    llm_client = LLMClient()

    host_out = Path(output_dir)
    logger = Logger(
        mcp_client,
        log_file="/workspace/agent_run.log",
        to_stdout=True,
        host_log_path=host_out / "agent_run.log",
        event_log_path="/workspace/agent_events.log",
        host_event_log_path=host_out / "agent_events.log",
    )

    loop = AgenticLoop(mcp_client, llm_client, config, logger)
    try:
        loop.run_interactive()
    finally:
        mcp_client.close()


def main():
    load_dotenv(find_dotenv(), override=True)
    args = parse_args()

    output_dir = args.output_dir or "outputs/agentic_loop"
    os.makedirs(output_dir, exist_ok=True)

    # Build MCP URL from env or args
    mcp_url = args.mcp_url
    if not mcp_url:
        hostname = os.getenv("MCP_HOSTNAME", "localhost")
        port = os.getenv("MCP_PORT", "7002")
        basepath = os.getenv("MCP_BASEPATH", "/mcp")
        mcp_url = f"http://{hostname}:{port}{basepath}"

    config = LoopConfig(
        model=args.model,
        mcp_url=mcp_url,
        max_turns=args.max_turns,
        temperature=args.temperature,
        output_dir=output_dir,
        plan_generator_model=args.plan_generator_model,
        plan_executor_model=args.plan_executor_model,
    )

    mcp_client = MCPClient(url=config.mcp_url)
    llm_client = LLMClient()

    # Set up logger with host-side paths for direct file I/O
    log_file = "/workspace/agent_run.log"  # VM path (for MCP fs_write)
    host_log_path = Path(output_dir) / "agent_run.log"
    host_event_log_path = Path(output_dir) / "agent_events.log"

    logger = Logger(
        mcp_client,
        log_file=log_file,
        to_stdout=True,
        host_log_path=host_log_path,
        event_log_path="/workspace/agent_events.log",
        host_event_log_path=host_event_log_path,
    )

    loop = AgenticLoop(mcp_client, llm_client, config, logger)

    try:
        if args.task:
            result = loop.run(args.task, plan_mode=args.plan_mode)
            print(result)
        else:
            loop.run_interactive()
    finally:
        mcp_client.close()


if __name__ == "__main__":
    main()
