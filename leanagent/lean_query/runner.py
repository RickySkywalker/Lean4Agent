"""Execute Lean verification queries and parse results."""

import itertools
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from lean_query.config import ConfigError, VerifierConfig
from lean_query.discovery import file_to_module, resolve_config
from lean_query.driver_gen import generate_driver
from lean_query.schema import VerificationOutput, parse_lean_json

# UNIQUE driver name per invocation. The old fixed "_lean_query_driver.lean" RACED when two
# lean_query processes ran concurrently in the same Verifier dir (8-worker annotation batch / a
# concurrent round-trip): process B overwrote A's driver, so A's `lake env lean --run` executed B's
# driver and returned B's graph's verdict (audit-confirmed cross-contamination: a sympy query
# returned a failed_workflow_2 graph). pid+counter makes each concurrent driver distinct.
_DRIVER_COUNTER = itertools.count()


def _driver_filename() -> str:
    return f"_lean_query_driver_{os.getpid()}_{next(_DRIVER_COUNTER)}.lean"


def run_lean_query(config: VerifierConfig) -> VerificationOutput:
    """Orchestrate the full verification query cycle.

    1. Validate config
    2. Discover definitions in target Lean file
    3. Build the target module's .olean so the generated driver can import it
    4. Generate temp Lean driver
    5. Execute via lake env lean --run
    6. Parse JSON output
    7. Clean up

    Args:
        config: Verified configuration.

    Returns:
        VerificationOutput with structured results or errors.
    """
    config.validate()

    project = Path(config.lean_project_path)
    target_path = project / config.target_file

    # Discover and resolve definitions
    try:
        resolved = resolve_config(str(target_path), config)
    except ConfigError as e:
        return VerificationOutput(
            layer=config.layer, graph_name="",
            theorem_results={}, per_node_results=[],
            graph_level_results={}, errors=[str(e)],
        )

    # Generate driver
    module_path = file_to_module(config.target_file)

    # Ensure the target module's .olean exists before the driver tries to
    # `import` it. `lake env lean --run <driver>` does NOT invoke the build
    # system — it just compiles the driver on the fly against whatever
    # .oleans happen to be on disk. For freshly-authored targets, the
    # .olean may not exist yet; we must build it explicitly. Already-built
    # targets get a near-instant cache hit.
    build_rc, _, build_stderr = _build_module(
        str(project), module_path, config.timeout_seconds, config.env,
    )
    if build_rc != 0:
        error_msg = _parse_lean_error(build_stderr) or build_stderr.strip()
        return VerificationOutput(
            layer=config.layer, graph_name=resolved.get("workflow_graph", ""),
            theorem_results={}, per_node_results=[],
            graph_level_results={},
            errors=[f"lake build {module_path} failed (exit code {build_rc}): {error_msg}"],
        )

    driver_content = generate_driver(module_path, resolved, config.layer)

    driver_filename = _driver_filename()
    driver_path = project / driver_filename
    driver_path.write_text(driver_content)

    try:
        returncode, stdout, stderr = _execute_lean(
            str(project), driver_filename,
            config.timeout_seconds, config.env,
        )

        if returncode != 0:
            error_msg = _parse_lean_error(stderr)
            return VerificationOutput(
                layer=config.layer, graph_name=resolved.get("workflow_graph", ""),
                theorem_results={}, per_node_results=[],
                graph_level_results={},
                errors=[f"Lean compilation failed (exit code {returncode}): {error_msg}"],
            )

        # Parse JSON from stdout
        # Lean may print info/warning messages before the JSON on stderr,
        # but the driver only prints JSON to stdout
        json_output = stdout.strip()
        if not json_output:
            return VerificationOutput(
                layer=config.layer, graph_name=resolved.get("workflow_graph", ""),
                theorem_results={}, per_node_results=[],
                graph_level_results={},
                errors=["Lean produced no output on stdout"],
            )

        result = parse_lean_json(json_output)

        # Write output if requested
        if config.output_file:
            Path(config.output_file).write_text(result.to_json(config.pretty_print))

        return result

    finally:
        if driver_path.exists():
            driver_path.unlink()


def _execute_lean(
    lean_project_path: str,
    driver_filename: str,
    timeout: int,
    env: dict,
) -> tuple[int, str, str]:
    """Run: cd lean_project_path && lake env lean --run driver_filename"""
    import os
    run_env = os.environ.copy()
    run_env.update(env)

    try:
        result = subprocess.run(
            ["lake", "env", "lean", "--run", driver_filename],
            cwd=lean_project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Lean execution timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", "lake command not found. Ensure Lean/Lake is installed and in PATH."


def _build_module(
    lean_project_path: str,
    module_path: str,
    timeout: int,
    env: dict,
) -> tuple[int, str, str]:
    """Run: cd lean_project_path && lake build <module_path>

    Produces the .olean for <module_path> so a subsequent `lake env lean --run`
    driver can `import` it. Already-built modules are a cache hit and return
    almost immediately.
    """
    import os
    run_env = os.environ.copy()
    run_env.update(env)

    try:
        result = subprocess.run(
            ["lake", "build", module_path],
            cwd=lean_project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"lake build {module_path} timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", "lake command not found. Ensure Lean/Lake is installed and in PATH."


def _parse_lean_error(stderr: str) -> str:
    """Extract the most relevant error message from Lean stderr."""
    lines = stderr.strip().split("\n")
    error_lines = [l for l in lines if "error:" in l.lower()]
    if error_lines:
        return error_lines[0].strip()
    if lines:
        return lines[-1].strip()
    return "Unknown error"
