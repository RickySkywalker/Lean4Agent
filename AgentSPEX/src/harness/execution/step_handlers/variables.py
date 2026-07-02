"""Variable manipulation step handlers.

This module provides steps for working with context variables:
- set_variable: Assign a value to a context variable
- increment: Increment a numeric variable
- return: Return a value from a workflow/submodule
- input: Collect interactive user input
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ...parsing.templates import expand_template_variables

if TYPE_CHECKING:
    from mcp_client.logger import Logger

    from ...types.config import EffectiveArgs


class VariableStepsMixin:
    """Mixin providing variable manipulation steps.

    These steps allow workflows to manage state by setting, incrementing,
    and returning context variables, as well as collecting user input.
    """

    def execute_increment_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[str, int]:
        """Increment an integer variable in context.

        Args:
            step_data: Contains 'increment' key with the variable name.
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments (unused).
            logger: Logger instance for output.

        Returns:
            Tuple of (status_message, 0) - no tokens used.
        """
        var_name = step_data.get("increment")
        if not isinstance(var_name, str):
            return "", 0
        try:
            current = int(context.get(var_name, 0))
        except Exception:
            current = 0
        context[var_name] = current + 1
        logger(f"Incremented '{var_name}' to {context[var_name]}")
        return f"{var_name}={context[var_name]}", 0

    def execute_set_variable_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[str, int]:
        """Set a context variable from a value or expression.

        Args:
            step_data: Contains 'set_variable' key with:
                - name: Variable name to set
                - value: Optional value (defaults to prev_output)
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments (unused).
            logger: Logger instance for output.

        Returns:
            Tuple of (status_message, 0) - no tokens used.
        """
        set_var = step_data["set_variable"]
        var_name = set_var["name"]
        source = set_var.get("value", context.get("prev_output", ""))

        # Expand templates in the source value
        value = expand_template_variables(str(source), context)
        try:
            val = eval(value)
        except Exception:
            val = value
            logger.log_event(
                logger,
                "warning",
                {
                    "step_id": str(step_number),
                    "message": f"set_variable: {str(var_name)} = {str(value)}",
                },
            )
        context[var_name] = val

        logger(f"Set context variable: {var_name} = {value}")
        logger.log_event(
            logger,
            "info",
            {
                "step_id": str(step_number),
                "message": f"Set {var_name} = {value}",
            },
        )
        return f"Set {var_name} in context", 0

    def execute_return_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[Any, int]:
        """Return a variable's value directly without wrapper text.

        Designed for submodules to return values to parent workflows.
        Unlike set_variable which outputs a status message, this step
        outputs the actual variable value.

        Args:
            step_data: Contains 'return' key with variable name
                (defaults to 'prev_output' if not specified).
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments (unused).
            logger: Logger instance for output.

        Returns:
            Tuple of (variable_value, 0) - no tokens used.

        Example YAML:
            - return: result_data      # Returns value of result_data
            - return: prev_output      # Returns prev_output
            - return:                  # Defaults to prev_output
        """
        var_name = step_data.get("return", "prev_output")

        # Handle empty/None case
        if not var_name:
            var_name = "prev_output"

        # Expand template variables in var_name
        expanded_var_name = expand_template_variables(str(var_name), context)

        logger(
            f"\n==== Executing return step {step_number}: returning {expanded_var_name} ===="
        )

        # Try to get the value from context, otherwise use the input value itself
        if expanded_var_name in context:
            value = context[expanded_var_name]
            logger(f"Found '{expanded_var_name}' in context")
        else:
            value = expanded_var_name
            logger(f"'{expanded_var_name}' not in context, returning as literal value")

        output = value

        logger(
            f"Return value: {str(output)[:200]}{'...' if len(str(output)) > 200 else ''}"
        )

        # Return the actual value without any wrapper text
        return output, 0

    def execute_input_step(
        self,
        step_data: Dict[str, Any],
        context: Dict[str, Any],
        step_number: int,
        args: EffectiveArgs,
        logger: Logger,
    ) -> Tuple[str, int]:
        """Execute interactive input step to collect user input.

        Prompts the user for input and saves the response to a context variable.
        Supports both interactive terminal mode and non-interactive environments
        (where it uses the default value).

        Args:
            step_data: Contains 'input' key with:
                - prompt: Text to display to the user
                - save_as: Variable name to save input (default: 'user_input')
                - default: Default value if input is empty
            context: Current workflow context dictionary.
            step_number: Identifier for this step.
            args: Effective arguments (unused).
            logger: Logger instance for output.

        Returns:
            Tuple of (user_input, 0) - no tokens used.

        Note:
            In non-interactive environments (tests, CI, pipes), automatically
            uses the default value unless CS_FORCE_INTERACTIVE_INPUT is set.
        """
        input_config = step_data["input"]

        # Expand template variables in prompt
        prompt = expand_template_variables(
            input_config.get("prompt", "Enter input:"), context
        )
        save_as = input_config.get("save_as", "user_input")
        default = input_config.get("default", "")

        is_pretty = bool(getattr(logger, "pretty", False))

        def _read_from_tty(prompt_text: str) -> Optional[str]:
            """
            Try reading a single line from the controlling terminal (/dev/tty).

            Some launchers (e.g. UI-run subprocesses) may give the agent a non-interactive
            stdin, but a controlling TTY still exists. In that case, /dev/tty input lets
            the user type responses as expected.
            """
            try:
                if sys.stdin is not None and sys.stdin.isatty():
                    return None
            except Exception:
                # If the isatty check fails, still try /dev/tty.
                pass

            try:
                with open(
                    "/dev/tty", "r", encoding="utf-8", errors="replace"
                ) as tty_in:
                    if prompt_text:
                        sys.stdout.write(prompt_text)
                        sys.stdout.flush()
                    line = tty_in.readline()
                    if line == "":
                        return ""
                    return line.strip()
            except Exception:
                return None

        def _read_from_ui_channel() -> Optional[str]:
            """
            If running under yaml-flow-editor (or another UI launcher), wait for a UI-supplied answer.

            Protocol (filesystem-based):
            - CS_UI_RUN_ID: stable run identifier
            - CS_UI_INPUT_DIR: directory path writable by the agent process
            - Agent writes: <CS_UI_INPUT_DIR>/request_<step_id>.json
            - UI writes:    <CS_UI_INPUT_DIR>/response_<step_id>.txt
            """
            try:
                if sys.stdin is not None and sys.stdin.isatty():
                    return None
            except Exception:
                pass

            run_id = os.environ.get("CS_UI_RUN_ID") or ""
            input_dir = os.environ.get("CS_UI_INPUT_DIR") or ""
            if not run_id or not input_dir:
                return None

            step_id = str(step_number)
            base = Path(input_dir)
            try:
                base.mkdir(parents=True, exist_ok=True)
            except Exception:
                return None

            request_path = base / f"request_{step_id}.json"
            response_path = base / f"response_{step_id}.txt"

            payload = {
                "run_id": run_id,
                "step_id": step_id,
                "prompt": prompt,
                "default": default,
                "save_as": save_as,
            }
            try:
                request_path.write_text(
                    json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            except Exception:
                return None

            # Emit a sentinel line so the UI log stream can detect and open an input modal.
            try:
                sys.stdout.write(
                    f"\n[ui-input-request]{json.dumps(payload, ensure_ascii=False)}\n"
                )
                sys.stdout.flush()
            except Exception:
                pass

            # Wait (poll) for UI response. Default: 24h hard limit to avoid infinite hangs.
            deadline_s = float(os.environ.get("CS_UI_INPUT_TIMEOUT_S") or 86400)
            start = time.time()
            while True:
                try:
                    if response_path.exists():
                        return response_path.read_text(
                            encoding="utf-8", errors="replace"
                        ).strip()
                except Exception:
                    # Ignore transient fs errors and keep waiting
                    pass

                if time.time() - start > deadline_s:
                    return ""
                time.sleep(0.2)

        # In pretty mode: render as an event panel and use rich console input.
        if is_pretty:
            answer: str = ""
            # Avoid blocking in non-interactive environments (tests/CI/redirects).
            try:
                if (not sys.stdin.isatty()) and (
                    not os.environ.get("CS_FORCE_INTERACTIVE_INPUT")
                ):
                    ui_answer = _read_from_ui_channel()
                    if ui_answer is not None:
                        answer = ui_answer
            except Exception:
                pass

            # If we already got an answer from the UI channel, don't prompt again.
            if answer != "":
                # continue to default handling below
                pass
            else:
                try:
                    # If stdin is redirected, try /dev/tty before falling back to default
                    if (not sys.stdin.isatty()) and (
                        not os.environ.get("CS_FORCE_INTERACTIVE_INPUT")
                    ):
                        tty_answer = _read_from_tty("Your answer: ")
                        if tty_answer is None:
                            answer = default or ""
                            logger.log_event(
                                logger,
                                "warning",
                                {
                                    "step_id": str(step_number),
                                    "message": "Non-interactive stdin detected; /dev/tty unavailable; auto-using default for input step.",
                                },
                            )
                            context[save_as] = answer
                            logger.log_event(
                                logger,
                                "info",
                                {
                                    "step_id": str(step_number),
                                    "message": f"Input saved: {save_as} = {answer}",
                                },
                            )
                            return answer, 0
                        answer = tty_answer
                except Exception:
                    pass

            if answer == "":
                logger.log_event(
                    logger,
                    "input_request",
                    {
                        "step_id": str(step_number),
                        "prompt": prompt,
                        "default": default,
                        "save_as": save_as,
                    },
                )
                console = getattr(logger, "_console", None)
                try:
                    if console is not None and hasattr(console, "input"):
                        answer = console.input("Your answer: ").strip()
                    else:
                        tty_answer = _read_from_tty("Your answer: ")
                        answer = (
                            tty_answer if tty_answer is not None else input().strip()
                        )
                except (EOFError, KeyboardInterrupt):
                    answer = ""
        else:
            logger(f"\n==== Input step {step_number}: collecting user input ====")
            logger(f"Prompt: {prompt}")

            # Display prompt and collect input
            print("\n" + "=" * 70)
            print("USER INPUT REQUESTED")
            print("=" * 70)
            print(f"\n{prompt}")
            if default:
                print(f"(Press Enter for default: {default})")
            print()

            try:
                sys.stdout.write("Your answer: ")
                sys.stdout.flush()
                tty_answer = _read_from_tty("")
                answer = tty_answer if tty_answer is not None else input().strip()
            except (EOFError, KeyboardInterrupt):
                print("\nInput interrupted. Using default.")
                answer = ""

        # Use default if empty
        if not answer:
            answer = default
            if default and not is_pretty:
                print(f"Using default: {default}")
        if not is_pretty:
            print("=" * 70 + "\n")

        # Save to context
        context[save_as] = answer
        logger(f"Saved input to context variable: {save_as} = {answer}")
        if is_pretty:
            logger.log_event(
                logger,
                "info",
                {
                    "step_id": str(step_number),
                    "message": f"Input saved: {save_as} = {answer}",
                },
            )

        return answer, 0  # No tokens used
