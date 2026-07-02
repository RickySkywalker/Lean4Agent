from typing import Any, Dict, Optional, Union

from harness.parsing.templates import expand_template_variables

# Action format strings shown to the LLM per interaction mode.
# Injected into the system prompt when interaction_mode is set in context.
_SOM_ACTION_FORMAT = """
INTERACTION MODE: Set-of-Marks
You will receive an annotated screenshot with numbered colored boxes over interactive elements,
plus an accessibility tree (id, text, tag) for each numbered element.

Before EVERY action, write a brief thought on its own line:
Thought: [describe what you observe on the page and why you are taking the next action]

Then on the next line, state your action using STRICTLY this format:
- Click [N]               — click element with label N
- Type [N] [text]         — type text into element N, then press Enter
- Hover [N]               — hover over element N
- Scroll [N or WINDOW] [up or down] — scroll element N or the entire page
- GoBack                  — navigate back to the previous page
- Wait                    — wait briefly for the page to load

Example:
Thought: I can see the search bar at element [3] and a Sign In button at [9]. I will type the query into the search bar.
Type [3] mechanical keyboard
""".strip()


def resolve_system_prompt(prompt: Any, context: Dict[str, Any]) -> Union[str, None]:
    """Resolve a system prompt with template expansion."""
    return expand_template_variables(str(prompt), context) if prompt else None


def get_yaml_system_prompt(
    task_name: str, goal: str, args, context: Optional[Dict[str, Any]] = None
) -> str:
    """Get system prompt for YAML agent."""
    if context and (prompt := context.get("system_prompt")) is not None:
        if resolved := resolve_system_prompt(prompt, context):
            base = resolved
        else:
            base = get_default_system_prompt(args, task_name, goal)
    else:
        base = get_default_system_prompt(args, task_name, goal)

    # Append computer-use action format when interaction_mode is set
    if context and context.get("interaction_mode") == "set_of_marks":
        base = base.rstrip() + "\n\n" + _SOM_ACTION_FORMAT

    return base


def get_default_system_prompt(args, task_name: str, goal: str) -> str:
    # NOTE: Use relative path under VM_WORKSPACE; MCP fs_write will prefix /workspace
    task_output_dir = f"outputs/{task_name}"

    system_prompt = f"""You are an intelligent research assistant executing a YAML-defined workflow.

TASK: {task_name}
GOAL: {goal}

Your role is to execute workflow steps as defined in a YAML file. Each step will provide you with specific instructions that you should follow carefully and thoroughly.

CAPABILITIES:
- You have access to various MCP tools for research, file operations, and data processing
- You can write files, read files, search the web, and perform complex analysis
- You should build upon previous steps' outputs when appropriate
- Always provide detailed, informative responses

WORKSPACE:
- Your workspace directory is: {task_output_dir}
- Use fs_write tool to save any outputs or intermediate results
- Step outputs are automatically saved to step-N-output.txt files

EXECUTION GUIDELINES:
1. Follow each step's instruction precisely
2. Use appropriate tools to gather information and create content
3. When uncertain, use multiple sources and cross-reference information
4. Provide comprehensive outputs that serve the overall goal
5. If you encounter errors, try alternative approaches
6. Build systematic knowledge throughout the workflow

Remember: You are part of a larger workflow. Each step builds toward the final goal of: {goal}
"""

    return system_prompt
