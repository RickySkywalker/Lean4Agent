"""YAML Agent - Main orchestrator for YAML workflow execution.

This module provides the AgentSPEX class which coordinates the execution
of YAML-defined workflows, handling:
- Workflow loading and parsing
- Submodule tool loading
- Checkpoint management for durable execution
- Step execution orchestration via Interpreter
- Trace recording and replay for debugging

Example:
    agent = AgentSPEX(mcp_url="http://localhost:8080")
    result = agent.run(args)
"""

from __future__ import annotations

import os
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Union

from dotenv import find_dotenv, load_dotenv

from mcp_client.client import MCPClient
from mcp_client.logger import Logger

from .checkpoints.checkpoint_manager import CheckpointManager
from .checkpoints.durable_execution import TraceWriter, iter_jsonl
from .execution.conversation import ensure_conversation_history
from .execution.interpreter import Interpreter
from .execution.llm_executor import ToolCallLimitExceeded
from .llms import LLMClient, LLMConfig
from .parsing.conditions import evaluate_condition as _evaluate_condition
from .parsing.templates import \
    expand_template_variables as _expand_template_variables
from .parsing.yaml_parser import YAMLTaskParser
from .submodules import SubmoduleFunctionSpec, load_submodule_tools_for_yaml
from .tools.filtering import EffectiveToolConfig
from .types.config import EffectiveArgs
from .types.context import CHECKPOINT_KIND, CHECKPOINT_SCHEMA_VERSION
from .types.serialization import get_tool_name, safe_json_dumps
from .utils.reproducibility import (create_reproducibility_snapshot,
                                    ensure_workflow_submodules_snapshot)

load_dotenv(find_dotenv(), override=True)


class AgentSPEX:
    """YAML-native Agent that executes YAML workflow definitions.

    This class is the main entry point for running YAML-defined workflows.
    It coordinates between the MCP client for tool execution, the LLM client
    for completions, and the Interpreter for step execution.

    Attributes:
        mcp_url: URL of the MCP server.
        llm_client: LLMClient for LLM completions (supports multiple providers via LiteLLM).
        mcp_client: MCP client for tool invocation.
        tools: List of available tool definitions.
        submodule_tools: List of submodule tool definitions.
        submodule_registry: Registry of submodule specifications.
        agent_interpreter: Interpreter for executing workflow steps.
        usage_tracker: Dict tracking token usage across the workflow.

    Example:
        agent = AgentSPEX(
            mcp_url="http://localhost:8080",
            tool_config_fp="tools.json",
        )
        result = agent.run(args)

        # With custom LLM configuration (e.g., local vLLM server)
        llm_config = LLMConfig(api_base="http://localhost:8000")
        agent = AgentSPEX(
            mcp_url="http://localhost:8080",
            llm_config=llm_config,
        )
    """

    # Step execution methods delegated to agent_interpreter
    _DELEGATED_METHODS: FrozenSet[str] = frozenset(
        {
            "execute_basic_step",
            "execute_task_step",
            "execute_for_each_step",
            "execute_conditional_step",
            "execute_parallel_step",
            "execute_while_step",
            "execute_switch_step",
            "execute_increment_step",
            "execute_set_variable_step",
            "execute_return_step",
            "execute_input_step",
            "execute_call_step",
            "execute_gather_step",
            "execute_workflow_step",
        }
    )

    def __init__(
        self,
        mcp_url: Optional[str] = None,
        tool_config_fp: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        llm_config: Optional[LLMConfig] = None,
        mcp_client: Optional["MCPClient"] = None,
    ) -> None:
        """Initialize the YAML Agent.

        Args:
            mcp_url: URL of the MCP server for tool execution.
            tool_config_fp: Optional path to tool configuration file.
            session_id: Optional MCP session ID for resuming sessions.
            llm_config: Optional LLM configuration for custom providers/endpoints.
            mcp_client: Optional pre-configured MCPClient instance. If provided,
                uses this instead of creating a new MCPClient from mcp_url.
        """
        self.mcp_url = mcp_url
        self.llm_client = LLMClient(llm_config)
        if mcp_client is not None:
            self.mcp_client = mcp_client
        else:
            self.mcp_client = MCPClient(
                url=mcp_url, tool_config_fp=tool_config_fp, session_id=session_id
            )

        # default writing text
        self.mcp_fs_write = self.mcp_client.make_mcp_tool_function(
            "fs_write", ["path", "content"]
        )
        # default reading text
        self.mcp_fs_read = self.mcp_client.make_mcp_tool_function(
            "fs_read", ["path", "max_bytes"]
        )

        self.yaml_parser = None
        self.tools = self.mcp_client.list_tools()
        self.submodule_tools: List[Dict[str, Any]] = []
        self.submodule_registry: Dict[str, SubmoduleFunctionSpec] = {}

        # Initialize tokenizer (will be set based on model)
        self.tokenizer = None
        self.usage_tracker = {
            "prompt_tokens_total": 0,
            "completion_tokens_total": 0,
            "reasoning_tokens_total": 0,
            "cost_total": 0.0,
            "tool_calls_total": 0,
        }
        self.agent_interpreter: Interpreter = Interpreter(
            self.mcp_client, self.tools, self.llm_client, self.usage_tracker
        )

    def _configure_tracing(
        self,
        trace_writer: Optional[TraceWriter] = None,
        replay_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Configure tracing state for the LLMExecutor.

        Args:
            trace_writer: TraceWriter for recording events
            replay_events: List of events for replay mode
        """
        llm_executor = self.agent_interpreter.llm_executor
        llm_executor._trace_writer = trace_writer
        if replay_events is not None:
            llm_executor._llm_replay_events = replay_events
            llm_executor._replay_index = 0

    # Utility methods for template expansion and condition evaluation
    @staticmethod
    def expand_template_variables(text: str, context: Dict[str, Any]) -> str:
        """Expand template variables in text using context values."""
        return _expand_template_variables(text, context)

    @staticmethod
    def evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate a condition string against context values."""
        return _evaluate_condition(condition, context)

    def __getattr__(self, name: str) -> Any:
        """Delegate step execution methods to agent_interpreter."""
        if name in self._DELEGATED_METHODS:
            return getattr(self.agent_interpreter, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def run(
        self,
        args: Union[EffectiveArgs, Any],
        external_logger: Optional[Logger] = None,
    ) -> str:
        """Run the YAML agent with a YAML workflow file.

        This is the main entry point for executing a workflow. It handles:
        - Loading and parsing the YAML workflow file
        - Setting up logging and output directories
        - Checkpoint management for resume support
        - Durable execution via tracing
        - Executing all workflow steps
        - Writing final output

        Args:
            args: Agent arguments containing at minimum:
                - workflow_file: Path to the YAML workflow file
                - model: LLM model to use
                Can be an argparse namespace or EffectiveArgs instance.
            external_logger: Optional external logger for direct host logging.
                If not provided, creates a sandbox logger.

        Returns:
            The final output from the workflow execution.

        Raises:
            RuntimeError: If OPENAI_API_KEY is not set.
            FileNotFoundError: If the workflow file doesn't exist.
        """
        # Load and parse YAML file
        self.yaml_parser = YAMLTaskParser()
        yaml_data = self.yaml_parser.load_task(args.workflow_file)
        submodule_tools, submodule_registry = load_submodule_tools_for_yaml(
            yaml_data, args.workflow_file
        )

        # Create effective args from CLI args + YAML config
        # This allows per-file model configuration
        yaml_config = yaml_data.get("config", {}) or {}
        if "model" not in yaml_config and "model_name" in yaml_config:
            yaml_config = dict(yaml_config)
            yaml_config["model"] = yaml_config.get("model_name")
        if isinstance(args, EffectiveArgs):
            # Already an EffectiveArgs, apply YAML config if present
            effective_args = args.with_yaml_config(yaml_config) if yaml_config else args
        else:
            # Convert from argparse namespace to EffectiveArgs
            base_args = EffectiveArgs.from_args(args)
            effective_args = (
                base_args.with_yaml_config(yaml_config) if yaml_config else base_args
            )

        task_name = yaml_data["name"]
        goal = yaml_data["goal"]
        workflow = yaml_data["workflow"]

        # Set up logging and output directory
        # sandbox_output_dir: path used by MCP tools inside the sandbox (relative
        #     to VM_WORKSPACE, e.g. "outputs/<task_name>").
        # task_output_dir: host-side persistent path used for checkpoint files,
        #     logs, and best-effort host writes.
        workspace_persistent = os.environ.get("WORKSPACE_PERSISTENT")
        task_output_subdir = Path("outputs") / task_name
        sandbox_output_dir = str(task_output_subdir)
        if workspace_persistent:
            task_output_dir = str(Path(workspace_persistent) / task_output_subdir)
        else:
            task_output_dir = str(task_output_subdir)
        if getattr(args, "output_dir", None):
            task_output_dir = str(args.output_dir).rstrip("/")
            task_output_subdir = Path(task_output_dir)
        Path(task_output_dir).mkdir(parents=True, exist_ok=True)

        # Create reproducibility snapshot for run (config + git state)
        # Note: run_agent.sh also creates this; to avoid clobbering, we only
        # create the full snapshot if run_config.env is missing, but we ALWAYS
        # ensure that submodules/modules are captured under reproducibility/.
        repro_check_path = Path(task_output_dir) / "reproducibility" / "run_config.env"
        try:
            if not repro_check_path.exists():
                task_env_file = None
                if hasattr(args, "workflow_file") and args.workflow_file:
                    # Derive task_env_file path from workflow_file if it exists
                    plan_file_path = Path(args.workflow_file)
                    env_file_path = plan_file_path.with_suffix(".env")
                    if env_file_path.exists():
                        task_env_file = str(env_file_path)

                create_reproducibility_snapshot(
                    output_dir=Path(task_output_dir),
                    workflow_file=getattr(args, "workflow_file", ""),
                    task_env_file=task_env_file,
                    checkpoint_path=getattr(args, "checkpoint_path", None),
                    trace_path=getattr(args, "trace_path", None),
                    resume=getattr(args, "resume", False),
                    mcp_url=getattr(args, "mcp_url", None),
                )

            # In all cases (even when snapshot was created by run_agent.sh),
            # make sure submodules/modules referenced by the workflow are saved.
            ensure_workflow_submodules_snapshot(
                output_dir=Path(task_output_dir),
                workflow_file=getattr(args, "workflow_file", ""),
            )
        except Exception as e:
            # Don't fail the run if reproducibility snapshot or submodule capture fails
            print(f"Warning: Failed to create/augment reproducibility snapshot: {e}")
            traceback.print_exc()

        # Workspace Backup configuration
        self.host_workspace = os.environ.get("HOST_WORKSPACE")
        if workspace_persistent:
            self.workspace_backup_path = Path(workspace_persistent)
        else:
            self.workspace_backup_path = Path(task_output_dir) / "workspace_snapshot"

        # Use external logger if provided, otherwise create sandbox logger
        if external_logger:
            logger = external_logger
        else:
            logger = Logger(
                mcp_client=self.mcp_client,
                log_file=sandbox_output_dir + "/agent_run.log",
                host_log_path=Path(task_output_dir) / "agent_run.log",
                event_log_path=sandbox_output_dir + "/agent_events.log",
                host_event_log_path=Path(task_output_dir) / "agent_events.log",
            )
            try:
                logger.event(
                    "info",
                    {
                        "message": f"Logs: {task_output_dir}/agent_run.log  Events: {task_output_dir}/agent_events.log",
                        "log_path": logger.log_path,
                        "event_log_path": logger.event_log_path,
                    },
                )
            except Exception:
                pass

        def _rotate_existing_file(path: Path, label: str) -> None:
            """Move aside existing state files instead of deleting them."""
            if not path.exists():
                return
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = path.with_name(f"{path.stem}-prev-{ts}{path.suffix}")
            try:
                path.rename(backup_path)
                logger(
                    f"Fresh run: preserved existing {label} at {backup_path} (was {path})"
                )
            except Exception as e:
                logger(f"Warning: failed to rotate existing {label} at {path}: {e}")

        def _find_latest_checkpoint(base_dir: Path) -> Optional[Path]:
            """
            Find the most recent checkpoint file in a directory.

            We consider any file matching 'checkpoint*.json' in the given
            directory and return the one with the latest modification time.
            """
            try:
                candidates = [
                    p for p in base_dir.glob("checkpoint*.json") if p.is_file()
                ]
            except Exception:
                return None
            if not candidates:
                return None
            try:
                return max(candidates, key=lambda p: p.stat().st_mtime)
            except Exception:
                return None

        logger.log_event(
            logger,
            "workflow_start",
            {
                "task_name": task_name,
                "goal": goal,
                "model": effective_args.model,
                "total_steps": len(workflow),
            },
        )

        # --- Checkpoint Manager Setup ---
        resume_enabled = bool(getattr(args, "resume", False))

        checkpoint_arg = getattr(args, "checkpoint_path", None)
        if resume_enabled:
            # Resume: honor explicit checkpoint_arg if provided,
            # otherwise pick the latest checkpoint*.json under task_output_dir.
            if checkpoint_arg:
                checkpoint_path = Path(checkpoint_arg)
            else:
                latest = _find_latest_checkpoint(Path(task_output_dir))
                if latest:
                    checkpoint_path = latest
                    logger(f"[Resume] Using latest checkpoint at {checkpoint_path}")
                else:
                    logger(
                        f"[Resume] WARNING: No checkpoint*.json found in {task_output_dir}; starting from scratch."
                    )
                    checkpoint_path = Path(task_output_dir) / "checkpoint.json"
        else:
            # Fresh run: default to explicit path or checkpoint.json
            checkpoint_path = Path(
                checkpoint_arg or (Path(task_output_dir) / "checkpoint.json")
            )
        trace_path = Path(
            getattr(args, "trace_path", None) or (Path(task_output_dir) / "trace.jsonl")
        )
        run_id = uuid.uuid4().hex[:12]
        artifacts: Dict[str, Any] = {"step_outputs": {}, "final_output": None}

        # Fresh run: move existing state aside to avoid unintended resume
        if not resume_enabled:
            _rotate_existing_file(checkpoint_path, "checkpoint")
            _rotate_existing_file(trace_path, "trace")

        checkpoint_manager = CheckpointManager(
            checkpoint_path, load_existing=resume_enabled
        )

        if resume_enabled and checkpoint_manager.loaded:
            # Validate checkpoint
            kind = checkpoint_manager.get_metadata("kind")
            version = checkpoint_manager.get_metadata("schema_version")
            if kind != CHECKPOINT_KIND:
                logger(f"WARNING: Checkpoint kind '{kind}' mismatch during resume")
            if version != CHECKPOINT_SCHEMA_VERSION:
                logger(
                    f"WARNING: Checkpoint version '{version}' mismatch during resume"
                )

            # Restore Run ID
            saved_run_id = checkpoint_manager.get_metadata("run_id")
            if saved_run_id:
                run_id = saved_run_id

            # Restore Artifacts
            saved_artifacts = checkpoint_manager.data.get("artifacts")
            if saved_artifacts:
                if "step_outputs" in saved_artifacts:
                    artifacts["step_outputs"] = saved_artifacts["step_outputs"]
                if "final_output" in saved_artifacts:
                    artifacts["final_output"] = saved_artifacts["final_output"]

            # Restore MCP session
            desired_mcp_session_id = checkpoint_manager.get_metadata("mcp_session_id")
            if desired_mcp_session_id:
                current_sid = self.mcp_client.get_session_id()
                if current_sid != desired_mcp_session_id:
                    try:
                        self.mcp_client.close()
                    except Exception as e:
                        logger(
                            f"Warning: failed to close previous MCP session before resume: {e}"
                        )
                    logger(f"Resuming MCP session: {desired_mcp_session_id}")
                    self.mcp_client = MCPClient(
                        url=self.mcp_url, session_id=str(desired_mcp_session_id)
                    )
                    # Refresh default tool wrappers + tool list
                    self.mcp_fs_write = self.mcp_client.make_mcp_tool_function(
                        "fs_write", ["path", "content"]
                    )
                    self.mcp_fs_read = self.mcp_client.make_mcp_tool_function(
                        "fs_read", ["path", "max_bytes"]
                    )
                    self.tools = self.mcp_client.list_tools()

                    # Update interpreter to use the new MCP client and tools
                    self.agent_interpreter.mcp_client = self.mcp_client
                    self.agent_interpreter.tools = self.tools
                    self.agent_interpreter.mcp_fs_write = self.mcp_fs_write
                    self.agent_interpreter.mcp_fs_read = self.mcp_fs_read
                    self.agent_interpreter.llm_executor.mcp_client = self.mcp_client
                    self.agent_interpreter.llm_executor.tools = self.tools

                    # Re-init logger with new client (append mode to preserve events)
                    if not external_logger:
                        logger = Logger(
                            mcp_client=self.mcp_client,
                            log_file=sandbox_output_dir + "/agent_run.log",
                            host_log_path=Path(task_output_dir) / "agent_run.log",
                            event_log_path=sandbox_output_dir + "/agent_events.log",
                            host_event_log_path=Path(task_output_dir)
                            / "agent_events.log",
                            append_mode=True,
                        )

            # Restore workspace from manifest (lightweight, replaces full rsync restore).
            # Mirrors the DISABLE_WORKSPACE_MANIFEST guard on the per-step capture path
            # (see below): if the current run never captures manifests, there is
            # nothing meaningful to restore, and under concurrent evolve runs on a
            # shared NFS workspace a stale multi-hundred-MB manifest from a prior
            # run can block this process in uninterruptible disk sleep for hours.
            if self.host_workspace and not os.environ.get("DISABLE_WORKSPACE_MANIFEST"):
                logger("[Resume] Restoring workspace from manifest")
                checkpoint_manager.restore_from_manifest(
                    target_dir=Path(self.host_workspace),
                    logger=logger,
                )

                # Also restore task output files from persistent storage
                saved_backup_path = checkpoint_manager.get_metadata(
                    "workspace_backup_path"
                )
                backup_path = (
                    Path(saved_backup_path)
                    if saved_backup_path
                    else self.workspace_backup_path
                )

                if backup_path and backup_path.exists():
                    logger(f"[Resume] Restoring task output files from {backup_path}")
                    checkpoint_manager.restore_task_files(
                        backup_dir=backup_path,
                        target_dir=Path(self.host_workspace),
                        task_output_subdir=str(task_output_subdir),
                        logger=logger,
                    )

        # Update checkpoint with static info immediately
        checkpoint_manager.set_metadata("kind", CHECKPOINT_KIND)
        checkpoint_manager.set_metadata("schema_version", CHECKPOINT_SCHEMA_VERSION)
        checkpoint_manager.set_metadata("run_id", run_id)
        checkpoint_manager.set_metadata("task_name", task_name)
        checkpoint_manager.set_metadata(
            "workflow_file", getattr(args, "workflow_file", "")
        )
        checkpoint_manager.set_metadata("task_output_dir", task_output_dir)

        # Durable execution: tool-level trace (record) or replay
        replay_trace_path = getattr(args, "replay_trace", None)
        if replay_trace_path:
            self.mcp_client.enable_replay(str(replay_trace_path))
            # Load LLM response events for replay
            replay_events = [
                ev
                for ev in iter_jsonl(Path(replay_trace_path))
                if ev.get("type") == "llm_response"
            ]
            self._configure_tracing(trace_writer=None, replay_events=replay_events)
        else:
            self.mcp_client.enable_tracing(str(trace_path))
            self._configure_tracing(trace_writer=TraceWriter(trace_path))

        def _checkpointable_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
            omit = {"submodule_tools", "submodule_registry"}
            out: Dict[str, Any] = {}
            for k, v in (ctx or {}).items():
                if isinstance(k, str) and k.startswith("_"):
                    continue
                if k in omit:
                    continue
                out[k] = v
            return out

        logger(f"*************")
        logger(
            f"This is a {effective_args.model} YAML agent executing workflow: {task_name}"
        )
        logger(f"Goal: {goal}")
        if yaml_config:
            logger(f"Config from YAML: {yaml_config}")
        logger("\n")

        # Initialize context with parameters and metadata
        context = {
            "task_name": task_name,
            "goal": goal,
            "task_output_dir": task_output_dir,
            "sandbox_output_dir": sandbox_output_dir,
            "prev_output": "",
            "submodule_tools": submodule_tools,
            "submodule_registry": submodule_registry,
            "workflow_file": args.workflow_file,
            "workflow_dir": str(Path(args.workflow_file).resolve().parent),
            "workflow_root": str(Path(args.workflow_file).resolve().parent),
        }

        # Add parameters from YAML to context
        if "parameters" in yaml_data:
            context.update(yaml_data["parameters"])

        # Resume: restore context from checkpoint
        if resume_enabled and checkpoint_manager.loaded:
            saved_context = checkpoint_manager.data.get("context")
            if saved_context and isinstance(saved_context, dict):
                for k, v in saved_context.items():
                    context[k] = v

        # Allow workflow to override the default system prompt
        if yaml_data.get("system_prompt"):
            context["system_prompt"] = yaml_data.get("system_prompt")

        KEYS = [
            "enabled_tools",
            "enabled_submodules",
            "expose_submodules_as_tools",
            "allow_inline_tools_without_enable",
            "inline_tool_calls_only",
            "enable_inline_tool_calls",
            "stop_on_return",
            "require_submodule_submit",
            "max_workflow_steps",
            "swebench_mode",
            "enable_git_filtering",
            "require_thought_section",
            "thought_missing_message",
            "thought_footer_message",
            "submit_reminder_message",
        ]

        for key in KEYS:
            if key in yaml_config:
                context[key] = yaml_config[key]
            elif key in yaml_data:
                context[key] = yaml_data[key]

        if context.get("swebench_mode"):
            context.setdefault("enable_git_filtering", True)
            context.setdefault("require_thought_section", True)

        # Initialize workflow-level conversation history
        ensure_conversation_history(context, effective_args)

        # Add problem_statement from args if present
        if (
            hasattr(effective_args, "problem_statement")
            and effective_args.problem_statement
        ):
            context["problem_statement"] = effective_args.problem_statement

        logger("===== YAML Workflow =====")
        logger(f"Task: {task_name}")
        logger(f"Parameters: {yaml_data.get('parameters', {})}")
        logger(f"Workflow steps: {len(workflow)}")

        logger("===== tools =====")
        tool_config = EffectiveToolConfig.compute(self.tools, context)
        for tool in tool_config.tools:
            logger(f"Tool: {get_tool_name(tool)}")
        if tool_config.submodule_tools:
            logger("===== submodule tools =====")
            for tool in tool_config.submodule_tools:
                logger(f"Submodule tool: {get_tool_name(tool)}")

        # Execute workflow
        step_outputs = []

        max_workflow_steps = context.get("max_workflow_steps")
        for i, step_data in enumerate(workflow, 1):
            step_id = str(i)
            # Use checkpoint manager to skip
            if resume_enabled and checkpoint_manager.is_completed(step_id):
                logger(f"Skipping completed step {step_id}")
                # Emit step events so the dashboard shows completed steps
                step_type = ""
                step_name = f"Step {step_id}"
                if isinstance(step_data, dict):
                    step_type = step_data.get("step_type", "")
                    step_name = (step_data.get(step_type) or {}).get("name", step_name)
                logger.log_event(
                    logger,
                    "step_start",
                    {
                        "step_id": step_id,
                        "step_number": step_id,
                        "name": step_name,
                        "step_type": step_type,
                        "instruction": "(resumed – previously completed)",
                        "depth": 0,
                    },
                )
                logger.log_event(
                    logger,
                    "step_end",
                    {
                        "step_id": step_id,
                        "tokens": 0,
                        "status": "completed",
                    },
                )
                try:
                    step_out_file = Path(task_output_dir) / f"step-{step_id}-output.txt"
                    if step_out_file.exists():
                        output = step_out_file.read_text(encoding="utf-8")
                        context["prev_output"] = output
                        step_outputs.append(output)
                    else:
                        logger(
                            f"Warning: Step {step_id} marked complete but output file missing."
                        )
                except Exception as e:
                    logger(f"Warning: Failed to restore step {step_id} output: {e}")
                continue

            if max_workflow_steps and i > int(max_workflow_steps):
                logger(
                    f"Reached max_workflow_steps={max_workflow_steps}; stopping workflow execution."
                )
                break
            try:
                logger("%" * 20)
                logger(f"Cross Step Context: {safe_json_dumps(context)}")
                logger("%" * 20)

                # Pass checkpoint_manager to execute_workflow_step
                output, _ = self.agent_interpreter.execute_workflow_step(
                    step_data,
                    context,
                    i,
                    effective_args,
                    logger,
                    checkpoint_manager=checkpoint_manager,
                )
                context["prev_output"] = output
                step_outputs.append(output)

                # Write step output to file (sandbox + host mirror)
                step_filename = f"step-{i}-output.txt"
                self.mcp_fs_write(f"{sandbox_output_dir}/{step_filename}", output)
                host_step_path = f"{task_output_dir}/{step_filename}"
                checkpoint_manager.best_effort_host_write_text(
                    host_step_path, output, append=False
                )
                artifacts["step_outputs"][str(i)] = host_step_path

                # Update Checkpoint via Manager
                checkpoint_manager.set_metadata(
                    "mcp_session_id", self.mcp_client.get_session_id()
                )
                checkpoint_manager.mark_completed(
                    step_id=step_id,
                    context=_checkpointable_context(context),
                    artifacts=artifacts,
                    metrics={
                        "total_tokens": self.usage_tracker["prompt_tokens_total"]
                        + self.usage_tracker["completion_tokens_total"],
                        "prompt_tokens": self.usage_tracker["prompt_tokens_total"],
                        "completion_tokens": self.usage_tracker[
                            "completion_tokens_total"
                        ],
                        "cost": self.usage_tracker["cost_total"],
                        "tool_calls_total": self.usage_tracker["tool_calls_total"],
                    },
                    update_context=True,
                )

                # Capture lightweight workspace manifest (replaces full rsync backup).
                # Skip when DISABLE_WORKSPACE_MANIFEST is set — useful for evolve-style
                # workflows whose only artifact is a single YAML they write themselves,
                # where the per-step snapshot is pure overhead and (under concurrent
                # runs on a shared workspace) can starve local HTTP sockets and cause
                # EIO on the next LLM call.
                if self.host_workspace and not os.environ.get("DISABLE_WORKSPACE_MANIFEST"):
                    checkpoint_manager.capture_and_save_manifest(
                        workspace_dir=Path(self.host_workspace),
                        step_id=step_id,
                        backup_dir=self.workspace_backup_path,
                        logger=logger,
                    )

            except ToolCallLimitExceeded as e:
                logger(f"Global tool call limit reached at step {i}: {e}")
                logger.log_event(
                    logger,
                    "tool_call_limit_reached",
                    {
                        "step_id": str(i),
                        "total_tool_calls": self.usage_tracker["tool_calls_total"],
                        "limit": effective_args.max_tool_calls,
                    },
                )
                output = f"Tool call limit reached at step {i}: {str(e)}"
                step_outputs.append(output)
                context["prev_output"] = output
                if checkpoint_manager:
                    try:
                        checkpoint_manager.set_metadata("status", "tool_call_limit_reached")
                    except Exception:
                        pass
                break
            except Exception as e:
                logger(f"Error executing step {i}: {str(e)}")
                output = f"Error in step {i}: {str(e)}"
                step_outputs.append(output)
                if checkpoint_manager:
                    try:
                        checkpoint_manager.set_metadata("last_error", str(e))
                        checkpoint_manager.set_metadata("status", "error")
                    except Exception:
                        pass

        # Write final output
        final_output = context["prev_output"]
        self.mcp_fs_write(f"{sandbox_output_dir}/final-output.txt", final_output)
        final_file_path = f"{task_output_dir}/final-output.txt"
        checkpoint_manager.best_effort_host_write_text(
            final_file_path, final_output, append=False
        )
        artifacts["final_output"] = final_file_path
        if checkpoint_manager:
            try:
                checkpoint_manager.set_metadata(
                    "pointer",
                    {
                        "next_step": len(workflow) + 1,
                        "last_completed_step": len(workflow),
                        "status": "completed",
                    },
                )
                checkpoint_manager.set_metadata(
                    "context", _checkpointable_context(context)
                )
                checkpoint_manager.set_metadata(
                    "metrics",
                    {
                        "total_tokens": self.usage_tracker["prompt_tokens_total"]
                        + self.usage_tracker["completion_tokens_total"],
                        "prompt_tokens": self.usage_tracker["prompt_tokens_total"],
                        "completion_tokens": self.usage_tracker[
                            "completion_tokens_total"
                        ],
                        "cost": self.usage_tracker["cost_total"],
                        "tool_calls_total": self.usage_tracker["tool_calls_total"],
                    },
                )
            except Exception as exc:
                logger(f"Warning: failed to persist final checkpoint metadata: {exc}")

        total_prompt = self.usage_tracker["prompt_tokens_total"]
        total_completion = self.usage_tracker["completion_tokens_total"]
        total_tokens = total_prompt + total_completion

        logger(f"\n\nTotal steps executed: {len(workflow)}")
        logger(f"Total tokens used: {total_tokens}")
        logger(f"Total tool calls: {self.usage_tracker['tool_calls_total']}")
        logger(f"Output files can be found in {task_output_dir}.")
        logger(f"Final output written to {final_file_path}")
        logger.log_event(
            logger,
            "workflow_end",
            {
                "total_tokens": total_tokens,
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_steps": len(workflow),
                "output_dir": task_output_dir,
                "final_file_path": final_file_path,
                "reasoning_tokens": self.usage_tracker["reasoning_tokens_total"],
                "cost": self.usage_tracker["cost_total"],
                "tool_calls_total": self.usage_tracker["tool_calls_total"],
            },
        )

        return final_output
