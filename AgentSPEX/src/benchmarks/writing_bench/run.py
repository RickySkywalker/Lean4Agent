"""WritingBench benchmark runner - main entry point.

Evaluates agents on writing tasks across 6 domains with rubric-based scoring.
Based on https://github.com/X-PLUG/WritingBench

"""

import json
import os
import signal
import sys
import traceback
import urllib.request
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import List

from benchmarks.writing_bench.config import WritingResult, parse_args
from benchmarks.writing_bench.evaluate import evaluate
from benchmarks.writing_bench.instance import (collect_instance_artifacts,
                                               prepare_yaml_for_instance,
                                               sandbox_query_dir, save_result)

_DATA_DIR = Path(__file__).parent / "data"
_BENCHMARK_PATH = _DATA_DIR / "benchmark_all.jsonl"

_GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/X-PLUG/WritingBench/main/benchmark_query"
)

_REQUIREMENT_DIR = _DATA_DIR / "requirement"
_REQUIREMENT_FILES = [
    "requirement/style/style_subset.jsonl",
    "requirement/style/style_subset_C.jsonl",
    "requirement/format/format_subset.jsonl",
    "requirement/format/format_subset_C.jsonl",
    "requirement/length/length_subset.jsonl",
    "requirement/length/length_subset_C.jsonl",
]


def _download_file(url: str, dest: Path) -> bool:
    """Download a file from a URL. Returns True on success."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading {dest.name}...")
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  Warning: could not download {dest.name}: {e}")
        return False


def _ensure_data():
    """Download benchmark data from GitHub if not already present."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not _BENCHMARK_PATH.exists():
        print("Downloading WritingBench benchmark data...")
        url = f"{_GITHUB_RAW_BASE}/benchmark_all.jsonl"
        if not _download_file(url, _BENCHMARK_PATH):
            print("ERROR: Could not download benchmark_all.jsonl. Exiting.")
            sys.exit(1)
        print(f"  Saved to {_BENCHMARK_PATH}")

    # Download requirement subset files (optional, for detailed scoring)
    for rel_path in _REQUIREMENT_FILES:
        dest = _DATA_DIR / rel_path
        if not dest.exists():
            url = f"{_GITHUB_RAW_BASE}/{rel_path}"
            _download_file(url, dest)


def _load_queries(query_indices=None, limit=None) -> List[dict]:
    """Load queries from benchmark JSONL."""
    queries = []
    with open(_BENCHMARK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line))

    if query_indices:
        idx_set = set(query_indices)
        queries = [q for q in queries if q["index"] in idx_set]

    if limit and limit < len(queries):
        queries = queries[:limit]

    return queries


_DRAFT_EXTENSIONS = {".md", ".txt", ".tex", ".html"}


def _read_draft_from_file(mcp_client, agent_output: str) -> str | None:
    """Try to read draft content from the file the agent wrote to.

    The file-based workflow returns the output file path (e.g. ``draft.md``)
    as the agent's return value.  We read its content via MCP so the agent
    never has to output the full text itself (which can cause timeouts on
    long documents).

    Returns the file content, or ``None`` if reading failed.
    """
    file_path = agent_output.strip().strip('"').strip("'")

    # Sanity check: must look like a short path with a known extension
    if not file_path or len(file_path) > 200:
        return None

    suffix = PurePosixPath(file_path).suffix.lower()
    if suffix not in _DRAFT_EXTENSIONS:
        return None

    try:
        result = mcp_client.invoke("fs_read", {"path": file_path})
        if isinstance(result, dict) and "text" in result:
            text = result["text"]
            if text and text.strip():
                return text
    except Exception as e:
        print(f"  Warning: could not read draft file '{file_path}': {e}")

    return None


def _run_single_query(
    idx: int,
    total: int,
    query: dict,
    args,
    runs_dir: Path,
    experiment_name: str,
) -> WritingResult:
    """Run the agent on a single writing query.

    Each query gets its own:
    - Host-side directory: ``{runs_dir}/{index}/``
    - Sandbox-side directory: ``outputs/{experiment_name}/query_{index}/``
    - Logger (if ``--save-logs``): ``{index}_full.log``, ``{index}_agent_events.log``
    - Customised YAML with isolated ``output_dir`` parameter
    """
    index = query["index"]
    query_text = query["query"]
    preview = query_text[:80].replace("\n", " ")

    # Per-instance host directory
    instance_dir = runs_dir / str(index)
    instance_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[{idx}/{total}] Query {index}: {preview}...")

    logger = None
    mcp_client = None
    try:
        from harness.agent import AgentSPEX
        from harness.types.config import EffectiveArgs
        from mcp_client.client import MCPClient

        mcp_client = MCPClient()

        # --- Per-instance Logger ---
        save_logs = getattr(args, "save_logs", False)
        quiet = getattr(args, "quiet", False)
        if save_logs:
            from mcp_client.logger import Logger

            host_log_path = instance_dir / f"{index}_full.log"
            host_event_log_path = instance_dir / f"{index}_agent_events.log"
            # Sandbox-side log paths (under the per-query output dir)
            sb_dir = sandbox_query_dir(experiment_name, index)
            sandbox_log_path = f"{sb_dir}/{index}_full.log"
            sandbox_event_log_path = f"{sb_dir}/{index}_agent_events.log"

            logger = Logger(
                mcp_client=mcp_client,
                log_file=sandbox_log_path,
                host_log_path=host_log_path,
                event_log_path=sandbox_event_log_path,
                host_event_log_path=host_event_log_path,
                deduplicate=True,
                to_stdout=not quiet,
            )
            logger(f"Starting query {index}: {preview}")

        # --- Per-instance customised YAML ---
        custom_yaml_file = prepare_yaml_for_instance(
            args.workflow_file, query, instance_dir, experiment_name
        )

        # --- Per-instance EffectiveArgs (avoids mutating shared state) ---
        instance_args = Namespace(
            problem_statement=query_text,
            output_dir=str(instance_dir),
        )
        agent_args = EffectiveArgs(
            workflow_file=custom_yaml_file,
            model=args.model if args.model else "gpt-4.1",
            _original_args=instance_args,
        )

        agent = AgentSPEX(mcp_client=mcp_client)
        agent_output = agent.run(agent_args, external_logger=logger)
        raw_output = (
            agent_output if isinstance(agent_output, str) else str(agent_output or "")
        )

        # File-based workflow: the agent returns the draft file path.
        # Read content via MCP so the LLM never has to output the full text.
        file_content = _read_draft_from_file(mcp_client, raw_output)
        if file_content:
            final_text = file_content
            print(f"  [{index}] Read {len(final_text)} chars from draft file")
        else:
            # Fallback: use the agent's direct output (legacy non-file workflow)
            final_text = raw_output

        # --- Collect artifacts from sandbox to host ---
        collected = collect_instance_artifacts(
            mcp_client, index, instance_dir, experiment_name
        )
        if collected:
            print(f"  [{index}] Collected artifacts: {', '.join(collected)}")

        result = WritingResult(
            index=index,
            query=query_text,
            domain1=query.get("domain1", ""),
            domain2=query.get("domain2", ""),
            lang=query.get("lang", ""),
            status="completed",
            response=final_text,
        )

        save_result(result, instance_dir)
        if logger:
            logger(f"Completed query {index} ({len(final_text)} chars)")
        print(f"  [{index}] Completed ({len(final_text)} chars)")
        return result

    except Exception as e:
        print(f"  [{index}] Error: {e}")
        traceback.print_exc()
        if logger:
            logger(f"Error on query {index}: {e}")
        result = WritingResult(
            index=index,
            query=query_text,
            domain1=query.get("domain1", ""),
            domain2=query.get("domain2", ""),
            lang=query.get("lang", ""),
            status="failed",
            error=str(e),
        )
        save_result(result, instance_dir)
        return result
    finally:
        if mcp_client is not None:
            mcp_client.close()


def _signal_handler(signum, frame):
    """Handle Ctrl+C: force-exit immediately instead of blocking on thread join."""
    print(f"\n\nInterrupted (signal {signum}). Exiting...")
    os._exit(1)


def main():
    args = parse_args()

    # Register signal handlers so Ctrl+C exits immediately
    # instead of blocking on ThreadPoolExecutor.shutdown(wait=True)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Step 1: Ensure data is available
    _ensure_data()

    # Step 2: Load queries
    queries = _load_queries(query_indices=args.query_indices, limit=args.limit)
    print(f"\n{len(queries)} queries to process")

    # Step 3: Run agent on each query
    runs_dir = Path(args.output_dir) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Derive experiment name from --output-dir for cohesive sandbox naming.
    # e.g. "outputs/my_experiment" -> "my_experiment"
    experiment_name = Path(args.output_dir).name

    results: List[WritingResult] = []

    if args.max_parallel > 1:
        print(f"Running with max {args.max_parallel} parallel instances")
        print(f"Sandbox output: outputs/{experiment_name}/query_*/")
        if args.save_logs:
            print(f"Logs: {runs_dir}/<index>/<index>_full.log")
            if args.quiet:
                print(
                    "Terminal output suppressed (--quiet). Use dashboard to view logs."
                )
        with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
            futures = {
                executor.submit(
                    _run_single_query,
                    i + 1,
                    len(queries),
                    q,
                    args,
                    runs_dir,
                    experiment_name,
                ): q
                for i, q in enumerate(queries)
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    q = futures[future]
                    results.append(
                        WritingResult(
                            index=q["index"],
                            query=q["query"],
                            status="failed",
                            error=str(e),
                        )
                    )
    else:
        for i, q in enumerate(queries):
            results.append(
                _run_single_query(
                    i + 1, len(queries), q, args, runs_dir, experiment_name
                )
            )

    # Summary
    completed = sum(1 for r in results if r.status == "completed")
    failed = len(results) - completed
    print(f"\n{'='*60}")
    print(
        f"Completed: {completed}/{len(results)}"
        + (f" ({failed} failed)" if failed else "")
    )
    print(f"Results: {runs_dir}")

    # Step 4: Evaluate
    if not args.skip_eval and completed > 0:
        print(f"\nRunning evaluation with {args.judge_model}...")
        eval_dir = Path(args.output_dir) / "evals"
        evaluate(
            runs_dir=str(runs_dir),
            benchmark_path=str(_BENCHMARK_PATH),
            eval_dir=str(eval_dir),
            judge_model=args.judge_model,
            max_parallel=args.max_parallel_eval,
        )
    elif args.skip_eval:
        print("\nSkipped evaluation (--skip-eval)")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
