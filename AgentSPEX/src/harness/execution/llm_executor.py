"""LLM execution with multi-step tool calling.

This module provides the LLMExecutor class which handles LLM interactions
with support for tool calling, inline tools, submodule execution, and
durable execution via tracing.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

import litellm

from ..checkpoints.tracing import TracingMixin
from ..llms import LLMClient
from ..llms.tokens import (count_message_tokens, extract_token_usage,
                           get_model_context_limit)
from ..parsing.inline_tools import (PYTHON_BLOCK_LANGS,
                                    detect_malformed_code_blocks,
                                    extract_code_blocks_with_lang,
                                    parse_inline_tool_calls,
                                    select_executable_block,
                                    truncate_to_first_code_block,
                                    wrap_python_as_bash)
from ..prompts.yaml_prompts import (get_yaml_system_prompt,
                                    resolve_system_prompt)
from ..submodules.specs import extract_submodule_result_value
from ..tools.filtering import EffectiveToolConfig
from ..tools.formatting import format_inline_tool_result
from ..types.context import ContextKeys, Tokens
from ..types.serialization import get_tool_name, truncate_message
from ..utils.file_parsers import image_to_data_uri
from ..utils.step_utils import get_step_depth
from .shell_utils import ShellUtilsMixin

if TYPE_CHECKING:
    from mcp_client.client import MCPClient
    from mcp_client.logger import Logger

    from ..types.config import EffectiveArgs

# Timeout for OpenAI API calls (configurable via environment)
TIMEOUT: int = int(os.environ.get("TIMEOUT", "300"))


class ToolCallLimitExceeded(Exception):
    """Raised when the global max_tool_calls limit is reached."""
    pass


def _trim_vision_history(messages: list, max_images: int = 4) -> None:
    """Keep only the last `max_images` screenshot messages as actual images.

    Older screenshot messages have their image_url block stripped, leaving
    only the text label. Sliding window: last 4 rounds as full multimodal,
    older rounds as text summaries to prevent context blowup.
    """
    image_msg_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("role") == "user"
        and isinstance(m.get("content"), list)
        and any(b.get("type") == "image_url" for b in m["content"])
    ]
    to_strip = (
        image_msg_indices[: len(image_msg_indices) - max_images]
        if len(image_msg_indices) > max_images
        else []
    )
    for i in to_strip:
        text_only = [b for b in messages[i]["content"] if b.get("type") == "text"]
        if len(text_only) == 1:
            messages[i]["content"] = text_only[0]["text"]
        elif len(text_only) > 1:
            messages[i]["content"] = text_only
        else:
            # No text block at all — use a placeholder so content is never empty
            messages[i]["content"] = "[Screenshot removed from history]"


def _trim_som_elements(messages: list, max_keep: int = 4) -> None:
    """Strip som_elements from tool results beyond the last `max_keep` browser calls.

    Element IDs are regenerated on each browser_navigate, so old AC trees are
    not just stale but actively misleading — element [5] on a previous page is
    unrelated to element [5] on the current page. Keeping only the last `max_keep`
    AC trees in sync with the image sliding window prevents context blowup.
    """
    som_indices = [
        i
        for i, m in enumerate(messages)
        if m.get("role") == "tool"
        and isinstance(m.get("content"), str)
        and "som_elements" in m["content"]
    ]
    to_strip = (
        som_indices[: len(som_indices) - max_keep]
        if len(som_indices) > max_keep
        else []
    )
    for i in to_strip:
        try:
            parsed = json.loads(messages[i]["content"])
            if isinstance(parsed, dict) and isinstance(
                parsed.get("som_elements"), list
            ):
                n = len(parsed["som_elements"])
                parsed["som_elements"] = f"[truncated — {n} elements on previous page]"
                messages[i]["content"] = json.dumps(parsed, default=str)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass


class LLMExecutor(TracingMixin, ShellUtilsMixin):
    """Executes LLM interactions with multi-step tool calling support.

    This class is the core execution engine for LLM-driven workflow steps.
    It manages the conversation with the LLM, handles tool calls (both
    standard and inline), executes submodules, and supports durable
    execution via tracing.

    Attributes:
        mcp_client: MCP client for tool invocation.
        llm_client: LLMClient for LLM completions (supports multiple providers via LiteLLM).
        tools: List of available tool definitions.
        usage_tracker: Dict for tracking token usage across steps.
        metrics_lock: Threading lock for thread-safe metrics updates.

    Inherited from TracingMixin:
        _trace_lock: Lock for thread-safe trace writing.
        _trace_writer: Optional writer for durable execution traces.
        _llm_replay_events: Events for replay mode.
        _replay_index: Current position in replay events.

    Example:
        executor = LLMExecutor(mcp_client, tools, llm_client, usage_tracker)
        output, tokens = executor.execute_llm_step(
            instruction="Analyze the code",
            prev_output="",
            step_id=1,
            args=effective_args,
            logger=logger,
            context=workflow_context,
        )
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        tools: List[Dict[str, Any]],
        llm_client: LLMClient,
        usage_tracker: Dict[str, int],
    ) -> None:
        """Initialize the LLM executor.

        Args:
            mcp_client: MCP client for invoking tools.
            tools: List of tool definitions in OpenAI format.
            llm_client: LLMClient for chat completions (supports multiple providers).
            usage_tracker: Mutable dict for accumulating token usage.
        """
        self.mcp_client = mcp_client
        self.llm_client = llm_client
        self.tools = tools
        self.usage_tracker = usage_tracker
        self.metrics_lock = threading.Lock()

        # Reference to interpreter for submodule execution (set by Interpreter after init)
        self.interpreter: Optional[Any] = None

        # Initialize tracing state (required by TracingMixin)
        self._trace_lock = threading.Lock()
        self._trace_writer = None
        self._llm_replay_events = None
        self._replay_index = 0

    def _check_and_increment_tool_calls(self, args: EffectiveArgs) -> None:
        """Increment the global tool call counter and check the limit.

        Args:
            args: EffectiveArgs containing the max_tool_calls limit.

        Raises:
            ToolCallLimitExceeded: If the limit has been reached.
        """
        with self.metrics_lock:
            if (
                args.max_tool_calls is not None
                and self.usage_tracker["tool_calls_total"] >= args.max_tool_calls
            ):
                raise ToolCallLimitExceeded(
                    f"Global tool call limit of {args.max_tool_calls} reached "
                    f"(current: {self.usage_tracker['tool_calls_total']})"
                )
            self.usage_tracker["tool_calls_total"] += 1

    # ------------------------------------------------------------------
    # Vision helpers
    # ------------------------------------------------------------------

    def _vpath_to_host_path(self, vpath: str) -> Optional[str]:
        """Convert a Docker-internal vpath to a host-absolute path.

        The sandbox workspace is mounted at HOST_WORKSPACE on the host.
        Each MCP session has its own subdirectory keyed by sha1(session_id)[:16].
        """
        import hashlib

        host_ws = os.environ.get("HOST_WORKSPACE", "")
        session_id = getattr(self.mcp_client, "_session_id", None)
        if not host_ws or not session_id or not vpath:
            return None
        sess_key = hashlib.sha1(session_id.encode()).hexdigest()[:16]
        return os.path.join(host_ws, "sessions", sess_key, vpath.lstrip("/"))

    def execute_llm_step(
        self,
        instruction: str,
        prev_output: str,  # noqa: ARG002 - kept for API compatibility, use context["prev_output"] instead
        step_id: Union[int, str],
        args: EffectiveArgs,
        logger: Logger,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        step_config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, int]:
        """Execute a single LLM step with tool calling loop.

        Prepares messages and tools, then delegates to multi_step_tool_call_loop
        for the actual LLM interaction. Handles system prompt resolution and
        effective tool configuration.

        Args:
            instruction: The prompt/instruction for this step.
            prev_output: Output from the previous step (for context).
            step_id: Identifier for this step in the workflow.
            args: Effective arguments with model configuration.
            logger: Logger instance for output.
            context: Optional workflow context dictionary.
            system_prompt: Optional custom system prompt (overrides default).
            step_config: Optional step-specific configuration for tool filtering.

        Returns:
            Tuple of (output, tokens) where output is the final response
            and tokens is the total number of tokens used.
        """
        if context is None:
            context = {}
        if system_prompt is not None:
            system_prompt = resolve_system_prompt(system_prompt, context)
        else:
            system_prompt = get_yaml_system_prompt(
                context.get("task_name", "unknown"),
                context.get("goal", ""),
                args,
                context,
            )

        prompt = instruction

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        tool_config = EffectiveToolConfig.compute(self.tools, context, step_config)
        expose_submodules = context.get("expose_submodules_as_tools", True)
        combined_tools = tool_config.tools + (
            tool_config.submodule_tools if expose_submodules else []
        )
        return self.multi_step_tool_call_loop(
            step_id,
            messages,
            args,
            logger,
            tools=combined_tools,
            context=context,
            allowed_submodule_names=tool_config.enabled_submodule_names,
        )

    def _invoke_submodule_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Dict[str, Any],
        args: EffectiveArgs,
        logger: Logger,
        step_id: Union[int, str],
        parent_step_id: Optional[Union[int, str]] = None,
        parent_iteration: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Invoke a submodule as a tool call.

        Looks up the submodule specification, resolves parameters from context
        and tool arguments, then executes the submodule workflow.

        Args:
            tool_name: Name of the submodule to invoke.
            tool_args: Arguments passed by the LLM.
            context: Current workflow context.
            args: Effective arguments for LLM configuration.
            logger: Logger instance for output.
            step_id: Identifier for this invocation.
            parent_step_id: ID of the calling step (for logging).
            parent_iteration: Iteration number in parent loop (for logging).

        Returns:
            Dict with 'result' and 'tokens' keys.

        Raises:
            ValueError: If submodule not found or required parameters missing.
        """
        registry = context.get("submodule_registry", {})
        spec = registry.get(tool_name)
        if not spec:
            raise ValueError(f"Unknown submodule tool: {tool_name}")

        params: Dict[str, Any] = {}
        missing = []

        for p in spec.context_params:
            if p.name in context:
                params[p.name] = context[p.name]
            elif p.default is not None:
                params[p.name] = p.default
            elif p.required:
                missing.append(p.name)

        for p in spec.model_params:
            if p.name in tool_args:
                params[p.name] = tool_args[p.name]
            elif p.default is not None:
                params[p.name] = p.default
            elif p.required:
                missing.append(p.name)

        if missing:
            raise ValueError(
                f"Missing required submodule parameters: {', '.join(missing)}"
            )

        step_id_str = str(step_id)
        logger.log_event(
            logger,
            "step_start",
            {
                "step_id": step_id_str,
                "step_number": step_id_str,
                "name": tool_name,
                "step_type": "submodule_call",
                "instruction": spec.description or "",
                "depth": get_step_depth(step_id_str),
                "parent_step_id": (
                    str(parent_step_id) if parent_step_id is not None else None
                ),
                "parent_iteration": parent_iteration,
            },
        )

        call_step_data = {
            "call": {
                "module": spec.module_path,
                "parameters": params,
                "return": spec.return_var,
            }
        }
        try:
            if self.interpreter is None:
                raise RuntimeError(
                    "Cannot invoke submodule: interpreter reference not set. "
                    "Ensure LLMExecutor.interpreter is set by the parent Interpreter."
                )
            result, tokens = self.interpreter.execute_call_step(
                call_step_data, context, step_id, args, logger
            )
            logger.log_event(
                logger,
                "step_end",
                {
                    "step_id": step_id_str,
                    "tokens": tokens,
                    "status": "completed",
                },
            )
            return {"result": result, "tokens": tokens}
        except Exception as e:
            logger.log_event(
                logger,
                "step_end",
                {
                    "step_id": step_id_str,
                    "tokens": 0,
                    "status": "error",
                    "error": str(e),
                },
            )
            raise

    def multi_step_tool_call_loop(
        self,
        step_id: Union[int, str],
        messages: List[Dict[str, Any]],
        args: EffectiveArgs,
        logger: Logger,
        tools: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        record_assistant_message: bool = False,
        history_messages: Optional[List[Dict[str, Any]]] = None,
        allowed_submodule_names: Optional[List[str]] = None,
    ) -> Tuple[Any, int]:
        """Execute the multi-step tool calling loop.

        This is the core execution loop that:
        1. Sends messages to the LLM
        2. Parses tool calls (standard, inline, or raw bash)
        3. Executes tool calls and collects results
        4. Appends results to conversation and iterates
        5. Terminates on final response or max iterations

        Args:
            step_id: Identifier for this step.
            messages: Current conversation messages (modified in-place).
            args: Effective arguments with model and limit configuration.
            logger: Logger instance for output.
            tools: Optional list of available tools (defaults to self.tools).
            context: Optional workflow context dictionary.
            record_assistant_message: Whether to append final response to history.
            history_messages: Optional separate history to append messages to.
            allowed_submodule_names: Optional whitelist of allowed submodules.

        Returns:
            Tuple of (output, tokens) where output is the final LLM response
            and tokens is the total number of tokens used across all iterations.
        """
        effective_tools = tools if tools is not None else self.tools
        allowed_tool_names = {get_tool_name(t) for t in (effective_tools or [])}
        prev_output = ""
        num_tokens = 0
        is_last_step = False
        step_id_str = str(step_id)
        submit_reminder_count = 0
        max_empty_reminders = 3
        submit_reminder_iter = -2

        for iter in range(args.max_tool_calls_per_step + 1):
            logger(f"   --- Tool call iteration {iter + 1} ---")
            logger(f"   calling {args.model} with messages:")

            # Calculate context utilization
            current_tokens = count_message_tokens(messages, args.model)
            context_limit = get_model_context_limit(args.model)

            if current_tokens > 0:
                utilization_ratio = current_tokens / context_limit
                logger(
                    f"   Context: {current_tokens:,} / {context_limit:,} tokens ({utilization_ratio:.1%} utilized)"
                )
            else:
                logger(f"   Context: Unable to count tokens")
                utilization_ratio = None

            # Skip last-step warnings on the iteration right after the
            # submit reminder to avoid consecutive user messages.
            if submit_reminder_iter != iter - 1:
                if is_last_step:
                    messages.append(
                        {
                            "role": "user",
                            "content": "This will be the last message in this step. So please do not perform any tool call and provide final output of this step.",
                        }
                    )
                elif iter == args.max_tool_calls_per_step - 1 or (
                    utilization_ratio and utilization_ratio >= args.context_threshold
                ):
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You are approaching the context limit for this step. "
                                "Wrap up your current progress and provide your final output. "
                                "Do not start any new tool calls. Summarize your findings and conclusions so far."
                            ),
                        }
                    )
                    is_last_step = True

            logger.print_messages(messages, max_value_len=2000, num_indents=4)
            logger.log_event(
                logger,
                "messages_start",
                {
                    "step_id": step_id_str,
                    "iteration": iter + 1,
                    "messages": messages,
                    "context_tokens": max(current_tokens, 0),
                    "context_limit": context_limit,
                    "utilization": (
                        (utilization_ratio * 100)
                        if utilization_ratio is not None
                        else 0
                    ),
                },
            )

            replay_trace = getattr(args, "replay_trace", None)
            if replay_trace:
                # Replay mode: do not call OpenAI. Use recorded llm_response events.
                ev = self._next_replay_event(step_id=step_id_str, iteration=iter + 1)

                class _Fn:
                    def __init__(self, name: str, arguments: str):
                        self.name = name
                        self.arguments = arguments

                class _TC:
                    def __init__(self, id_: str, fn):
                        self.id = id_
                        self.function = fn

                class _Msg:
                    def __init__(self, content: str, tool_calls: list):
                        self.content = content
                        self.tool_calls = tool_calls

                class _Choice:
                    def __init__(self, msg):
                        self.message = msg

                class _Usage:
                    total_tokens = 0
                    prompt_tokens = 0
                    completion_tokens = 0

                tc_objs = []
                for tc in ev.get("tool_calls") or []:
                    fn = _Fn(
                        str((tc.get("function") or {}).get("name") or ""),
                        str((tc.get("function") or {}).get("arguments") or "{}"),
                    )
                    tc_objs.append(_TC(str(tc.get("id")), fn))
                msg_obj = _Msg(str(ev.get("content") or ""), tc_objs)
                resp = type(
                    "Resp", (), {"choices": [_Choice(msg_obj)], "usage": _Usage()}
                )()
            else:
                # Determine temperature (some models like GPT-5 need temperature=1.0)
                temperature = args.temperature
                if args.model in ["gpt-5", "gpt-5-mini", "gpt-5-nano"]:
                    temperature = 1.0

                model_kwargs = dict(getattr(args, "model_kwargs", None) or {})
                # Remove keys already passed as explicit arguments to avoid duplicates
                for k in (
                    "temperature",
                    "model",
                    "tools",
                    "tool_choice",
                    "timeout",
                    "api_base",
                ):
                    model_kwargs.pop(k, None)

                resp = self.llm_client.completion(
                    model=args.model,
                    messages=messages,
                    tools=effective_tools if effective_tools else None,
                    tool_choice="auto" if effective_tools else None,
                    temperature=temperature,
                    timeout=TIMEOUT,
                    api_base=args.api_base,
                    **model_kwargs,
                )

            usage = extract_token_usage(resp.usage)
            usage_total = usage["total_tokens"]
            usage_prompt = usage["prompt_tokens"]
            usage_completion = usage["completion_tokens"]
            usage_reasoning = usage["reasoning_tokens"]
            num_tokens += usage_total
            try:
                call_cost = litellm.completion_cost(completion_response=resp)
            except Exception:
                call_cost = 0.0

            with self.metrics_lock:
                self.usage_tracker["prompt_tokens_total"] += usage_prompt
                self.usage_tracker["completion_tokens_total"] += usage_completion
                self.usage_tracker["reasoning_tokens_total"] += usage_reasoning
                self.usage_tracker["cost_total"] += call_cost
            logger.log_event(
                logger,
                "messages_end",
                {
                    "step_id": step_id_str,
                    "iteration": iter + 1,
                    "usage": {
                        "prompt_tokens": usage_prompt,
                        "completion_tokens": usage_completion,
                        "total_tokens": usage_total,
                        "reasoning_tokens": usage_reasoning,
                        "cost": call_cost,
                    },
                },
            )
            logger.log_event(
                logger,
                "agent_iteration",
                {
                    "step_id": step_id_str,
                    "number": iter + 1,
                    "max": args.max_tool_calls_per_step + 1,
                    "tokens": max(current_tokens, 0),
                    "limit": context_limit,
                    "utilization": (
                        (utilization_ratio * 100)
                        if utilization_ratio is not None
                        else 0
                    ),
                },
            )
            logger("")

            choice = resp.choices[0]
            msg = choice.message
            logger.log_event(
                logger,
                "llm_response",
                {
                    "step_id": step_id_str,
                    "iteration": iter + 1,
                    "content": msg.content or "",
                },
            )
            # Durable execution: persist llm_response (incl tool_calls) into trace.jsonl
            try:
                tool_calls_payload = []
                for tc in msg.tool_calls or []:
                    tool_calls_payload.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )
                self._trace(
                    {
                        "type": "llm_response",
                        "step_id": step_id_str,
                        "iteration": iter + 1,
                        "content": msg.content or "",
                        "tool_calls": tool_calls_payload,
                    }
                )
            except Exception:
                pass

            submodule_registry = (
                context.get("submodule_registry", {}) if context else {}
            )
            inline_calls_executed = False
            assistant_msg_appended = False
            submodule_result_value = None
            stop_on_return = bool(
                context
                and (
                    context.get("stop_on_return")
                    or context.get("stop_on_submodule_result")
                )
            )
            # Inline tool calls are opt-in for backwards compatibility
            # Also enabled if inline_tool_calls_only is set (implies inline mode)
            # Also enabled during replay to ensure recorded inline tool calls are replayed
            enable_inline_tool_calls = bool(
                context
                and (
                    context.get("enable_inline_tool_calls")
                    or context.get("inline_tool_calls_only")
                )
            ) or bool(replay_trace)
            # Strict-bash-fence mode (engine fix, conv 7ef9d7d4): only an explicitly
            # shell-tagged ```bash fence is executable; an untagged/quoted fence is
            # NOT run and does NOT preempt a real later ```bash action. Gated
            # default-OFF (env HARNESS_STRICT_BASH_FENCE / context strict_bash_fence)
            # so the live run's behavior is byte-identical unless opted in.
            strict_bash_fence = False
            if enable_inline_tool_calls:
                _sbf = context.get("strict_bash_fence") if context else None
                if _sbf is None:
                    # HARNESS_STRICT_BASH_FENCE is the primary name; WF_STRICT_BASH_FENCE
                    # is an alias that rides the training launch's WF_* env propagation.
                    _raw = (os.environ.get("HARNESS_STRICT_BASH_FENCE")
                            or os.environ.get("WF_STRICT_BASH_FENCE") or "0")
                    _sbf = _raw.strip().lower() not in ("0", "", "false", "no")
                strict_bash_fence = bool(_sbf)

            # Truncate to first code block if multiple are present (legacy only —
            # strict mode keeps the full content so a real ```bash after a quoted
            # fence is preserved and recorded).
            inline_content = msg.content or ""
            if enable_inline_tool_calls and not strict_bash_fence:
                inline_content = truncate_to_first_code_block(inline_content)

            malformed_inline_error = (
                detect_malformed_code_blocks(inline_content)
                if enable_inline_tool_calls
                else ""
            )
            if malformed_inline_error:
                raw_content = msg.content or ""
                truncated_content = (
                    raw_content[:30] + "...truncated"
                    if len(raw_content) > 30
                    else raw_content
                )
                assistant_msg = {
                    "role": "assistant",
                    "content": truncated_content,
                }
                messages.append(assistant_msg)
                if history_messages is not None:
                    history_messages.append(assistant_msg)
                assistant_msg_appended = True

                inline_user_msg = {
                    "role": "user",
                    "content": malformed_inline_error,
                }
                messages.append(inline_user_msg)
                if history_messages is not None:
                    history_messages.append(inline_user_msg)
                inline_calls_executed = True
                # Reject malformed inline format and skip tool execution
                continue

            # If the response contains a code block but no THOUGHT section,
            # truncate and remind — a missing THOUGHT often leads to
            # degraded follow-up responses (including empty outputs).
            require_thought_section = bool(
                context and context.get(ContextKeys.REQUIRE_THOUGHT_SECTION)
            )
            _default_thought_footer = "Continue working hard and always remember to include a THOUGHT section."
            thought_footer_message = (
                (
                    context.get(ContextKeys.THOUGHT_FOOTER_MESSAGE)
                    or _default_thought_footer
                )
                if require_thought_section
                else None
            )
            if (
                require_thought_section
                and enable_inline_tool_calls
                and inline_content.strip()
                and "```" in inline_content
                and "THOUGHT" not in inline_content
            ):
                truncated_content = (
                    inline_content[:30] + "...truncated"
                    if len(inline_content) > 30
                    else inline_content
                )
                assistant_msg = {
                    "role": "assistant",
                    "content": truncated_content,
                }
                messages.append(assistant_msg)
                if history_messages is not None:
                    history_messages.append(assistant_msg)
                assistant_msg_appended = True

                _default_thought_missing = (
                    "Your response was missing a THOUGHT section. "
                    "No commands were executed.\n\n"
                    "You MUST include a THOUGHT section before your code block. "
                    "Please retry with the following format:\n\n"
                    "<format_example>\n"
                    "THOUGHT: Your reasoning and analysis here\n\n"
                    "```bash\n"
                    "your_command_here\n"
                    "```\n"
                    "</format_example>"
                )
                thought_reminder = (
                    (
                        context.get(ContextKeys.THOUGHT_MISSING_MESSAGE)
                        or _default_thought_missing
                    )
                    if context
                    else _default_thought_missing
                )
                inline_user_msg = {
                    "role": "user",
                    "content": thought_reminder,
                }
                messages.append(inline_user_msg)
                if history_messages is not None:
                    history_messages.append(inline_user_msg)
                inline_calls_executed = True
                logger(f"  Missing THOUGHT section — truncated and reminded")
                continue

            selected_block = (
                select_executable_block(
                    inline_content, strict_bash_fence=strict_bash_fence)
                if enable_inline_tool_calls
                else None
            )
            raw_bash_block = None
            if selected_block is not None:
                lang, block_content = selected_block
                candidate_block = block_content.strip()
                if candidate_block and (
                    not lang
                    or lang.strip().lower() in {"bash", "sh", "shell", "zsh", "fish"}
                ):
                    match = re.match(r"^\s*([A-Za-z_]\w*)\s*\(", candidate_block)
                    if not match or match.group(1) not in (
                        allowed_tool_names | set(submodule_registry.keys())
                    ):
                        raw_bash_block = candidate_block
                elif (
                    candidate_block
                    and lang
                    and lang.strip().lower() in PYTHON_BLOCK_LANGS
                ):
                    raw_bash_block = wrap_python_as_bash(candidate_block)

            inline_calls = (
                []
                if (raw_bash_block or not enable_inline_tool_calls)
                else parse_inline_tool_calls(inline_content)
            )
            if raw_bash_block:
                assistant_msg = {
                    "role": "assistant",
                    "content": inline_content,
                }
                messages.append(assistant_msg)
                if history_messages is not None:
                    history_messages.append(assistant_msg)
                assistant_msg_appended = True

                tool_name = "shell_run"
                tool_args = {"text": raw_bash_block}
                tool_args = self._inject_shell_defaults(tool_name, tool_args, context)
                is_submodule_tool = False
                bypass_inline_tool_filter = (
                    bool(context.get("allow_inline_tools_without_enable"))
                    if context
                    else False
                )
                inline_results = []

                # Check for blocked commands (e.g., git log without --oneline)
                blocked_error = self._check_blocked_command(raw_bash_block, context)
                if blocked_error:
                    inline_results.append(
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "error": blocked_error,
                        }
                    )
                    logger(f"Blocked command: {blocked_error}")
                elif (
                    not bypass_inline_tool_filter
                    and allowed_tool_names
                    and tool_name not in allowed_tool_names
                ):
                    inline_results.append(
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "error": "Tool is not enabled for this step",
                        }
                    )
                    logger(f"Tool {tool_name} is not enabled for this step")
                else:
                    logger.log_event(
                        logger,
                        "inline_tool_call_start",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": 1,
                            "name": tool_name,
                            "args": json.dumps(tool_args, default=str),
                        },
                    )
                    try:
                        self._check_and_increment_tool_calls(args)
                        result_value = self.mcp_client.invoke(
                            tool_name, tool_args, is_catch_exception=False
                        )
                        inline_results.append(
                            {
                                "name": tool_name,
                                "args": tool_args,
                                "result": result_value,
                            }
                        )
                    except ToolCallLimitExceeded:
                        raise
                    except Exception as e:
                        inline_results.append(
                            {
                                "name": tool_name,
                                "args": tool_args,
                                "error": str(e),
                            }
                        )
                        logger(f"Tool {tool_name} failed with error: {e}")

                    logger.log_event(
                        logger,
                        "inline_tool_call_end",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": 1,
                            "name": tool_name,
                            "result": (
                                inline_results[-1].get("result")
                                if inline_results
                                else ""
                            ),
                        },
                    )

                inline_user_msg = {
                    "role": "user",
                    "content": "\n".join(
                        format_inline_tool_result(
                            item.get("name", ""),
                            item.get("result", item),
                            thought_footer_message=thought_footer_message,
                        )
                        for item in inline_results
                    ),
                }
                messages.append(inline_user_msg)
                if history_messages is not None:
                    history_messages.append(inline_user_msg)
                inline_calls_executed = True

                if self._is_submit_command(raw_bash_block, context):
                    prev_output = Tokens.SUBMIT_COMPLETE
                    break

                if stop_on_return and inline_results:
                    extracted = extract_submodule_result_value(
                        inline_results[-1].get("result", "")
                    )
                    if extracted is not None:
                        submodule_result_value = extracted
                        prev_output = submodule_result_value
                        break

            if inline_calls:
                assistant_msg = {
                    "role": "assistant",
                    "content": inline_content,
                }
                messages.append(assistant_msg)
                if history_messages is not None:
                    history_messages.append(assistant_msg)
                assistant_msg_appended = True

                inline_results = []
                for call_index, call in enumerate(inline_calls, start=1):
                    tool_name = call.name
                    tool_args = call.args or {}
                    tool_args = self._inject_shell_defaults(
                        tool_name, tool_args, context
                    )
                    is_submodule_tool = tool_name in submodule_registry
                    bypass_inline_tool_filter = (
                        bool(context.get("allow_inline_tools_without_enable"))
                        if context
                        else False
                    )
                    if is_submodule_tool:
                        if (
                            allowed_submodule_names is not None
                            and tool_name not in allowed_submodule_names
                        ):
                            inline_results.append(
                                {
                                    "name": tool_name,
                                    "args": tool_args,
                                    "error": "Submodule is not enabled for this step",
                                }
                            )
                            logger(
                                f"Submodule {tool_name} is not enabled for this step"
                            )
                            continue
                    elif allowed_tool_names and tool_name not in allowed_tool_names:
                        if bypass_inline_tool_filter:
                            inline_results.append(
                                {
                                    "name": tool_name,
                                    "args": tool_args,
                                    "result": f"Note: '{tool_name}' is not a supported tool.",
                                }
                            )
                            logger(
                                f"Unrecognized tool '{tool_name}' — "
                                f"replied with guidance instead of invoking"
                            )
                            continue
                        inline_results.append(
                            {
                                "name": tool_name,
                                "args": tool_args,
                                "error": "Tool is not enabled for this step",
                            }
                        )
                        logger(f"Tool {tool_name} is not enabled for this step")
                        continue

                    logger.log_event(
                        logger,
                        "inline_tool_call_start",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": call_index,
                            "name": tool_name,
                            "args": json.dumps(tool_args, default=str),
                        },
                    )

                    try:
                        self._check_and_increment_tool_calls(args)
                        if is_submodule_tool:
                            result_dict = self._invoke_submodule_tool(
                                tool_name,
                                tool_args,
                                context,
                                args,
                                logger,
                                f"{step_id_str}.inline.{call_index}",
                                parent_step_id=step_id_str,
                                parent_iteration=iter + 1,
                            )
                            result_value = result_dict.get("result", result_dict)
                            # Propagate submit signal from submodule
                            if self._is_submodule_submit_result(result_value):
                                inline_results.append(
                                    {
                                        "name": tool_name,
                                        "args": tool_args,
                                        "result": result_value,
                                    }
                                )
                                logger.log_event(
                                    logger,
                                    "inline_tool_call_end",
                                    {
                                        "step_id": step_id_str,
                                        "iteration": iter + 1,
                                        "call": call_index,
                                        "name": tool_name,
                                        "result": "SUBMIT_COMPLETE (propagated from submodule)",
                                    },
                                )
                                prev_output = Tokens.SUBMIT_COMPLETE
                                break
                        else:
                            result_value = self.mcp_client.invoke(
                                tool_name, tool_args, is_catch_exception=False
                            )
                        if stop_on_return:
                            extracted = extract_submodule_result_value(result_value)
                            if extracted is not None:
                                submodule_result_value = extracted
                        inline_results.append(
                            {
                                "name": tool_name,
                                "args": tool_args,
                                "result": result_value,
                            }
                        )
                    except ToolCallLimitExceeded:
                        raise
                    except Exception as e:
                        inline_results.append(
                            {
                                "name": tool_name,
                                "args": tool_args,
                                "error": str(e),
                            }
                        )
                        logger(f"Tool {tool_name} failed with error: {e}")

                    logger.log_event(
                        logger,
                        "inline_tool_call_end",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": call_index,
                            "name": tool_name,
                            "result": (
                                inline_results[-1].get("result")
                                if inline_results
                                else ""
                            ),
                        },
                    )

                inline_user_msg = {
                    "role": "user",
                    "content": "\n".join(
                        format_inline_tool_result(
                            item.get("name", ""),
                            item.get("result", item),
                            thought_footer_message=thought_footer_message,
                        )
                        for item in inline_results
                    ),
                }
                messages.append(inline_user_msg)
                if history_messages is not None:
                    history_messages.append(inline_user_msg)
                inline_calls_executed = True

                # Check if a submodule propagated a submit signal
                if prev_output == Tokens.SUBMIT_COMPLETE:
                    break

                if stop_on_return and submodule_result_value is not None:
                    prev_output = submodule_result_value
                    break

                if tool_name == "shell_run":
                    cmd_text = ""
                    if isinstance(tool_args, dict):
                        cmd_text = tool_args.get("text", "")
                    if self._is_submit_command(cmd_text, context):
                        prev_output = Tokens.SUBMIT_COMPLETE
                        break

            tool_calls = msg.tool_calls or []
            if tool_calls and context and context.get("inline_tool_calls_only"):
                if not assistant_msg_appended:
                    assistant_msg = {
                        "role": "assistant",
                        "content": msg.content or "",
                    }
                    messages.append(assistant_msg)
                    if history_messages is not None:
                        history_messages.append(assistant_msg)
                inline_user_msg = {
                    "role": "user",
                    "content": (
                        "Your messages must follow:\n"
                        "\n"
                        "<format_example>\n"
                        "THOUGHT: Your reasoning and analysis here\n"
                        "\n"
                        "Example of a tool call:\n"
                        "```bash\n"
                        f'some_tool({{"arg": "value"}})\n'
                        "```\n"
                        "</format_example>"
                    ),
                }
                messages.append(inline_user_msg)
                if history_messages is not None:
                    history_messages.append(inline_user_msg)
                inline_calls_executed = True
                continue
            tool_calls_msg = []
            tool_results_msg = []
            tool_calls_for_history = []
            tool_results_for_history = []
            vision_msgs = []  # screenshot image messages to inject after tool results

            if tool_calls:
                tool_calls_msg.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )

                for call_index, tool_call in enumerate(tool_calls, start=1):
                    tool_name = tool_call.function.name
                    tool_args_raw = tool_call.function.arguments
                    is_submodule_tool = tool_name in submodule_registry
                    if is_submodule_tool:
                        if (
                            allowed_submodule_names is not None
                            and tool_name not in allowed_submodule_names
                        ):
                            tool_results_msg.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_name,
                                    "content": "error: Submodule is not enabled for this step",
                                }
                            )
                            if history_messages is not None:
                                tool_results_for_history.append(tool_results_msg[-1])
                            logger(
                                f"Submodule {tool_name} is not enabled for this step"
                            )
                            continue
                    elif allowed_tool_names and tool_name not in allowed_tool_names:
                        tool_results_msg.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": "error: Tool is not enabled for this step",
                            }
                        )
                        if history_messages is not None:
                            tool_results_for_history.append(tool_results_msg[-1])
                        logger(f"Tool {tool_name} is not enabled for this step")
                        continue
                    if history_messages is not None:
                        tool_calls_for_history.append(
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                },
                            }
                        )
                    logger.log_event(
                        logger,
                        "tool_call_start",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": call_index,
                            "name": tool_name,
                            "args": tool_args_raw,
                        },
                    )

                    try:
                        tool_args = (
                            json.loads(tool_args_raw)
                            if isinstance(tool_args_raw, str)
                            else tool_args_raw
                        ) or {}
                    except Exception:
                        tool_args = {}
                    tool_args = self._inject_shell_defaults(
                        tool_name, tool_args, context
                    )

                    try:
                        self._check_and_increment_tool_calls(args)
                        if context and tool_name in context.get(
                            "submodule_registry", {}
                        ):
                            result_dict = self._invoke_submodule_tool(
                                tool_name,
                                tool_args,
                                context,
                                args,
                                logger,
                                f"{step_id_str}.tool.{call_index}",
                                parent_step_id=step_id_str,
                                parent_iteration=iter + 1,
                            )
                            # Propagate submit signal from submodule
                            sub_result = result_dict.get("result", result_dict)
                            if self._is_submodule_submit_result(sub_result):
                                logger.log_event(
                                    logger,
                                    "tool_call_end",
                                    {
                                        "step_id": step_id_str,
                                        "iteration": iter + 1,
                                        "call": call_index,
                                        "name": tool_name,
                                        "result": "SUBMIT_COMPLETE (propagated from submodule)",
                                    },
                                )
                                prev_output = Tokens.SUBMIT_COMPLETE
                                break
                        else:
                            result_dict = self.mcp_client.invoke(
                                tool_name, tool_args, is_catch_exception=False
                            )
                        if is_submodule_tool:
                            tool_content = json.dumps(
                                result_dict.get("result", result_dict), default=str
                            )
                        else:
                            tool_content = json.dumps(result_dict, default=str)
                        tool_results_msg.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": tool_content,
                            }
                        )
                        if history_messages is not None:
                            tool_results_for_history.append(tool_results_msg[-1])
                        # Vision: inject screenshot as user message after tool result
                        if context.get(ContextKeys.VISION_AUTO_SCREENSHOT):
                            img_vpath = result_dict.get(
                                "som_filename"
                            ) or result_dict.get("screenshot_filename")
                            host_path = self._vpath_to_host_path(img_vpath)
                            if host_path and os.path.exists(host_path):
                                try:
                                    data_uri = image_to_data_uri(host_path)
                                    vision_msgs.append(
                                        {
                                            "role": "user",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": f"[Screenshot from {tool_name}]",
                                                },
                                                {
                                                    "type": "image_url",
                                                    "image_url": {"url": data_uri},
                                                },
                                            ],
                                        }
                                    )
                                except Exception:
                                    pass
                    except ToolCallLimitExceeded:
                        raise
                    except Exception as e:
                        tool_results_msg.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": f"error: Tool invocation failed with error {e}",
                            }
                        )
                        if history_messages is not None:
                            tool_results_for_history.append(tool_results_msg[-1])
                        logger(f"Tool {tool_name} failed with error: {e}")

                    if stop_on_return and tool_results_msg:
                        latest_content = tool_results_msg[-1].get("content", "")
                        extracted = None
                        if isinstance(latest_content, str):
                            try:
                                parsed_content = json.loads(latest_content)
                                extracted = extract_submodule_result_value(
                                    parsed_content
                                )
                            except Exception:
                                extracted = extract_submodule_result_value(
                                    latest_content
                                )
                        if extracted is not None:
                            submodule_result_value = extracted

                    if tool_name == "shell_run":
                        cmd_text = ""
                        if isinstance(tool_args, dict):
                            cmd_text = tool_args.get("text", "")
                        if self._is_submit_command(cmd_text, context):
                            prev_output = Tokens.SUBMIT_COMPLETE
                            break

                    result_entry = tool_results_msg[-1] if tool_results_msg else None
                    logger.log_event(
                        logger,
                        "tool_call_end",
                        {
                            "step_id": step_id_str,
                            "iteration": iter + 1,
                            "call": call_index,
                            "name": tool_name,
                            "result": (
                                result_entry.get("content") if result_entry else ""
                            ),
                        },
                    )

            # Check if a submodule propagated a submit signal
            if prev_output == Tokens.SUBMIT_COMPLETE:
                break

            if tool_calls_msg:
                messages.extend(tool_calls_msg)
                messages.extend(tool_results_msg)
                if vision_msgs:
                    messages.extend(vision_msgs)
                    max_imgs = context.get(ContextKeys.VISION_MAX_HISTORY, 4)
                    _trim_vision_history(messages, max_images=max_imgs)
                if context.get(ContextKeys.VISION_AUTO_SCREENSHOT):
                    max_imgs = context.get(ContextKeys.VISION_MAX_HISTORY, 4)
                    _trim_som_elements(messages, max_keep=max_imgs)
                if history_messages is not None:
                    if tool_calls_for_history:
                        history_messages.append(
                            {
                                "role": "assistant",
                                "content": msg.content or "",
                                "tool_calls": tool_calls_for_history,
                            }
                        )
                    history_messages.extend(tool_results_for_history)
                logger(f"  Tool calls performed:")
                logger.print_messages(tool_calls_msg, max_value_len=2000, num_indents=4)
                logger(f"  Tool calls result:")
                logger.print_messages(
                    tool_results_msg, max_value_len=2000, num_indents=4
                )
                logger("\n")

            if stop_on_return and submodule_result_value is not None:
                prev_output = submodule_result_value
                break

            if len(msg.content or "") > args.max_tokens_per_step // 2:
                content = truncate_message(
                    msg.content or "", args.max_tokens_per_step // 2
                )
                logger(
                    f"  Output is too long, truncating to {args.max_tokens_per_step//2} characters"
                )
            else:
                content = msg.content or ""

            if (not tool_calls_msg and not inline_calls_executed) or is_last_step:
                logger(f"  Assistant's output for step {step_id}: {content}\n")
                prev_output = content

                # If submission is required but hasn't happened, send a
                # reminder instead of ending the task (up to max_empty_reminders times).
                if (
                    submit_reminder_count < max_empty_reminders
                    and not is_last_step
                    and context
                    and context.get("require_submodule_submit")
                    and allowed_submodule_names
                    and "submit_changes" in allowed_submodule_names
                    and prev_output != Tokens.SUBMIT_COMPLETE
                ):
                    submit_reminder_count += 1
                    submit_reminder_iter = iter
                    # Append the assistant's response to messages so the
                    # conversation stays in valid user/assistant alternation.
                    assistant_msg = {"role": "assistant", "content": content}
                    messages.append(assistant_msg)
                    if history_messages is not None:
                        history_messages.append(assistant_msg)
                    _default_submit_reminder = (
                        "You have not submitted your changes yet. "
                        "You MUST call the submit_changes subagent before this task can end. "
                        "Please review your work and submit:\n\n"
                        "```submit_changes\n"
                        'query: "Brief summary of what you changed and why"\n'
                        "```"
                    )
                    reminder = (
                        context.get(ContextKeys.SUBMIT_REMINDER_MESSAGE)
                        or _default_submit_reminder
                    )
                    messages.append({"role": "user", "content": reminder})
                    if history_messages is not None:
                        history_messages.append({"role": "user", "content": reminder})
                    logger(f"  Submit reminder injected — continuing loop")
                    continue

                if record_assistant_message:
                    target = (
                        history_messages if history_messages is not None else messages
                    )
                    target.append({"role": "assistant", "content": content})
                break

        return prev_output, num_tokens


# Backward compatibility alias
LLM_Executor = LLMExecutor
