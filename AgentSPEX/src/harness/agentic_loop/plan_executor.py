"""Plan execution bridge: runs verified YAML plans through the AgentSPEX Interpreter.

PlanExecutor is a lightweight wrapper around the existing workflow engine
(Interpreter + LLMExecutor). It handles context/args setup and the step
iteration loop, without the checkpoint, tracing, workspace backup, and
reproducibility infrastructure of YAMLAgent.run().

Why not call YAMLAgent.run() directly?
1. YAMLAgent.run() calls mcp_client.enable_tracing(), which mutates the
   shared MCP client's tracing state — a side effect we don't want.
2. ~200 lines of checkpoint/workspace/reproducibility code that creates
   unnecessary files and overhead for plan-mediated execution.
3. Model override precedence differs: the agentic loop's explicit override
   should take priority over the plan's config.model, but with_yaml_config()
   gives YAML config priority over the base EffectiveArgs model.
4. Error handling: PlanExecutor returns errors as strings to the orchestrator;
   YAMLAgent raises exceptions that would kill the agentic loop.

All actual step execution is delegated to the existing Interpreter,
LLMExecutor, and step handler mixins. The components reused here are:
- Interpreter (src/harness/execution/interpreter.py) — step dispatch
- YAMLTaskParser (src/harness/parsing/yaml_parser.py) — YAML loading
- EffectiveArgs (src/harness/types/config.py) — config merging
- LLMExecutor (src/harness/execution/llm_executor.py) — multi-turn tool calling
- EffectiveToolConfig (src/harness/tools/filtering.py) — tool filtering
- ensure_conversation_history (src/harness/execution/conversation.py)
- load_submodule_tools_for_yaml (src/harness/submodules/loader.py)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from harness.execution.conversation import ensure_conversation_history
from harness.execution.interpreter import Interpreter
from harness.llms.client import LLMClient
from harness.parsing.yaml_parser import YAMLTaskParser
from harness.submodules import load_submodule_tools_for_yaml
from harness.types.config import EffectiveArgs
from mcp_client.client import MCPClient
from mcp_client.logger import Logger


@dataclass
class ExecutionResult:
    """Structured result from plan execution.

    Provides both the output text and metadata about execution health,
    enabling the orchestrator to detect failures and make informed decisions
    about whether to proceed with dependent tasks.
    """

    output: str  # Final output (context["prev_output"])
    success: bool  # True if all steps completed without exceptions
    steps_completed: int  # Number of steps that actually ran
    steps_total: int  # Total steps in the workflow
    errors: list[str] = field(default_factory=list)  # Error messages from failed steps
    plan_yaml: dict = field(
        default_factory=dict
    )  # Parsed plan data (for health assessment)
    tokens_used: int = 0  # Total tokens consumed during execution
    cost: float = 0.0  # Total cost of LLM calls during execution


class PlanExecutor:
    """Bridge between the agentic loop and the AgentSPEX workflow engine.

    Given a verified YAML plan file, loads it, creates a fresh Interpreter,
    and executes all workflow steps. Returns the final output string to the
    orchestrator for synthesis.

    The Interpreter handles all step types (task, step, for_each, if, while,
    switch, call, parallel, gather, set_variable, increment, input, return)
    and manages its own conversation history and tool calling within each step.

    Shares the same MCPClient and LLMClient as the agentic loop to avoid
    duplicate connections and ensure sandbox state is consistent.
    A fresh Interpreter is created per execution to avoid state leakage
    between plan runs.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        llm_client: LLMClient,
        logger: Logger,
        output_dir: str,
    ):
        """Initialize the plan executor.

        Args:
            mcp_client: Shared MCP client (same instance as the agentic loop
                uses for its own tool calls).
            llm_client: Shared LLM client (same instance as the agentic loop).
            logger: Logger for execution events (plan_execution_start/end/error).
            output_dir: Base output directory. Plan outputs go to
                {output_dir}/plan_outputs/{task_name}/.
        """
        self.mcp_client = mcp_client
        self.llm_client = llm_client
        self.logger = logger
        self.output_dir = output_dir
        self._parser = YAMLTaskParser()

    def execute(
        self,
        plan_path: Path,
        model: Optional[str] = None,
    ) -> ExecutionResult:
        """Load and execute a YAML plan through the Interpreter.

        Args:
            plan_path: Path to the verified YAML plan file.
            model: Optional model override for execution. If provided,
                takes precedence over the plan's config.model. If not
                provided, the plan's config.model is used (or the
                EffectiveArgs default of gpt-4.1-mini).

        Returns:
            ExecutionResult with the output text, success flag, step
            counts, any errors, the parsed plan data (for health
            assessment), and token/cost usage.

        Raises:
            FileNotFoundError: If the plan file doesn't exist.
            ValueError: If the plan contains invalid YAML or is missing
                required fields (name, goal, workflow).
        """
        plan_path = Path(plan_path)

        # ── 1. Load and parse YAML ───────────────────────────────────────
        yaml_data = self._parser.load_task(str(plan_path))
        task_name = yaml_data["name"]
        goal = yaml_data["goal"]
        workflow = yaml_data["workflow"]
        yaml_config = yaml_data.get("config", {}) or {}

        # ── 2. Load submodules if declared in the plan ───────────────────
        submodule_tools, submodule_registry = load_submodule_tools_for_yaml(
            yaml_data, str(plan_path)
        )

        # ── 3. Build EffectiveArgs ───────────────────────────────────────
        # Precedence: explicit model override > plan's config.model > default
        #
        # EffectiveArgs.with_yaml_config() applies YAML config on top of base,
        # so we build base first, apply YAML config, then re-apply explicit
        # model if provided (since YAML config would have overridden it).
        base_args = EffectiveArgs(workflow_file=str(plan_path))
        effective_args = (
            base_args.with_yaml_config(yaml_config) if yaml_config else base_args
        )
        if model:
            # Re-create with explicit model on top of yaml-configured values
            effective_args = EffectiveArgs(
                model=model,
                api_base=effective_args.api_base,
                max_tokens_per_step=effective_args.max_tokens_per_step,
                max_tool_calls_per_step=effective_args.max_tool_calls_per_step,
                temperature=effective_args.temperature,
                model_kwargs=effective_args.model_kwargs,
                context_threshold=effective_args.context_threshold,
                workflow_file=str(plan_path),
            )

        # ── 4. Create fresh Interpreter with shared clients ──────────────
        # A fresh Interpreter per execution prevents state leakage between
        # plans (conversation history, tool call counts, etc.).
        # The usage_tracker is per-execution so we can report costs per plan.
        tools = self.mcp_client.list_tools()
        usage_tracker: Dict[str, Any] = {
            "prompt_tokens_total": 0,
            "completion_tokens_total": 0,
            "reasoning_tokens_total": 0,
            "cost_total": 0.0,
        }
        interpreter = Interpreter(
            mcp_client=self.mcp_client,
            tools=tools,
            llm_client=self.llm_client,
            usage_tracker=usage_tracker,
        )

        # ── 5. Set up context ────────────────────────────────────────────
        # This mirrors the context initialization in YAMLAgent.run(),
        # minus checkpoint-related fields and workspace backup paths.
        plan_output_dir = str(Path(self.output_dir) / "plan_outputs" / task_name)
        Path(plan_output_dir).mkdir(parents=True, exist_ok=True)
        sandbox_output_dir = f"outputs/{task_name}"

        context: Dict[str, Any] = {
            "task_name": task_name,
            "goal": goal,
            "task_output_dir": plan_output_dir,
            "sandbox_output_dir": sandbox_output_dir,
            "prev_output": "",
            # Submodule tools and registry for plans that use 'call' steps
            "submodule_tools": submodule_tools,
            "submodule_registry": submodule_registry,
            # Plan file paths (needed by submodule resolution)
            "workflow_file": str(plan_path),
            "workflow_dir": str(plan_path.resolve().parent),
            "workflow_root": str(plan_path.resolve().parent),
        }

        # Add parameters from YAML to context (available as {{param}} in templates)
        if "parameters" in yaml_data:
            context.update(yaml_data["parameters"])

        # Allow plan to override the default system prompt
        if yaml_data.get("system_prompt"):
            context["system_prompt"] = yaml_data["system_prompt"]

        # Propagate config keys to context (same set as YAMLAgent.run)
        # These control tool filtering, inline tools, and execution behavior
        _CONFIG_CONTEXT_KEYS = [
            "enabled_tools",
            "enabled_submodules",
            "expose_submodules_as_tools",
            "enable_inline_tool_calls",
            "inline_tool_calls_only",
            "allow_inline_tools_without_enable",
            "stop_on_return",
            "require_submodule_submit",
            "max_workflow_steps",
        ]
        for key in _CONFIG_CONTEXT_KEYS:
            if key in yaml_config:
                context[key] = yaml_config[key]
            elif key in yaml_data:
                context[key] = yaml_data[key]

        # Initialize conversation history (for stateful 'step' type steps)
        ensure_conversation_history(context, effective_args)

        # ── 6. Execute workflow steps ────────────────────────────────────
        self.logger.event(
            "plan_execution_start",
            {
                "plan": str(plan_path),
                "task_name": task_name,
                "model": effective_args.model,
                "steps": len(workflow),
            },
        )

        errors: list[str] = []
        steps_completed = 0
        max_workflow_steps = context.get("max_workflow_steps")

        for i, step_data in enumerate(workflow, 1):
            # Respect max_workflow_steps if set in the plan's config
            if max_workflow_steps and i > int(max_workflow_steps):
                self.logger.event(
                    "plan_execution_warning",
                    {
                        "plan": str(plan_path),
                        "message": f"Reached max_workflow_steps={max_workflow_steps}",
                    },
                )
                break

            try:
                output, _tokens = interpreter.execute_workflow_step(
                    step_data,
                    context,
                    i,
                    effective_args,
                    self.logger,
                    checkpoint_manager=None,  # No checkpointing for plan execution
                )
                context["prev_output"] = output
                steps_completed = i
            except Exception as e:
                # Capture errors as strings rather than propagating —
                # the orchestrator needs to see the error and decide what to do
                error_msg = f"Error in step {i}: {e}"
                errors.append(error_msg)
                self.logger.event(
                    "plan_execution_error",
                    {
                        "plan": str(plan_path),
                        "step": i,
                        "error": str(e),
                    },
                )
                context["prev_output"] = error_msg
                steps_completed = i

        # ── 7. Return structured result ──────────────────────────────────
        final_output = context.get("prev_output", "")

        total_tokens = (
            usage_tracker["prompt_tokens_total"]
            + usage_tracker["completion_tokens_total"]
        )
        self.logger.event(
            "plan_execution_end",
            {
                "plan": str(plan_path),
                "task_name": task_name,
                "total_tokens": total_tokens,
                "cost": usage_tracker["cost_total"],
                "steps_executed": steps_completed,
                "errors": len(errors),
            },
        )

        return ExecutionResult(
            output=final_output,
            success=len(errors) == 0,
            steps_completed=steps_completed,
            steps_total=len(workflow),
            errors=errors,
            plan_yaml=yaml_data,
            tokens_used=total_tokens,
            cost=usage_tracker["cost_total"],
        )
