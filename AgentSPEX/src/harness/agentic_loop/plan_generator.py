"""Plan generator: uses a cheap LLM to produce AgentSPEX YAML workflows."""

import re
from pathlib import Path
from typing import Optional

import yaml

from harness.llms.client import LLMClient

from .prompts import get_plan_generator_system_prompt


class PlanGenerator:
    """Generate AgentSPEX YAML workflow plans for a given task.

    Uses a (typically cheap) LLM to produce YAML, validates it parses,
    and writes it to disk. Retries once on parse failure with error feedback.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model: str,
        plans_dir: Path,
        available_tool_names: list[str],
        workflow_language_guide: str,
        temperature: float = 0.2,
        tool_briefs: dict[str, dict] | None = None,
        executor_model: str | None = None,
    ):
        self.llm_client = llm_client
        self.model = model
        self.plans_dir = plans_dir
        self.available_tool_names = available_tool_names
        self.temperature = temperature
        self._tool_briefs = tool_briefs or {}
        self._system_prompt = get_plan_generator_system_prompt(
            available_tool_names,
            workflow_language_guide,
            executor_model=executor_model,
        )
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        task_id: str,
        task_description: str,
        context_summary: Optional[str] = None,
        hints: Optional[str] = None,
        recommended_tools: Optional[list[str]] = None,
    ) -> Path:
        """Generate a YAML plan for the given task.

        Args:
            task_id: Identifier used for the output filename (e.g. "task_001").
            task_description: What the task should accomplish.
            context_summary: Optional summary of relevant context from the
                orchestrator's conversation so far.
            hints: Optional hints for the plan generator (e.g. preferred
                structure, tool preferences).
            recommended_tools: Optional list of MCP tool names pre-selected
                by the orchestrator. When provided, the plan generator is
                instructed to use ONLY these tools. The orchestrator (more
                capable model with full tool schemas) makes the tool selection
                decision; the plan generator focuses on workflow structure.

        Returns:
            Path to the generated YAML file.

        Raises:
            ValueError: If YAML generation fails after retry.
        """
        user_message = self._build_user_message(
            task_description,
            context_summary,
            hints,
            recommended_tools,
        )

        # First attempt
        raw_response = self._call_llm(user_message)
        yaml_str = self._extract_yaml(raw_response)

        parse_error = self._try_parse(yaml_str)
        if parse_error:
            # Retry with error feedback
            retry_message = (
                f"The YAML you produced has a syntax error:\n{parse_error}\n\n"
                f"Original YAML:\n```yaml\n{yaml_str}\n```\n\n"
                "Please fix the error and return the corrected YAML "
                "inside a ```yaml fenced code block."
            )
            raw_response = self._call_llm(retry_message)
            yaml_str = self._extract_yaml(raw_response)
            parse_error = self._try_parse(yaml_str)
            if parse_error:
                raise ValueError(
                    f"Plan generation failed after retry. YAML error: {parse_error}"
                )

        # Write to disk
        plan_path = self.plans_dir / f"{task_id}.yaml"
        plan_path.write_text(yaml_str, encoding="utf-8")
        return plan_path

    def _build_user_message(
        self,
        task_description: str,
        context_summary: Optional[str],
        hints: Optional[str],
        recommended_tools: Optional[list[str]] = None,
    ) -> str:
        parts = [
            f"Generate a YAML workflow plan for the following task:\n\n{task_description}"
        ]
        if recommended_tools:
            tools_str = ", ".join(recommended_tools)
            parts.append(
                f"\n\n## Recommended Tools\n\n"
                f"The orchestrator has selected the following MCP tools for this task. "
                f"Use ONLY these tools in your plan's `enabled_tools` and step instructions:\n"
                f"  {tools_str}\n"
                f"Do NOT use tools outside this list."
            )
            # Inject tool parameter guidance for recommended tools that have briefs
            brief_lines = self._format_tool_briefs(recommended_tools)
            if brief_lines:
                parts.append(
                    "\n\n## Tool Parameter Guidance\n\n"
                    "The following describes output sizes and recommended parameter limits "
                    "for the tools above. Your step instructions should respect these limits "
                    "to avoid context exhaustion during execution.\n" + brief_lines
                )
        if context_summary:
            parts.append(f"\n\n## Context from Prior Tasks\n\n{context_summary}")
        if hints:
            parts.append(f"\n\n## Structural Hints\n\n{hints}")
        return "".join(parts)

    def _format_tool_briefs(self, recommended_tools: list[str]) -> str:
        """Format tool briefs for recommended tools that have entries in tool_briefs.yaml.

        Returns a compact string with one line per tool, or empty string if
        no recommended tools have briefs.
        """
        lines = []
        for tool_name in recommended_tools:
            brief_data = self._tool_briefs.get(tool_name)
            if not brief_data:
                continue
            brief_text = brief_data.get("brief", "")
            params = brief_data.get("params", {})
            # Build param constraint hints
            param_hints = []
            for param_name, param_info in params.items():
                if isinstance(param_info, dict) and "safe_max" in param_info:
                    param_hints.append(f"keep {param_name} ≤ {param_info['safe_max']}")
            constraint = (" " + "; ".join(param_hints) + ".") if param_hints else ""
            # Include tool-level note if present (for tools without params)
            note = brief_data.get("note", "")
            note_suffix = f" {note}" if note and not param_hints else ""
            lines.append(f"- **{tool_name}**: {brief_text}{constraint}{note_suffix}")
        return "\n".join(lines)

    def _call_llm(self, user_message: str) -> str:
        """Single LLM call with system prompt, no tools."""
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_message},
        ]
        response = self.llm_client.completion(
            model=self.model,
            messages=messages,
            tools=None,
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _extract_yaml(raw: str) -> str:
        """Extract YAML from a ```yaml fenced code block, or use raw text."""
        match = re.search(r"```yaml\s*\n(.*?)```", raw, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: try the whole response
        return raw.strip()

    @staticmethod
    def _try_parse(yaml_str: str) -> Optional[str]:
        """Attempt to parse YAML. Returns error message on failure, None on success."""
        try:
            data = yaml.safe_load(yaml_str)
            if not isinstance(data, dict):
                return "YAML did not parse to a dictionary (got {})".format(
                    type(data).__name__
                )
            if "workflow" not in data:
                return "Missing required top-level key: 'workflow'"
            if "name" not in data:
                return "Missing required top-level key: 'name'"
            return None
        except yaml.YAMLError as e:
            return str(e)
