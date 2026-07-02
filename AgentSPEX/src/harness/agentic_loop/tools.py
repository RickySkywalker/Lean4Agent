"""Orchestrator tool definitions: task management, plan generation, and dispatch."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .task_board import TaskBoard


@dataclass
class OrchestratorTool:
    """A local tool available to the orchestrator LLM.

    These run in-process (not via MCP) and are presented to the LLM
    alongside MCP tools in the same OpenAI function-calling format.
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[[dict[str, Any]], str]


def build_task_management_tools(
    task_board: TaskBoard,
    user_input_fn: Callable[[str, Optional[list[str]]], str],
) -> list[OrchestratorTool]:
    """Build task management and user interaction tools.

    Args:
        task_board: The TaskBoard instance for persistence.
        user_input_fn: Callback that prompts the user and returns their answer.
            Signature: (question, optional_options) -> answer_string
    """

    def handle_task_create(args: dict) -> str:
        task = task_board.create_task(
            description=args["description"],
            parent_id=args.get("parent_task_id"),
        )
        return f"Created {task.id}: {task.description}"

    def handle_task_update(args: dict) -> str:
        try:
            task = task_board.update_task(
                task_id=args["task_id"],
                status=args.get("status"),
                result_summary=args.get("result_summary"),
            )
            return f"Updated {task.id}: status={task.status.value}"
        except ValueError as e:
            return f"Error: {e}"

    def handle_task_list(args: dict) -> str:
        return task_board.get_summary()

    def handle_ask_user(args: dict) -> str:
        return user_input_fn(args["question"], args.get("options"))

    return [
        OrchestratorTool(
            name="task_create",
            description="Create a new task on the task board to track work.",
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What this task should accomplish",
                    },
                    "parent_task_id": {
                        "type": "string",
                        "description": "Parent task ID if this is a subtask",
                    },
                },
                "required": ["description"],
            },
            handler=handle_task_create,
        ),
        OrchestratorTool(
            name="task_update",
            description=(
                "Update a task's status or result. "
                "Set status to 'in_progress' before starting work, "
                "'completed' after finishing, or 'failed' on error."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "failed"],
                    },
                    "result_summary": {
                        "type": "string",
                        "description": "Brief summary of the result",
                    },
                },
                "required": ["task_id"],
            },
            handler=handle_task_update,
        ),
        OrchestratorTool(
            name="task_list",
            description="List all tasks and their current status.",
            parameters={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "failed"],
                        "description": "Optional: filter by status",
                    },
                },
            },
            handler=handle_task_list,
        ),
        OrchestratorTool(
            name="ask_user",
            description=(
                "Ask the user a question when you need clarification or a decision. "
                "Optionally provide multiple-choice options."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional multiple-choice options",
                    },
                },
                "required": ["question"],
            },
            handler=handle_ask_user,
        ),
    ]


def tools_to_openai_format(
    orchestrator_tools: list[OrchestratorTool],
    mcp_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge orchestrator and MCP tools into OpenAI function-calling format."""
    combined = []
    for tool in orchestrator_tools:
        combined.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
        )
    combined.extend(mcp_tools)
    return combined


def build_plan_tools(
    task_board: TaskBoard,
    plan_generator: Any,  # PlanGenerator (avoid circular import)
    verifier: Any,  # PlanVerifier
    user_input_fn: Callable[[str, Optional[list[str]]], str],
) -> list[OrchestratorTool]:
    """Build plan generation tool (with automatic verification + user approval).

    Args:
        task_board: TaskBoard for tracking plan_file on tasks.
        plan_generator: PlanGenerator instance.
        verifier: PlanVerifier instance.
        user_input_fn: Callback for asking user approval.
    """

    def handle_generate_plan(args: dict) -> str:
        task_id = args["task_id"]
        task = task_board.get_task(task_id)
        if not task:
            return f"Error: Task {task_id} not found on the task board."

        # 1. Generate — pass all orchestrator-provided context to the plan generator
        try:
            plan_path = plan_generator.generate(
                task_id=task_id,
                task_description=args["task_description"],
                context_summary=args.get("context_summary"),
                hints=args.get("hints"),
                recommended_tools=args.get("recommended_tools"),
            )
        except ValueError as e:
            return f"Error generating plan: {e}"

        task_board.update_task(task_id, plan_file=str(plan_path))

        # 2. Verify automatically
        result = verifier.verify(plan_path)
        task_board.update_task(task_id, plan_verified=result.is_valid)

        if not result.is_valid:
            return (
                f"Plan generated at {plan_path} but verification FAILED: "
                f"{result.summary()}"
            )

        # 3. Show full YAML to user and ask for approval
        yaml_content = Path(plan_path).read_text(encoding="utf-8")
        approval = user_input_fn(
            f"Plan generated and verified for {task_id}. Approve?\n\n"
            f"```yaml\n{yaml_content}\n```",
            ["Yes, approve", "No, reject"],
        )
        approved = approval.lower() in ("yes", "yes, approve", "y", "1")
        if approved:
            return (
                f"Plan generated, verified, and APPROVED.\n"
                f"Path: {plan_path}\n\n```yaml\n{yaml_content}\n```"
            )
        else:
            task_board.update_task(task_id, plan_verified=False)
            return f"Plan generated and verified, but REJECTED by user. Feedback: {approval}"

    return [
        OrchestratorTool(
            name="generate_plan",
            description=(
                "Generate a YAML workflow plan for a specific task. "
                "A separate plan generator model produces the YAML workflow "
                "based on the description, tools, and context you provide. "
                "The plan is automatically verified and presented to the user "
                "for approval. The task must already exist on the task board.\n\n"
                "Your job is to provide complete, actionable inputs:\n"
                "- task_description: Expand the task into a detailed, specific "
                "description with clear objectives and expected output format. "
                "The plan generator does NOT see your conversation — everything "
                "it needs must be in this description.\n"
                "- recommended_tools: Select the MCP tools this task needs "
                "based on your knowledge of what each tool does.\n"
                "- context_summary: Include relevant results from prior tasks.\n"
                "- hints: Structural preferences (e.g., 'use for_each to iterate', "
                "'use parallel for independent searches')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID of the task to generate a plan for (e.g. task_001)",
                    },
                    "task_description": {
                        "type": "string",
                        "description": (
                            "Detailed, actionable description of what the task should "
                            "accomplish. Include: (1) specific objectives, (2) the approach "
                            "to take, (3) expected output format. The plan generator does "
                            "not see your conversation history — provide all necessary "
                            "context here."
                        ),
                    },
                    "recommended_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "MCP tools the plan should use, selected from the available "
                            "tools based on your understanding of what each tool does and "
                            "what this task requires. For example: ['web_search', 'shell_run', "
                            "'fs_write'] for a research task, or ['paper_search', "
                            "'arxiv_fetch_abstract'] for academic paper retrieval."
                        ),
                    },
                    "context_summary": {
                        "type": "string",
                        "description": (
                            "Relevant context from prior completed tasks that this "
                            "task depends on or should build upon."
                        ),
                    },
                    "hints": {
                        "type": "string",
                        "description": (
                            "Structural hints and parameter constraints for the plan. "
                            "IMPORTANT: Always include search result limits (e.g., "
                            "'limit paper_search to 10 results', 'keep num_results <= 10'). "
                            "Also: preferred step types (e.g., 'use for_each to iterate'), "
                            "execution strategy (e.g., 'search first, then analyze'), "
                            "output format requirements."
                        ),
                    },
                },
                "required": ["task_id", "task_description"],
            },
            handler=handle_generate_plan,
        ),
    ]


def build_execution_tools(
    task_board: TaskBoard,
    plan_executor: Any,  # PlanExecutor (avoid circular import)
    summarize_fn: Any,  # Callable[[str, str], str] — summarizes raw result
) -> list[OrchestratorTool]:
    """Build plan execution tool for reactive/interactive mode.

    In plan mode (--plan_mode), execution is driven programmatically by
    _run_plan_mode() and does NOT use this tool. This tool exists for cases
    where the LLM generates a plan in reactive mode and wants to execute it.

    The execution result is summarized via summarize_fn before being returned,
    keeping the orchestrator's context compact. The full raw output stays
    inside the PlanExecutor's isolated scope.

    Args:
        task_board: TaskBoard for looking up plan paths and updating results.
        plan_executor: PlanExecutor instance for running YAML plans through
            the existing AgentSPEX Interpreter.
        summarize_fn: Callable(raw_result, task_description) -> compact summary.
            Typically AgenticLoop._summarize_execution_result, which uses a
            cheap LLM call to produce a structured summary.
    """

    def handle_execute_plan(args: dict) -> str:
        task_id = args["task_id"]
        task = task_board.get_task(task_id)
        if not task:
            return f"Error: Task {task_id} not found on the task board."

        # Guard: must have a generated and approved plan
        if not task.plan_file:
            return (
                f"Error: Task {task_id} has no plan file. "
                "Generate a plan with generate_plan first."
            )
        if not task.plan_verified:
            return (
                f"Error: Task {task_id} plan is not verified/approved. "
                "The plan must be generated and approved before execution."
            )

        plan_path = Path(task.plan_file)
        if not plan_path.exists():
            return f"Error: Plan file {task.plan_file} not found on disk."

        # Mark task as in_progress before execution
        task_board.update_task(task_id, status="in_progress")

        try:
            # Execute the plan in isolation (fresh Interpreter, no orchestrator context)
            execution_result = plan_executor.execute(
                plan_path=plan_path,
                model=args.get("model"),
            )

            # Summarize the raw result using a cheap LLM call —
            # only the compact summary enters the orchestrator's context,
            # not the full execution output (context isolation pattern)
            result_summary = summarize_fn(execution_result.output, task.description)

            status = "completed" if execution_result.success else "failed"
            task_board.update_task(
                task_id,
                status=status,
                result_summary=result_summary,
                error=(
                    "; ".join(execution_result.errors[:3])
                    if execution_result.errors
                    else None
                ),
            )

            status_line = "successfully" if execution_result.success else "with errors"
            error_line = (
                f"Errors: {'; '.join(execution_result.errors[:3])}\n"
                if execution_result.errors
                else ""
            )
            return (
                f"Plan executed {status_line} for {task_id}.\n"
                f"Steps: {execution_result.steps_completed}/{execution_result.steps_total}\n"
                f"{error_line}\n"
                f"Summary:\n{result_summary}"
            )
        except Exception as e:
            error_msg = str(e)
            task_board.update_task(
                task_id,
                status="failed",
                error=error_msg,
            )
            return f"Error executing plan for {task_id}: {error_msg}"

    return [
        OrchestratorTool(
            name="execute_plan",
            description=(
                "Execute an approved YAML workflow plan for a specific task. "
                "The task must have a generated and approved plan on the task board. "
                "The plan is executed through the AgentSPEX workflow engine "
                "in isolation (separate from this conversation's context). "
                "A compact summary of the result is returned. "
                "Use this after generate_plan has produced and the user has "
                "approved a plan."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": (
                            "ID of the task whose plan to execute (e.g. task_001). "
                            "The task must have plan_file set and plan_verified=true."
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Optional model override for plan execution. "
                            "If not provided, the plan's config.model is used."
                        ),
                    },
                },
                "required": ["task_id"],
            },
            handler=handle_execute_plan,
        ),
    ]


def dispatch_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    orchestrator_tools: list[OrchestratorTool],
    mcp_client: Any,
) -> str:
    """Route a tool call to orchestrator handler or MCP.

    Checks orchestrator tools first (local, fast). Falls back to MCP
    for sandbox tools.
    """
    for tool in orchestrator_tools:
        if tool.name == tool_name:
            return tool.handler(tool_args)
    # Not an orchestrator tool -> dispatch to MCP
    result = mcp_client.invoke(tool_name, tool_args)
    return (
        json.dumps(result, default=str)
        if isinstance(result, (dict, list))
        else str(result)
    )
