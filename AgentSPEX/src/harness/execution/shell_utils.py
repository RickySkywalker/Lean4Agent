"""Shell utilities for tool execution.

This module provides the ShellUtilsMixin for handling shell-related
tool calls, including default argument injection and completion detection.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..types.context import ContextKeys, Tokens


class ShellUtilsMixin:
    """Mixin for shell tool argument handling.

    Provides utility methods for handling shell-related tool calls,
    including default argument injection and completion token detection.
    """

    def _inject_shell_defaults(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Inject default cwd and conda_env for shell_run tool calls.

        Automatically adds working directory and conda environment settings
        from context if not explicitly provided in tool arguments.

        Args:
            tool_name: Name of the tool being invoked.
            tool_args: Original arguments for the tool call.
            context: Execution context containing default values.

        Returns:
            Updated tool arguments with defaults injected.
            Returns original args unchanged if not a shell_run call.
        """
        if tool_name != "shell_run" or not context:
            return tool_args

        updated = dict(tool_args or {})

        # Inject code_path as default cwd
        if "cwd" not in updated:
            code_path = context.get(ContextKeys.CODE_PATH)
            if code_path:
                updated["cwd"] = code_path

        # Inject conda_env_name as default conda_env
        if "conda_env" not in updated:
            conda_env = context.get(ContextKeys.CONDA_ENV_NAME)
            if conda_env:
                updated["conda_env"] = conda_env

        return updated

    def _is_submit_command(
        self,
        command_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if command contains the task completion token.

        When ``require_submodule_submit`` is set in *context*, direct
        submission is blocked — the token is only honoured inside a
        submodule (which runs in its own sub-context without this flag).

        Args:
            command_text: The command text to check.
            context: Optional execution context.

        Returns:
            True if the submit completion token is found and is allowed.
        """
        if Tokens.SUBMIT_COMPLETE not in (command_text or ""):
            return False
        # When the flag is set, block direct submit — the agent must
        # use the submit_changes submodule instead.
        if context and context.get(ContextKeys.REQUIRE_SUBMODULE_SUBMIT):
            return False
        return True

    def _is_submodule_submit_result(self, result: Any) -> bool:
        """Check if a submodule result contains the submit completion signal.

        When ``require_submodule_submit`` is enabled, the submit_changes
        submodule is the only way to submit.  Inside its sub-context (which
        does NOT have the flag), it runs ``COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT``
        and that becomes the submodule's return value.  This helper detects
        that signal so the parent loop can propagate it.

        Args:
            result: The value returned by the submodule.

        Returns:
            True if the result signals submission.
        """
        if isinstance(result, str):
            return Tokens.SUBMIT_COMPLETE in result
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, str) and Tokens.SUBMIT_COMPLETE in v:
                    return True
        return False

    def _check_blocked_command(
        self,
        command_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Check if command is blocked and return error message.

        Args:
            command_text: The shell command to check.
            context: Optional execution context.

        Returns:
            Error message if blocked, None otherwise.
        """
        if not command_text:
            return None

        import re

        # Only allow a safe subset of git commands when git filtering is enabled.
        if context and context.get(ContextKeys.ENABLE_GIT_FILTERING):
            _ALLOWED_GIT_SUBCOMMANDS = {"diff", "add", "log", "status", "show"}

            for m in re.finditer(
                r"\bgit\b((?:\s+--?\S+)*)\s+([a-z][\w-]*)", command_text
            ):
                subcmd = m.group(2)
                if subcmd not in _ALLOWED_GIT_SUBCOMMANDS:
                    return (
                        f"git {subcmd} is not allowed. "
                        f"Only these git commands are permitted: {', '.join(sorted(_ALLOWED_GIT_SUBCOMMANDS))}."
                    )

            if re.search(r"\bgit\b.*\blog\b", command_text):
                if re.search(r"--all\b|--branches\b|--remotes\b", command_text):
                    return (
                        "Viewing commits from other branches is not allowed. "
                        "You may only inspect the current branch's recent history "
                        "(e.g. git log --oneline -5)."
                    )

        # Block direct COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT when
        # require_submodule_submit is enabled.
        if (
            context
            and context.get(ContextKeys.REQUIRE_SUBMODULE_SUBMIT)
            and Tokens.SUBMIT_COMPLETE in command_text
        ):
            return (
                "Direct submission is blocked. You MUST use the submit_changes "
                "subagent to submit your work. Example:\n"
                "```submit_changes\n"
                'query: "Brief summary of changes"\n'
                "```"
            )

        return None
