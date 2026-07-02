"""Step handler implementations for the agent interpreter.

This package provides mixin classes that implement various workflow step types
for the YAML agent framework. Each mixin handles a specific category of steps:

- BasicStepsMixin: Simple LLM-driven steps and task steps
- ControlFlowMixin: Loops (for_each, while) and conditionals (if/else, switch)
- VariableStepsMixin: Variable manipulation (set, increment, return, input)
- SubmoduleStepsMixin: Sub-workflow calls, parallel gathering, and parallel execution

Example:
    class AgentInterpreter(StepHandlersMixin):
        def __init__(self, llm_executor, mcp_client, tools):
            self.llm_executor = llm_executor
            self.mcp_client = mcp_client
            self.tools = tools
            # ... additional initialization
"""

from __future__ import annotations

from .basic import BasicStepsMixin
from .calls import SubmoduleStepsMixin
from .control import ControlFlowMixin
from .variables import VariableStepsMixin


class StepHandlersMixin(
    BasicStepsMixin,
    ControlFlowMixin,
    VariableStepsMixin,
    SubmoduleStepsMixin,
):
    """Combined mixin providing all step execution methods.

    This mixin aggregates all step handler categories into a single class
    that can be inherited by the agent interpreter. The method resolution
    order (MRO) ensures that all step execution methods are available.

    Required Attributes:
        llm_executor: LLMExecutor instance for executing LLM-driven steps.
        mcp_client: MCPClient instance for tool invocation.
        tools: List of available tool definitions.
        mcp_fs_write: Callable for writing files via MCP.
        _load_submodule_tools_for_yaml: Callable for loading submodule tools.
        execute_workflow_step: Callable for recursive step execution.

    Step Methods Provided:
        - execute_basic_step: Step with persistent conversation history and tool use
        - execute_task_step: Stateless, fresh LLM instruction execution
        - execute_for_each_step: Loop over items
        - execute_conditional_step: If/then/else branching
        - execute_while_step: Conditional loop
        - execute_switch_step: Multi-way branching
        - execute_set_variable_step: Set context variable
        - execute_increment_step: Increment numeric variable
        - execute_return_step: Return value from workflow
        - execute_input_step: Interactive user input
        - execute_call_step: Call sub-workflow
        - execute_gather_step: Parallel sub-workflow calls
        - execute_parallel_step: Parallel step execution
    """

    pass


__all__ = ["StepHandlersMixin"]
