"""Core agentic loop: reactive while(True) with MCP tool access and task management."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import litellm
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style

from harness.llms.client import LLMClient
from harness.llms.tokens import (count_message_tokens, extract_token_usage,
                                 get_model_context_limit)
from mcp_client.client import MCPClient
from mcp_client.logger import Logger

from .plan_executor import PlanExecutor
from .plan_generator import PlanGenerator
from .prompts import get_orchestrator_system_prompt
from .session import LoopConfig, Session
from .task_board import TaskBoard, TaskStatus
from .tools import (OrchestratorTool, build_execution_tools, build_plan_tools,
                    build_task_management_tools, tools_to_openai_format)
from .verifier import PlanVerifier

# Inject a wrap-up message when context reaches this fraction of the limit
_CONTEXT_WRAP_UP_THRESHOLD = 0.70

_PROMPT_STYLE = Style.from_dict(
    {
        "slash-cmd": "ansiyellow bold",
    }
)


class _SlashCommandLexer(Lexer):
    """Highlights /command at the start of input in yellow."""

    def lex_document(self, document):
        def get_line(lineno):
            line = document.lines[lineno]
            if line.startswith("/"):
                parts = line.split(" ", 1)
                tokens = [("class:slash-cmd", parts[0])]
                if len(parts) > 1:
                    tokens.append(("", " " + parts[1]))
                return tokens
            return [("", line)]

        return get_line


def _serialize_tool_calls(tool_calls) -> list[dict]:
    """Convert LiteLLM tool_calls to OpenAI message format."""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in tool_calls
    ]


def _format_mcp_result(tool_name: str, raw: Any) -> str:
    """Format a raw MCP tool result for the LLM conversation.

    Borrowed pattern from agent/tools/formatting.py but:
    - Handles list results with proper JSON (not repr)
    - No YAML-workflow-specific prompt injections
    """
    # Unwrap nested {"result": {...}} structures produced by some MCP tools
    if isinstance(raw, dict) and "result" in raw and isinstance(raw["result"], dict):
        raw = raw["result"]

    # Special formatting for shell_run: extract structured fields
    if tool_name == "shell_run":
        if not isinstance(raw, dict):
            return f"Return code: None\nOutput: {raw}"
        parts = [
            f"Return code: {raw.get('returncode')}",
            f"Output: {raw.get('output')}",
        ]
        if raw.get("error"):
            parts.append(f"Error: {raw['error']}")
        if raw.get("warning"):
            parts.append(f"Warning: {raw['warning']}")
        return "\n".join(parts)

    # Dicts and lists: pretty-printed JSON
    if isinstance(raw, (dict, list)):
        try:
            return json.dumps(raw, indent=2, default=str)
        except Exception:
            return str(raw)

    if raw is None:
        return "Result: None"
    return str(raw)


def _truncate_tool_result(result_str: str, max_chars: int) -> str:
    """Truncate a tool result to max_chars, preserving head and tail."""
    if len(result_str) <= max_chars:
        return result_str
    head_len = int(max_chars * 0.7)
    tail_len = int(max_chars * 0.2)
    truncated_count = len(result_str) - head_len - tail_len
    return (
        f"{result_str[:head_len]}\n\n"
        f"... [TRUNCATED: {truncated_count:,} characters removed] ...\n\n"
        f"{result_str[-tail_len:]}"
    )


class AgenticLoop:
    """Reactive agentic loop with MCP tool access and task management.

    The core while(True) loop: call the LLM with MCP + orchestrator tools,
    execute any tool calls (routing locally or to MCP), append results to
    conversation, and repeat until the LLM responds with no tool calls.

    Orchestrator tools (task_create, task_update, task_list, ask_user) run
    in-process. MCP tools run in the sandbox VM. The LLM decides which to use.

    Protections:
    - Tool results are truncated to max_tool_result_chars before appending
    - Proactive context monitoring at 70% utilization injects a wrap-up message
    - ContextWindowExceededError is caught and recovered by trimming history
    - Empty LLM responses trigger a reminder (up to 3 times)
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: LLMClient,
        config: LoopConfig,
        logger: Logger,
    ):
        self.mcp_client = mcp_client
        self.llm_client = llm_client
        self.config = config
        self.logger = logger
        self.session = Session(config)
        self._mcp_tools: list[dict] = []
        self._all_tools: list[dict] = []
        self._orchestrator_tools: list[OrchestratorTool] = []
        self._task_board: Optional[TaskBoard] = None
        self._plan_executor: Optional[PlanExecutor] = None
        self._plan_generator: Optional[PlanGenerator] = None
        self._verifier: Optional[PlanVerifier] = None

    def run(self, task: str, plan_mode: bool = False) -> str:
        """Run a single task through the agentic loop.

        Args:
            task: The user's task description.
            plan_mode: If True, runs structured plan mode:
                Phase 1: Decompose into subtasks (task tools only)
                Phase 2: Generate YAML plan for each subtask
                No execution — plans are generated and verified only.
        """
        self._setup()
        if plan_mode:
            result = self._run_plan_mode(task)
        else:
            self.session.add_user_message(task)
            result = self._inner_loop()
        self.logger.event("loop_end", self.session.get_usage_summary())
        return result

    def run_interactive(self) -> None:
        """Interactive REPL mode. Reads tasks from stdin.

        Special commands:
          /plan <task>  — run task in plan mode (decompose → generate YAML plans → execute)
          exit          — quit the loop
        """
        self._setup()
        print(
            "AgentSPEX Agentic Loop (type '/exit' to quit, '/plan <task>' for plan mode)"
        )

        while True:
            print()
            self.logger.rule()
            try:
                user_input = pt_prompt(
                    "> ", lexer=_SlashCommandLexer(), style=_PROMPT_STYLE
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if user_input.lower() in ("/exit", "/quit", "/q"):
                break
            if not user_input:
                continue

            self.logger.rule()
            print()

            if user_input.startswith("/plan "):
                task = user_input[len("/plan ") :].strip()
                if not task:
                    print("Usage: /plan <task description>")
                    continue
                self.logger.event("user_message", {"content": user_input})
                result = self._run_plan_mode(task)
                self.logger.event("loop_end", self.session.get_usage_summary())
                continue

            self.session.add_user_message(user_input)
            self._inner_loop()

        self.logger.event("loop_end", self.session.get_usage_summary())

    def _setup(self) -> None:
        """Initialize MCP tools, orchestrator tools, plan generator, and system prompt."""
        self._mcp_tools = self.mcp_client.list_tools()

        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Each run gets a fresh task board to avoid stale tasks from previous
        # runs accumulating. Timestamped filename also serves as a run log.
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_board_path = output_dir / f"task_board_{run_ts}.json"
        self._task_board = TaskBoard(persist_path=task_board_path)

        # Task management tools
        self._orchestrator_tools = build_task_management_tools(
            self._task_board, self._get_user_input
        )

        # Plan generation + verification tools
        mcp_tool_names = [t["function"]["name"] for t in self._mcp_tools]
        workflow_guide = self._load_workflow_language_guide()
        self._tool_briefs = self._load_tool_briefs()
        self._plan_generator = PlanGenerator(
            llm_client=self.llm_client,
            model=self.config.plan_generator_model,
            plans_dir=output_dir / "plans",
            available_tool_names=mcp_tool_names,
            workflow_language_guide=workflow_guide,
            temperature=self.config.temperature,
            tool_briefs=self._tool_briefs,
            executor_model=self.config.plan_executor_model,
        )
        self._verifier = PlanVerifier(
            available_tool_names=set(mcp_tool_names),
        )
        plan_tools = build_plan_tools(
            self._task_board,
            self._plan_generator,
            self._verifier,
            self._get_user_input,
        )
        self._orchestrator_tools.extend(plan_tools)

        # Plan execution tools (for reactive mode; plan mode uses direct calls)
        self._plan_executor = PlanExecutor(
            mcp_client=self.mcp_client,
            llm_client=self.llm_client,
            logger=self.logger,
            output_dir=self.config.output_dir,
        )
        execution_tools = build_execution_tools(
            self._task_board,
            self._plan_executor,
            self._summarize_execution_result,
        )
        self._orchestrator_tools.extend(execution_tools)

        self._all_tools = tools_to_openai_format(
            self._orchestrator_tools, self._mcp_tools
        )

        all_tool_names = [t["function"]["name"] for t in self._all_tools]
        system_prompt = get_orchestrator_system_prompt(
            all_tool_names, self._task_board.get_summary()
        )
        self.session.add_system_message(system_prompt)

        self.logger.event(
            "loop_start",
            {
                "model": self.config.model,
                "plan_generator_model": self.config.plan_generator_model,
                "tools_count": len(all_tool_names),
                "orchestrator_tools": [t.name for t in self._orchestrator_tools],
                "mcp_tools_count": len(self._mcp_tools),
                "max_turns": self.config.max_turns,
            },
        )

    def _get_user_input(
        self, question: str, options: Optional[list[str]] = None
    ) -> str:
        """Prompt the user for input (used by the ask_user tool)."""
        print(f"\n[Agent]: {question}")
        if options:
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")
            print(f"  {len(options) + 1}. Other (type your answer)")

        answer = input("Your answer: ").strip()

        if options and answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(options):
                answer = options[idx]

        return answer or "(no answer provided)"

    def _run_plan_mode(self, task: str) -> str:
        """Structured plan mode: decompose → per-task plan-execute cycle → synthesize.

        Phase 1 — Decomposition:
            LLM decomposes the task using only task management tools.
            Tools available: task_create, task_update, task_list, ask_user.
            MCP tools are hidden to force decomposition behavior.

        Phase 2 — Interleaved plan-execute cycle (per task):
            For each subtask on the board:
            a) Build context_summary from previously completed tasks' results
            b) LLM generates a YAML plan (via generate_plan tool)
            c) Plan is auto-verified and shown to user for approval
            d) If approved, plan is executed in isolation (PlanExecutor,
               fresh Interpreter — orchestrator context is NOT involved)
            e) Raw execution result is summarized via _on_task_executed hook
            f) Compact result_summary stored on task board
            g) One status line injected into orchestrator conversation

            Context isolation: the orchestrator conversation never sees raw
            execution output. Only the task board carries results between tasks.
            The plan generator gets prior results via context_summary parameter.

        Phase 3 — Synthesis:
            LLM sees task board with full result_summaries and produces
            a final synthesized response.

        Hook points (methods prefixed with _on_*) provide extensibility:
            _on_decomposition_complete: after Phase 1, before plan-execute cycle
            _on_plan_generated: after a plan is generated and approved
            _on_task_executed: after a plan runs — default: cheap LLM summarization
            _on_all_tasks_complete: after all tasks, before synthesis
        These can be overridden in subclasses or replaced with LLM-driven
        logic in future versions.
        """
        self.logger.event("plan_mode_start", {"task": task[:500]})

        # ── Phase 1: Decomposition (task tools only) ───────────────────
        task_tool_names = {"task_create", "task_update", "task_list", "ask_user"}
        task_only_orch = [
            t for t in self._orchestrator_tools if t.name in task_tool_names
        ]
        task_only_openai = tools_to_openai_format(task_only_orch, [])

        decompose_msg = (
            f"{task}\n\n"
            "---\n"
            "Break this request down into subtasks using task_create. "
            "Create 2-5 subtasks that cover distinct phases of the work. "
            "Each subtask should be a meaningful unit of work. "
            "After creating all subtasks, summarize your decomposition plan."
        )
        self.session.add_user_message(decompose_msg)
        self.logger.event("plan_mode_phase", {"phase": "decomposition"})
        self._inner_loop_with_tools(task_only_openai, task_only_orch)

        tasks = self._task_board.list_tasks()
        if not tasks:
            return "Plan mode: No subtasks were created during decomposition."

        # Hook: post-decomposition — can reorder, filter, or annotate tasks
        tasks = self._on_decomposition_complete(tasks)

        # ── Phase 2: Interleaved plan-execute cycle ────────────────────
        self.logger.event("plan_mode_phase", {"phase": "plan_execute_cycle"})

        # Tools for the plan generation sub-phase
        plan_tool_names = {"generate_plan", "task_update", "task_list"}
        plan_only_orch = [
            t for t in self._orchestrator_tools if t.name in plan_tool_names
        ]
        plan_only_openai = tools_to_openai_format(plan_only_orch, [])

        executed_count = 0
        for task_item in tasks:
            # a) Build context_summary from previously completed tasks
            context_summary = self._task_board.get_results_summary()
            if context_summary == "No completed tasks with results yet.":
                context_summary = None

            # b) Generate plan via LLM (generate_plan tool includes verify + approve)
            self._task_board.update_task(task_item.id, status="in_progress")

            plan_msg_parts = [
                f"Generate a YAML workflow plan for task [{task_item.id}]: "
                f"{task_item.description}\n\n"
                "Call generate_plan with:\n"
                "- task_description: Expand the task into a detailed, actionable "
                "description with specific objectives and expected output format.\n"
                "- recommended_tools: Select the MCP tools this task needs from "
                "the available tools you know about.\n"
                "- hints: Include parameter constraints (e.g., 'limit paper_search "
                "to 10 results') and structural preferences (step types, iteration "
                "strategy, etc.)."
            ]
            if context_summary:
                plan_msg_parts.append(
                    f"\n- context_summary: Pass the following context from "
                    f"previously completed tasks:\n{context_summary}"
                )
            plan_msg_parts.append(
                "\n\nIMPORTANT: Only call generate_plan. Do NOT call execute_plan — "
                "execution happens automatically after the plan is approved. "
                "After calling generate_plan, stop and wait."
            )

            self.session.add_user_message("".join(plan_msg_parts))
            self.logger.event(
                "plan_mode_generating",
                {
                    "task_id": task_item.id,
                    "description": task_item.description,
                    "has_prior_context": context_summary is not None,
                },
            )
            self._inner_loop_with_tools(plan_only_openai, plan_only_orch)

            # c) Check if the plan was generated and approved
            task_item = self._task_board.get_task(task_item.id)
            if not task_item.plan_file or not task_item.plan_verified:
                self.logger.event(
                    "plan_mode_skipped",
                    {
                        "task_id": task_item.id,
                        "reason": "plan not approved or generation failed",
                    },
                )
                self.session.add_user_message(
                    f"Plan for {task_item.id} was not approved. Moving to next task."
                )
                continue

            # Hook: post-plan-generation — can inspect/modify plan before execution
            self._on_plan_generated(task_item)

            # d) Execute the approved plan in isolation
            #    This runs in a fresh Interpreter with its own conversation context.
            #    The orchestrator's conversation is completely uninvolved.
            self.logger.event(
                "plan_mode_executing",
                {
                    "task_id": task_item.id,
                    "plan_file": task_item.plan_file,
                },
            )
            plan_path = Path(task_item.plan_file)
            try:
                execution_result = self._plan_executor.execute(
                    plan_path=plan_path,
                    model=self.config.plan_executor_model,
                )
            except Exception as e:
                self._task_board.update_task(
                    task_item.id,
                    status="failed",
                    error=str(e),
                )
                self.session.add_user_message(
                    f"Execution of {task_item.id} failed: {e}"
                )
                continue

            # e) Write raw output to file ALWAYS (before health check).
            #    Persists raw data for inter-task passing and debugging.
            output_file_path = None
            try:
                plan_name = execution_result.plan_yaml.get("name", task_item.id)
                output_dir = Path(self.config.output_dir) / "plan_outputs" / plan_name
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_dir / "final-output.txt"
                output_file.write_text(execution_result.output, encoding="utf-8")
                # Also write to sandbox so subsequent plans can read via fs_read
                sandbox_path = f"outputs/{plan_name}/final-output.txt"
                try:
                    self.mcp_client.invoke(
                        "fs_write",
                        {
                            "path": sandbox_path,
                            "content": execution_result.output,
                        },
                    )
                    output_file_path = sandbox_path
                except Exception:
                    output_file_path = str(output_file)
            except Exception as e:
                self.logger.event(
                    "warning",
                    {
                        "message": f"Failed to write raw output file: {e}",
                    },
                )

            # f) Hook: post-execution — assess health and summarize.
            #    The cheap model's assessment is ADVISORY — the orchestrator
            #    (stronger model) makes the final decision on task status.
            result_summary = self._on_task_executed(task_item, execution_result)

            # g) Store result on task board. Health check is advisory:
            #    mark as completed with the summary (which may contain warnings).
            #    The orchestrator sees the assessment and can decide in synthesis.
            self._task_board.update_task(
                task_item.id,
                status="completed",
                result_summary=result_summary,
                output_file=output_file_path,
            )
            executed_count += 1

            # h) Inject status into orchestrator conversation.
            #    Include health warnings if the assessment flagged issues,
            #    so the orchestrator (stronger model) can make the final judgment.
            has_warnings = result_summary.startswith("EXECUTION FAILED")
            if has_warnings:
                self.session.add_user_message(
                    f"Task {task_item.id} executed but the health assessment flagged "
                    f"potential issues. Review the summary on the task board and decide "
                    f"whether to proceed or adjust subsequent tasks.\n"
                    f"Output file: {output_file_path or 'not available'}"
                )
            else:
                self.session.add_user_message(
                    f"Task {task_item.id} executed successfully. "
                    f"Result summary stored on task board."
                )
            self.logger.event(
                "plan_mode_task_completed",
                {
                    "task_id": task_item.id,
                    "summary_length": len(result_summary),
                },
            )

        # Hook: pre-synthesis — can augment or modify what the synthesizer sees
        self._on_all_tasks_complete()

        # ── Phase 3: Synthesis ─────────────────────────────────────────
        self.logger.event("plan_mode_phase", {"phase": "synthesis"})

        results_summary = self._task_board.get_results_summary()
        board_summary = self._task_board.get_summary()

        synthesis_msg = (
            "All tasks have been processed. Here is the final state:\n\n"
            f"{board_summary}\n\n"
            f"{results_summary}\n\n"
            "Please synthesize a final response that combines the results "
            "from all completed tasks into a coherent answer to the "
            "original request."
        )
        self.session.add_user_message(synthesis_msg)

        # Full tool set for synthesis — the LLM might need to read files,
        # do additional reactive work, etc.
        final_response = self._inner_loop()

        plans_dir = Path(self.config.output_dir) / "plans"
        plan_files = list(plans_dir.glob("*.yaml")) if plans_dir.exists() else []

        self.logger.event(
            "plan_mode_end",
            {
                "tasks_count": len(tasks),
                "executed_count": executed_count,
                "plans_count": len(plan_files),
            },
        )

        return final_response

    # ── Hook methods ─────────────────────────────────────────────────
    # These provide extensibility points in the plan-execute cycle.
    # Override in subclasses or replace with LLM-driven logic in
    # future versions. Each hook receives the relevant state and can
    # modify it before the next phase.

    def _on_decomposition_complete(self, tasks: list) -> list:
        """Hook: called after Phase 1 decomposition, before plan-execute cycle.

        Can reorder, filter, or annotate the task list. Default: pass through.

        Args:
            tasks: List of Task objects created during decomposition.

        Returns:
            Potentially modified list of tasks to process.
        """
        return tasks

    def _on_plan_generated(self, task_item) -> None:
        """Hook: called after a plan is generated and approved, before execution.

        Can inspect or modify the plan file on disk. Default: no-op.

        Args:
            task_item: The Task object with plan_file and plan_verified set.
        """
        pass

    def _on_task_executed(self, task_item, execution_result) -> str:
        """Hook: called after plan execution completes, before storing result.

        Uses an LLM-based health assessment to determine whether the execution
        succeeded AND produces a compact summary in a single LLM call. The
        assessor checks whether the output matches the task objective and
        the plan's expected behavior, catching subtle failures like
        hallucinated outputs from derailed intermediate steps.

        Args:
            task_item: The Task object that was executed.
            execution_result: ExecutionResult from PlanExecutor.execute().

        Returns:
            Compact result summary string to store on the task board.
            Prefixed with "EXECUTION FAILED" if the health check fails.
        """
        return self._assess_and_summarize_execution(execution_result, task_item)

    def _assess_and_summarize_execution(self, execution_result, task_item) -> str:
        """Assess execution health and summarize in a single LLM call.

        Combines health assessment and summarization into one cheap LLM call.
        The assessor receives the task objective, the plan's last step
        instruction, the raw output, and any errors — and returns a JSON
        object with both a success assessment and a compact summary.

        Fast-fails without an LLM call if execution had hard errors.
        """
        # Fast-fail: if execution had errors in every step, no LLM needed
        if execution_result.errors and execution_result.steps_completed == 0:
            error_detail = "; ".join(execution_result.errors[:3])
            return (
                f"EXECUTION FAILED - No steps completed successfully.\n"
                f"Errors: {error_detail}"
            )

        raw_output = execution_result.output

        # Short, error-free results can be returned directly
        if len(raw_output) <= 500 and execution_result.success:
            return raw_output

        # Extract the last step's instruction for comparison
        last_step_instruction = ""
        workflow = execution_result.plan_yaml.get("workflow", [])
        if workflow:
            last_step = workflow[-1]
            if isinstance(last_step, dict):
                for step_type, body in last_step.items():
                    if isinstance(body, dict):
                        last_step_instruction = body.get("instruction", "")[:500]
                        break

        # Cap input to avoid blowing context
        input_text = raw_output[:10000]
        if len(raw_output) > 10000:
            input_text += (
                f"\n\n... [truncated: {len(raw_output) - 10000:,} chars omitted]"
            )

        # Build error context if any
        error_context = ""
        if execution_result.errors:
            error_context = (
                f"\n\nIntermediate errors during execution ({len(execution_result.errors)}):\n"
                + "\n".join(f"- {e}" for e in execution_result.errors[:5])
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an execution health assessor and summarizer. Given a task's "
                    "objective, its plan's last step instruction, and the actual execution "
                    "output, you must:\n"
                    "1. Assess whether the execution succeeded — did the output actually "
                    "accomplish what the task objective asked for?\n"
                    "2. Check for signs of failure: output that asks for user input, "
                    "meta-conversations, hallucinated content not grounded in real tool "
                    "results, or content that doesn't match the expected format.\n"
                    "3. Consider whether intermediate errors may have corrupted the final "
                    "output — even if the final output looks plausible, it may be "
                    "hallucinated if earlier steps failed.\n"
                    "4. Produce a compact summary of what was actually accomplished.\n\n"
                    "Respond with ONLY a JSON object (no markdown fences):\n"
                    '{"succeeded": true/false, "confidence": 0.0-1.0, '
                    '"issues": ["list of concerns if any"], '
                    '"summary": "compact summary of what was accomplished (max 500 words)"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Task Objective\n{task_item.description}\n\n"
                    f"## Last Step Instruction\n{last_step_instruction}\n\n"
                    f"## Execution Stats\n"
                    f"Steps completed: {execution_result.steps_completed}/{execution_result.steps_total}\n"
                    f"Hard errors: {len(execution_result.errors)}\n"
                    f"{error_context}\n\n"
                    f"## Execution Output\n{input_text}"
                ),
            },
        ]

        try:
            response = self.llm_client.completion(
                model=self.config.plan_generator_model,
                messages=messages,
                tools=None,
                temperature=0.1,
            )
            response_text = response.choices[0].message.content or ""

            # Parse JSON response
            import json

            # Strip markdown fences if the LLM wraps in ```json ... ```
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]  # remove first line
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            assessment = json.loads(cleaned)
            succeeded = assessment.get("succeeded", True)
            confidence = assessment.get("confidence", 1.0)
            issues = assessment.get("issues", [])
            summary = assessment.get("summary", "")

            self.logger.event(
                "execution_health_assessment",
                {
                    "task_id": task_item.id,
                    "succeeded": succeeded,
                    "confidence": confidence,
                    "issues": issues[:5],
                    "steps_completed": execution_result.steps_completed,
                    "steps_total": execution_result.steps_total,
                    "errors": len(execution_result.errors),
                },
            )

            if not succeeded or confidence < 0.5:
                issues_text = (
                    "\n".join(f"- {issue}" for issue in issues)
                    if issues
                    else "- Assessment indicated failure"
                )
                return (
                    f"EXECUTION FAILED - Health assessment (confidence: {confidence:.2f}):\n"
                    f"{issues_text}\n\n"
                    f"Summary of what was attempted:\n{summary}"
                )

            return summary

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # JSON parsing failed — fall back to basic summarization
            self.logger.event(
                "warning",
                {
                    "message": f"Health assessment JSON parse failed: {e}. Falling back to basic summary.",
                },
            )
            return self._summarize_execution_result(raw_output, task_item.description)
        except Exception as e:
            self.logger.event(
                "warning",
                {
                    "message": f"Health assessment LLM call failed: {e}. Falling back to basic summary.",
                },
            )
            return self._summarize_execution_result(raw_output, task_item.description)

    def _on_all_tasks_complete(self) -> None:
        """Hook: called after all tasks are processed, before synthesis.

        Can augment the task board, write files, or prepare additional
        context for the synthesis phase. Default: no-op.
        """
        pass

    def _summarize_execution_result(
        self, raw_result: str, task_description: str
    ) -> str:
        """Summarize a raw plan execution result into a compact, structured form.

        Uses the plan generator model (cheap, e.g. gpt-5) to produce a
        summary that captures key outputs, findings, files created, and
        any information subsequent tasks might need. This mirrors the
        autocompact/agent-summary pattern from mature agentic harnesses:
        a separate cheap LLM call summarizes output at an execution boundary,
        so only compact context crosses into the orchestrator's awareness.

        If the raw result is already short enough (<= 500 chars), it is
        returned directly without an LLM call to save cost.

        Args:
            raw_result: Full text output from PlanExecutor.execute().
            task_description: Description of the task (for summarization context).

        Returns:
            Compact summary string (typically 200-500 words).
        """
        # Short results don't need summarization
        if len(raw_result) <= 500:
            return raw_result

        # Cap the input to avoid blowing the summarizer's context
        input_text = raw_result[:10000]
        if len(raw_result) > 10000:
            input_text += (
                f"\n\n... [truncated: {len(raw_result) - 10000:,} chars omitted]"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a concise summarizer for task execution results. "
                    "Given the task description and its execution output, produce "
                    "a structured summary that captures:\n"
                    "1. Key outputs and findings\n"
                    "2. Files created or modified (with paths if available)\n"
                    "3. Important decisions or data produced\n"
                    "4. Any information that subsequent tasks might need\n\n"
                    "Be concise but comprehensive. Max 500 words. "
                    "Use bullet points for clarity."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task: {task_description}\n\n" f"Execution output:\n{input_text}"
                ),
            },
        ]

        try:
            response = self.llm_client.completion(
                model=self.config.plan_generator_model,
                messages=messages,
                tools=None,
                temperature=0.1,
            )
            summary = response.choices[0].message.content or ""
            if summary:
                return summary
        except Exception as e:
            self.logger.event(
                "warning",
                {
                    "message": f"Summarization LLM call failed: {e}. Using truncation.",
                },
            )

        # Fallback: truncate if LLM call fails
        return raw_result[:2000]

    def _inner_loop_with_tools(
        self,
        tools_openai: list[dict],
        orchestrator_tools: list[OrchestratorTool],
    ) -> str:
        """Run the inner loop with a custom tool set.

        Temporarily swaps tool lists, runs _inner_loop, then restores.
        Used by plan mode phases to restrict available tools.
        """
        saved_all, saved_orch = self._all_tools, self._orchestrator_tools
        try:
            self._all_tools = tools_openai
            self._orchestrator_tools = orchestrator_tools
            return self._inner_loop()
        finally:
            self._all_tools = saved_all
            self._orchestrator_tools = saved_orch

    def _inner_loop(self) -> str:
        """The core while(True) tool-calling loop."""
        context_limit = get_model_context_limit(self.config.model)
        wrapping_up = False
        empty_response_count = 0

        while self.session.turn_count < self.config.max_turns:
            self.session.turn_count += 1

            # ── Proactive context monitoring ──────────────────────────────
            if not wrapping_up:
                current_tokens = count_message_tokens(
                    self.session.messages, self.config.model
                )
                if current_tokens > 0:
                    utilization = current_tokens / context_limit
                    self.logger.event(
                        "agent_iteration",
                        {
                            "number": self.session.turn_count,
                            "max": self.config.max_turns,
                            "tokens": current_tokens,
                            "limit": context_limit,
                            "utilization": round(utilization * 100, 1),
                        },
                    )
                    if utilization >= _CONTEXT_WRAP_UP_THRESHOLD:
                        self.session.add_user_message(
                            "You are approaching the context limit. "
                            "Please wrap up your current work and provide a final "
                            "response now. Do not start any new tool calls."
                        )
                        self.logger.event(
                            "warning",
                            {
                                "message": (
                                    f"Context at {utilization:.0%} "
                                    f"({current_tokens:,}/{context_limit:,} tokens). "
                                    "Wrap-up message injected."
                                ),
                            },
                        )
                        wrapping_up = True

            # ── Call LLM ─────────────────────────────────────────────────
            try:
                response = self.llm_client.completion(
                    model=self.config.model,
                    messages=self.session.messages,
                    tools=self._all_tools if self._all_tools else None,
                    temperature=self.config.temperature,
                    **self.config.model_kwargs,
                )
            except litellm.NotFoundError as e:
                self.logger.event(
                    "error",
                    {
                        "message": f"Model not found: '{self.config.model}'. Check the model name and try again.\n{e}",
                    },
                )
                return f"Error: model '{self.config.model}' was not found. Please restart with a valid model name."
            except litellm.AuthenticationError as e:
                self.logger.event(
                    "error",
                    {
                        "message": f"Authentication failed for model '{self.config.model}'. Check your API key.\n{e}",
                    },
                )
                return f"Error: authentication failed for '{self.config.model}'. Check your API key."
            except litellm.ContextWindowExceededError:
                self.logger.event(
                    "warning",
                    {
                        "message": "Context window exceeded — trimming conversation history",
                        "turn": self.session.turn_count,
                    },
                )
                self._trim_conversation_history()
                try:
                    response = self.llm_client.completion(
                        model=self.config.model,
                        messages=self.session.messages,
                        tools=self._all_tools if self._all_tools else None,
                        temperature=self.config.temperature,
                        **self.config.model_kwargs,
                    )
                except litellm.ContextWindowExceededError:
                    return "Error: Context window exceeded even after trimming."

            # ── Parse response ────────────────────────────────────────────
            message = response.choices[0].message
            text = message.content or ""
            tool_calls = message.tool_calls or []

            usage = extract_token_usage(response.usage)
            self.session.track_usage(usage)

            # ── No tool calls → termination signal ───────────────────────
            if not tool_calls:
                if not text:
                    # Empty response — nudge up to 3 times
                    empty_response_count += 1
                    if empty_response_count >= 3:
                        return "Agent produced no response after 3 reminders."
                    self.session.add_assistant_message("")
                    self.session.add_user_message(
                        "Your last response was empty. "
                        "Please provide your final answer or continue with tool calls."
                    )
                    continue

                self.session.add_assistant_message(text)
                self.logger.event(
                    "loop_turn",
                    {
                        "turn": self.session.turn_count,
                        "tools_called": [],
                        "tokens_this_turn": usage.get("total_tokens", 0),
                        "tokens_total": self.session.total_tokens,
                    },
                )
                self.logger.event("llm_response", {"content": text})
                return text

            # ── Add assistant message with tool calls ─────────────────────
            self.session.add_assistant_message(
                text, tool_calls=_serialize_tool_calls(tool_calls)
            )
            if text:
                self.logger.event("llm_response", {"content": text})

            # ── Execute tool calls ────────────────────────────────────────
            tool_results = []
            tool_names_called = []

            for tc in tool_calls:
                name = tc.function.name
                tool_names_called.append(name)
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}

                self.logger.event(
                    "tool_call_start",
                    {
                        "turn": self.session.turn_count,
                        "name": name,
                        "args": args,
                    },
                )

                # Route: orchestrator tool (in-process) or MCP (sandbox)
                orch_tool = next(
                    (t for t in self._orchestrator_tools if t.name == name), None
                )
                try:
                    if orch_tool:
                        result_str = orch_tool.handler(args)
                    else:
                        raw = self.mcp_client.invoke(name, args)
                        result_str = _format_mcp_result(name, raw)
                except Exception as e:
                    result_str = json.dumps({"error": str(e)})

                # Truncate oversized results before appending to history
                result_str = _truncate_tool_result(
                    result_str, self.config.max_tool_result_chars
                )

                tool_results.append(
                    {
                        "tool_call_id": tc.id,
                        "role": "tool",
                        "content": result_str,
                    }
                )

                self.logger.event(
                    "tool_call_end",
                    {
                        "turn": self.session.turn_count,
                        "name": name,
                        "result": result_str[:2000],
                    },
                )

            self.session.add_tool_results(tool_results)

            self.logger.event(
                "loop_turn",
                {
                    "turn": self.session.turn_count,
                    "tools_called": tool_names_called,
                    "tokens_this_turn": usage.get("total_tokens", 0),
                    "tokens_total": self.session.total_tokens,
                },
            )

        return "Max turns reached without completion."

    def _trim_conversation_history(self) -> None:
        """Aggressively truncate old tool results to recover context space.

        Keeps the system prompt and recent messages intact; shrinks tool
        result content in older turns to 500 chars.
        """
        messages = self.session.messages
        if len(messages) <= 3:
            return

        keep_recent = 6
        trim_limit = 500

        for i, msg in enumerate(messages):
            if i >= len(messages) - keep_recent:
                break
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if len(content) > trim_limit:
                    msg["content"] = (
                        content[:trim_limit]
                        + f"\n... [TRIMMED: {len(content) - trim_limit:,} chars removed]"
                    )

    @staticmethod
    def _load_tool_briefs() -> dict:
        """Load tool briefs from tool_briefs.yaml for context-aware plan generation.

        Returns a dict mapping tool name to its brief data, e.g.:
            {"paper_search": {"brief": "...", "params": {...}}, ...}
        """
        briefs_path = Path(__file__).parent / "tool_briefs.yaml"
        if briefs_path.exists():
            import yaml

            data = yaml.safe_load(briefs_path.read_text(encoding="utf-8"))
            tools = data.get("tools") or {}
            # YAML uses dict keyed by tool name: {paper_search: {brief: ..., params: ...}}
            if isinstance(tools, dict):
                return tools
            # Fallback for list format: [{name: ..., brief: ..., params: ...}, ...]
            if isinstance(tools, list):
                return {t["name"]: t for t in tools if "name" in t}
        return {}

    @staticmethod
    def _load_workflow_language_guide() -> str:
        """Load the agent-friendly workflow language guide from dev_docs/."""
        guide_path = (
            Path(__file__).parent
            / "dev_docs"
            / "agent_friendly_workflow_language_guide.md"
        )
        if guide_path.exists():
            return guide_path.read_text(encoding="utf-8")
        # Minimal fallback if the guide file is missing
        return (
            "AgentSPEX YAML workflows require top-level keys: name, goal, workflow.\n"
            "Step types: step, task, for_each, if, while, switch, call, parallel, "
            "gather, set_variable, increment, input, return.\n"
            "Use {{variable}} for template expansion. Use save_as to capture outputs."
        )
