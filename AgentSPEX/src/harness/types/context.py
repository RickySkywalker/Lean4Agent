"""Context keys and special tokens.

This module defines standardized keys and tokens used throughout the agent
framework to ensure consistency and avoid magic strings in the codebase.
"""

from typing import Final


class ContextKeys:
    """Standard keys used in workflow context dictionaries.

    These constants provide type-safe access to context dictionary entries,
    preventing typos and enabling IDE autocompletion.

    Example:
        context[ContextKeys.PREV_OUTPUT] = result
        if context.get(ContextKeys.STOP_ON_RETURN):
            return
    """

    # Task identification
    TASK_NAME: Final[str] = "task_name"
    TASK_OUTPUT_DIR: Final[str] = "task_output_dir"
    GOAL: Final[str] = "goal"

    # Workflow paths
    WORKFLOW_FILE: Final[str] = "workflow_file"
    WORKFLOW_DIR: Final[str] = "workflow_dir"
    WORKFLOW_ROOT: Final[str] = "workflow_root"

    # Execution state
    PREV_OUTPUT: Final[str] = "prev_output"
    CONVERSATION_HISTORY: Final[str] = "conversation_history"

    # Submodule configuration
    SUBMODULE_TOOLS: Final[str] = "submodule_tools"
    SUBMODULE_REGISTRY: Final[str] = "submodule_registry"
    ENABLED_SUBMODULES: Final[str] = "enabled_submodules"
    EXPOSE_SUBMODULES_AS_TOOLS: Final[str] = "expose_submodules_as_tools"

    # Tool configuration
    ENABLED_TOOLS: Final[str] = "enabled_tools"

    # Prompt configuration
    SYSTEM_PROMPT: Final[str] = "system_prompt"

    # Environment configuration
    CODE_PATH: Final[str] = "code_path"
    CONDA_ENV_NAME: Final[str] = "conda_env_name"

    # Flow control
    STOP_ON_RETURN: Final[str] = "stop_on_return"
    STOP_ON_SUBMODULE_RESULT: Final[str] = "stop_on_submodule_result"
    MAX_WORKFLOW_STEPS: Final[str] = "max_workflow_steps"
    REQUIRE_SUBMODULE_SUBMIT: Final[str] = "require_submodule_submit"

    # Inline tool calls
    ENABLE_INLINE_TOOL_CALLS: Final[str] = "enable_inline_tool_calls"
    INLINE_TOOL_CALLS_ONLY: Final[str] = "inline_tool_calls_only"
    ALLOW_INLINE_TOOLS_WITHOUT_ENABLE: Final[str] = "allow_inline_tools_without_enable"

    # Execution guardrails (opt-in); swebench_mode enables all of them at once
    SWEBENCH_MODE: Final[str] = "swebench_mode"
    ENABLE_GIT_FILTERING: Final[str] = "enable_git_filtering"
    REQUIRE_THOUGHT_SECTION: Final[str] = "require_thought_section"

    # Customizable reminder messages (fall back to built-in defaults when absent)
    THOUGHT_MISSING_MESSAGE: Final[str] = "thought_missing_message"
    THOUGHT_FOOTER_MESSAGE: Final[str] = "thought_footer_message"
    SUBMIT_REMINDER_MESSAGE: Final[str] = "submit_reminder_message"

    # Vision / computer use
    VISION_AUTO_SCREENSHOT: Final[str] = "vision_auto_screenshot"
    VISION_MAX_HISTORY: Final[str] = "vision_max_history"  # default: 4 (sliding window)


class Tokens:
    """Special tokens used in agent communication.

    These tokens are used for signaling specific actions or states
    in the agent's communication protocol.
    """

    SUBMIT_COMPLETE: Final[str] = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


# Checkpoint constants
CHECKPOINT_KIND: Final[str] = "yaml_agent_checkpoint"
CHECKPOINT_SCHEMA_VERSION: Final[int] = 1
