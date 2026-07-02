# YAML Task Language - Complete Beginner's Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Quick Start](#quick-start)
3. [Basic Structure](#basic-structure)
4. [Environment Variables and Parameters](#environment-variables-and-parameters)
5. [Step Types Reference](#step-types-reference)
6. [Template Variables](#template-variables)
7. [Context and Memory Management](#context-and-memory-management)
8. [Tool Filtering](#tool-filtering)
9. [Advanced Features](#advanced-features)
10. [Complete Examples](#complete-examples)
11. [Best Practices](#best-practices)
12. [Running Your Workflows](#running-your-workflows)

---

## Introduction

The YAML Task Language is a structured workflow language that allows you to define complex, multi-step tasks for an AI agent to execute. The agent has access to various tools (web search, file operations, code execution, etc.) and can orchestrate them according to your workflow definition.

**Key Features:**
- Declarative workflow syntax
- Support for loops, conditionals, and parallel execution
- Context management and variable passing
- Persistent memory system
- Modular design with reusable sub-workflows
- Environment variable integration

---

## Quick Start

Here's a minimal working example:

```yaml
name: "hello_world"
goal: "A simple task to demonstrate the basics"

parameters:
  greeting: "Hello"
  name: "World"

workflow:
  - step:
      name: "greet"
      instruction: "Say '{{greeting}}, {{name}}!' in a friendly way"
```

To run this:
```bash
bash ./scripts/run_agent.sh path/to/hello_world.yaml
```

---

## Basic Structure

Every YAML workflow consists of four main sections:

```yaml
# 1. Name: Unique identifier for this task
name: "task_name"

# 2. Goal: High-level description of what this task achieves
goal: "Brief description of the task objective"

# 3. Parameters: Variables available throughout the workflow
parameters:
  variable1: "value1"
  variable2: 42

# 4. Workflow: Sequence of steps to execute
workflow:
  - step:
      name: "first_step"
      instruction: "What the agent should do"

  - step:
      name: "second_step"
      instruction: "Next action to take"
```

### Execution Config (Optional)

Use the `config` section to control model settings. `model_kwargs` is passed directly
to the underlying LLM client (e.g., `max_tokens`, `temperature`, `reasoning_effort`).

```yaml
config:
  model: "gpt-4.1-mini"   # or model_name
  model_kwargs:
    temperature: 0.0
```

---

## System Prompt Override

You can override the default system prompt directly in the workflow:

```yaml
name: "custom_prompt_task"
goal: "Demonstrate a custom system prompt"
system_prompt: |
  You are a concise, pragmatic assistant.
  Always return outputs as bullet points.

workflow:
  - step:
      instruction: "Summarize the goal."
```

Notes:
- Template variables like `{{parameter_name}}` work inside `system_prompt`.
- You can also change it during execution by setting `system_prompt` via a `set_variable` step.

---

### Per-Step System Prompt Override

You can override the system prompt for a single step by adding `system_prompt` to that step:

```yaml
workflow:
  - step:
      name: "specialized_step"
      system_prompt: |
        You are a strict JSON generator.
        Return only JSON.
      instruction: "Return a JSON object with a single key 'ok' set to true."
```

This override supports `{{}}` template variables and applies only to that step.

---

## Parameters and Configuration

### Defining Parameters

Parameters are set directly in the YAML file and available throughout the workflow via `{{name}}`:

```yaml
name: "research_report"
goal: "Research artificial intelligence and write a report"

parameters:
  topic: "artificial_intelligence"
  max_papers: 10
  output_format: "markdown"
```

Environment variable substitution (`${VAR}`) is also supported for values you want to set externally (e.g. via shell exports):

```yaml
parameters:
  topic: "${PLAN_TOPIC:-artificial_intelligence}"  # Falls back to default
```

### Parameter Scope

Parameters are available throughout the workflow and can be:
- Read using template syntax: `{{parameter_name}}`
- Modified during execution (e.g., with `set_variable`)
- Passed to sub-modules

---

## Step Types Reference

### 1. Step (Conversation History)

Steps append a new user message to a workflow-level conversation history and run the model against that shared history. This is useful for multi-turn interactions that should remember prior exchanges.

**Syntax:**
```yaml
- step:
    name: "descriptive_name"
    instruction: "Detailed instruction for the agent"
    save_as: "variable_name"  # Optional: save output to context
```

**Example:**
```yaml
- step:
    instruction: "Remember the passphrase ORANGE BANANA. Reply only with OK."
- step:
    instruction: "What passphrase did I ask you to remember? Reply only with the passphrase."
```

**Key Points:**
- Conversation history is preserved across `step` steps only
- `step` does not auto-inject `prev_output`; use `{{prev_output}}` explicitly if needed
- `system_prompt` should be set at the workflow level (not per step)

---

### 2. Task (Stateless)

The fundamental building block for standalone agent actions. Tasks send an instruction to the LLM and capture the response. They are stateless - each execution is independent without maintaining conversation history.

**Syntax:**
```yaml
- task:
    name: "descriptive_name"
    instruction: "Detailed instruction for the agent"
    save_as: "variable_name"  # Optional: save output to context
```

**Example:**
```yaml
- task:
    name: "search_papers"
    instruction: |
      Search arXiv for papers about {{topic}}.
      Find the top 5 most relevant papers.
      Return their titles and arXiv IDs as a JSON array.
    save_as: "paper_list"
```

**Key Points:**
- The agent will use available tools to accomplish the instruction
- Instructions should be clear and specific
- Use `save_as` to store results for later use
- Use `|` for multi-line instructions
- Each task starts with a fresh conversation (no prior context)

---

### 3. For-Each Loop

Iterate over a list, executing sub-steps for each item.

**Syntax:**
```yaml
- for_each:
    variable: "loop_variable_name"
    in: "list_name"  # Can be a context variable or literal list
    limit: 10  # Optional: limit iterations
    steps:
      - step:
          instruction: "Process {{loop_variable_name}}"
```

**Example:**
```yaml
- for_each:
    variable: "paper_id"
    in: "paper_list"
    limit: 5
    steps:
      - step:
          name: "download_paper"
          instruction: |
            Download the arXiv paper with ID: {{paper_id}}
            Save it to a local file and return the file path.

      - step:
          name: "analyze_paper"
          instruction: |
            Read the downloaded paper and extract:
            1. Main research question
            2. Key findings
            3. Methodology used
            Return as structured JSON.
```

---

### 4. While Loop

Execute steps repeatedly while a condition is true.

**Syntax:**
```yaml
- while:
    condition: "variable_name < max_value"
    max_iterations: 10  # Safety limit
    steps:
      - step:
          instruction: "Action to perform"
      - increment: "variable_name"
```

**Supported Conditions:**
- Comparisons: `<`, `>`, `<=`, `>=`, `==`, `!=`
- Variables can be compared to numbers or other variables
- Truthiness: `variable_name` (checks if variable exists and is truthy)

**Example:**
```yaml
parameters:
  current_depth: 0
  max_depth: 3

workflow:
  - while:
      condition: "current_depth < max_depth"
      max_iterations: 5
      steps:
        - step:
            instruction: |
              Generate {{breadth}} search queries at depth {{current_depth}}.
              Make them increasingly specific as depth increases.

        - step:
            instruction: "Process the queries and gather results"

        - increment: "current_depth"
```

---

### 5. Conditional (If-Then-Else)

Execute different branches based on conditions.

**Syntax:**
```yaml
- if:
    condition: "variable_name == value"
    then:
      - step:
          instruction: "Action if condition is true"
    else:
      - step:
          instruction: "Action if condition is false"
```

**Example:**
```yaml
- if:
    condition: "paper_count > 0"
    then:
      - step:
          instruction: |
            Analyze the {{paper_count}} papers found.
            Create a comprehensive summary.
    else:
      - step:
          instruction: |
            No papers were found on {{topic}}.
            Suggest alternative search terms or related topics.
```

---

### 6. Set Variable

Set or update context variables.

**Syntax:**
```yaml
- set_variable:
    name: "variable_name"
    value: "literal_value_or_expression"
```

**Example:**
```yaml
- set_variable:
    name: "breadth"
    value: 8

- set_variable:
    name: "breadth"
    value: "{{breadth}} // 2"  # Reduce breadth by half

- set_variable:
    name: "items_list"
    value: '[{"id": 1}, {"id": 2}]'  # JSON literal
```

**Advanced Usage:**
```yaml
# Concatenate lists
- set_variable:
    name: "all_results"
    value: "{{results_1}} + {{results_2}}"

# Mathematical operations
- set_variable:
    name: "next_depth"
    value: "max({{current_depth}} // 2, 1)"

# Python expressions
- set_variable:
    name: "unique_items"
    value: "list(set({{items}}))"
```

---

### 7. Increment

Increment numeric variables (shorthand for common operations).

**Syntax:**
```yaml
- increment: "variable_name"
```

**Example:**
```yaml
parameters:
  counter: 0
  iteration: 0

workflow:
  - increment: "counter"      # counter becomes 1
  - increment: "iteration"    # iteration becomes 1
  - increment: "counter"      # counter becomes 2
```

---

### 8. Input

Collect interactive input from the user.

**Syntax:**
```yaml
- input:
    prompt: "Question or prompt for the user"
    save_as: "variable_name"
    default: "default_value"  # Optional
```

**Example:**
```yaml
- step:
    name: "generate_questions"
    instruction: |
      Given the research topic: {{topic}}
      Generate 3 clarifying questions to ask the user.
      Return as JSON array.
    save_as: "questions_json"

- step:
    name: "parse_questions"
    instruction: |
      Parse the questions from {{questions_json}}.
      Return as a clean JSON array of strings.
    save_as: "questions"

- for_each:
    variable: "question"
    in: "questions"
    steps:
      - input:
          prompt: "{{question}}"
          save_as: "user_answer"

      - step:
          instruction: |
            Store the Q&A pair:
            Q: {{question}}
            A: {{user_answer}}

            Use memory to persist this information.
```

---

### 9. Switch

Multi-way branching based on a variable value.

**Syntax:**
```yaml
- switch:
    variable: "variable_name"
    cases:
      value1:
        - step:
            instruction: "Action for value1"
      value2:
        - step:
            instruction: "Action for value2"
    default:
      - step:
          instruction: "Action if no case matches"
```

**Example:**
```yaml
- switch:
    variable: "research_type"
    cases:
      literature_review:
        - step:
            instruction: "Conduct systematic literature review"
      experimental:
        - step:
            instruction: "Design and run experiments"
      survey:
        - step:
            instruction: "Design survey and collect responses"
    default:
      - step:
          instruction: "Use general research methodology"
```

---

### 10. Call (Sub-modules)

Call another YAML workflow as a reusable module.

**Syntax:**
```yaml
- call:
    module: "path/to/module.yaml"
    parameters:
      param1: "value1"
      param2: "{{context_var}}"
    save_as: "result_variable"
    return: "variable_name"  # Which variable to return from module
```

**Example:**

**Main workflow (research_pipeline.yaml):**
```yaml
name: "research_pipeline"
goal: "Comprehensive research using reusable modules"

parameters:
  topics: ["AI", "Blockchain", "Quantum Computing"]

workflow:
  - for_each:
      variable: "topic"
      in: "topics"
      steps:
        - call:
            module: "modules/paper_analyzer.yaml"
            parameters:
              research_topic: "{{topic}}"
              max_papers: 5
            save_as: "analysis_{{topic}}"
            return: "summary"

  - step:
      name: "combine_analyses"
      instruction: |
        Combine all analyses into a final report.
        Write the report to multi_topic_report.md in the output directory.
```

**Module (modules/paper_analyzer.yaml):**
```yaml
name: "paper_analyzer_module"
goal: "Analyze papers for a given topic"

parameters:
  research_topic: "${RESEARCH_TOPIC}"
  max_papers: "${MAX_PAPERS:-3}"

workflow:
  - step:
      instruction: "Search for {{max_papers}} papers on {{research_topic}}"
      save_as: "papers"

  - step:
      instruction: "Analyze papers and create summary"
      save_as: "summary"

  - return: "summary"  # Return the summary to parent
```

---

### 11. Parallel & Gather

Execute multiple operations in parallel for performance.

#### Simple Parallel Steps

**Syntax:**
```yaml
- parallel:
    - step:
        instruction: "Independent task 1"
    - step:
        instruction: "Independent task 2"
    - step:
        instruction: "Independent task 3"
```

#### Parallel Module Calls

**Syntax:**
```yaml
- parallel:
    module: "path/to/module.yaml"
    parameters_list: "list_of_param_dicts"
    save_results_as: "results_variable"
    max_workers: 8
```

**Example - Parallel web searches:**
```yaml
- step:
    name: "prepare_queries"
    instruction: |
      Generate 10 diverse search queries about {{topic}}.
      Return as JSON array.
    save_as: "queries"

- step:
    name: "prepare_params"
    instruction: |
      Create parameter list for parallel processing.
      For each query in {{queries}}, create:
      [
        {"search_query": "query1", "max_results": 5},
        {"search_query": "query2", "max_results": 5},
        ...
      ]
    save_as: "search_params"

- parallel:
    module: "modules/web_searcher.yaml"
    parameters_list: "search_params"
    save_results_as: "all_search_results"
    max_workers: 5

- step:
    instruction: |
      Aggregate results from {{all_search_results}}.
      Create unified summary.
```

#### Gather Step (Advanced Parallel)

**Syntax:**
```yaml
- gather:
    calls:
      - module: "module1.yaml"
        parameters:
          param1: "value1"
        save_as: "result1"

      - module: "module2.yaml"
        parameters:
          param1: "value2"
        save_as: "result2"

    save_results_as: "all_results"
    max_workers: 4
```

---

### 12. Return

Return a value from a submodule (designed for use in modules called by `call` or `gather`).

**Syntax:**
```yaml
- return: "variable_name"  # Returns the value of variable_name
```

**Example:**
```yaml
name: "calculator_module"
goal: "Perform calculation and return result"

parameters:
  x: "${X}"
  y: "${Y}"

workflow:
  - step:
      instruction: "Calculate {{x}} + {{y}}"
      save_as: "sum"

  - step:
      instruction: "Calculate {{x}} * {{y}}"
      save_as: "product"

  - return: "sum"  # Returns the sum value to parent workflow
```

---

## Template Variables

Template variables use `{{variable_name}}` syntax and allow you to inject dynamic values into instructions.

### Variable Sources

1. **Parameters**: Defined in the YAML file
2. **Context variables**: Set during execution
3. **Loop variables**: Available inside loops
4. **Previous output**: `prev_output` contains the last step's output (not auto-injected into prompts)

### Examples

```yaml
parameters:
  topic: "Machine Learning"
  max_papers: 5
  author: "John Doe"

workflow:
  - step:
      instruction: |
        Search for papers on {{topic}} by {{author}}.
        Limit to {{max_papers}} results.

  - for_each:
      variable: "paper"
      in: "papers"
      steps:
        - step:
            instruction: |
              Analyze {{paper}} in the context of {{topic}}.
              Previous analysis: {{prev_output}}
```

### Escaping and Special Characters

```yaml
- step:
    instruction: |
      Create a JSON object with topic={{topic}}.
      Use triple quotes for strings: """{{topic}}"""
```

---

## Context and Memory Management

### Context Variables

Context is a dictionary available throughout the workflow:

```yaml
workflow:
  - set_variable:
      name: "stage"
      value: "initialization"

  - step:
      instruction: "Current stage: {{stage}}"
      save_as: "stage_output"

  - set_variable:
      name: "stage"
      value: "processing"

  - step:
      instruction: "Now at stage: {{stage}}"
```

### Special Context Variables

- `prev_output`: Output of the previous step
- `task_name`: Name of the current task
- `goal`: Goal of the current task
- `task_output_dir`: Output directory for files

---

### Memory System

The memory system provides persistent storage across workflow steps.

**Memory Operations:**

```yaml
# Store information
memory("store",
       key="unique_key",
       content="content to store",
       tags="tag1,tag2",
       memory_file="{{memory_file}}")

# Retrieve by key
memory("get",
       key="unique_key",
       memory_file="{{memory_file}}")

# Search by tags or content
memory("search",
       query="tag_name",
       memory_file="{{memory_file}}")

# List recent entries
memory("recent",
       limit=5,
       memory_file="{{memory_file}}")

# Get statistics
memory("stats",
       memory_file="{{memory_file}}")
```

**Complete Example:**

```yaml
parameters:
  memory_file: "${EPISODIC_MEMORY_FILE}"

workflow:
  - step:
      instruction: |
        NOTE: Memory file at {{memory_file}}

        Analyze the topic {{topic}} and identify key themes.

        Store findings:
        memory("store",
               key="initial_analysis",
               content="[analysis text]",
               tags="analysis,themes",
               memory_file="{{memory_file}}")

  - for_each:
      variable: "paper"
      in: "papers"
      steps:
        - step:
            instruction: |
              Analyze {{paper}}.

              Store detailed notes:
              memory("store",
                     key="paper_{{paper}}",
                     content="[detailed analysis]",
                     tags="paper,analysis,{{paper}}",
                     memory_file="{{memory_file}}")

  - step:
      name: "create_report"
      instruction: |
        Retrieve all stored analyses:
        memory("search",
               query="analysis",
               memory_file="{{memory_file}}")

        Create comprehensive report using all stored information.
        Write the report to final_report.md in the output directory.
```

**Memory Best Practices:**

1. **Use specific keys**: Include identifiers like depth, branch, or iteration
   ```yaml
   key="analysis_d{{depth}}_b{{branch}}_i{{iteration}}"
   ```

2. **Tag strategically**: Use multiple tags for flexible retrieval
   ```yaml
   tags="learnings,depth{{depth}},branch{{branch}},important"
   ```

3. **Search efficiently**: Use targeted queries
   ```yaml
   # Get all learnings from depth 2
   memory("search", query="learnings depth2", memory_file="{{memory_file}}")
   ```

4. **Avoid context overflow**: Store large content in memory instead of context
   ```yaml
   - step:
       instruction: |
         Analyze large document.
         Store full analysis in memory.
         Return only brief summary to context.
   ```

---

## Tool Filtering

You can restrict which tools are available to the agent at different levels of the workflow hierarchy. This is useful for:
- Limiting agent capabilities for specific tasks
- Reducing cognitive load by removing irrelevant tools

### Plan-Level Tool Filtering

Restrict tools for the entire workflow using the `config` section:

```yaml
name: "read_only_analysis"
goal: "Analyze files without modifying them"

config:
  enabled_tools: ["fs_read", "web_search", "memory"]

workflow:
  - step:
      name: "analyze"
      instruction: "Read and analyze the project files"
```

### Step-Level Tool Filtering

Restrict tools for individual steps by adding `enabled_tools` to the step:

```yaml
workflow:
  - step:
      name: "research"
      instruction: "Search the web for information"
      enabled_tools: ["web_search"]

  - step:
      name: "write_report"
      instruction: "Write the findings to a file"
      enabled_tools: ["fs_write"]
```

### Combining Plan and Step Filtering

When both plan-level and step-level filtering are specified, the **intersection** is used. Step-level can only further restrict, not expand beyond plan-level:

```yaml
name: "restricted_workflow"
goal: "Demonstrate hierarchical tool filtering"

config:
  enabled_tools: ["fs_read", "fs_write", "web_search"]

workflow:
  # This step only has fs_read (intersection of plan and step)
  - step:
      name: "read_only"
      instruction: "Read the config file"
      enabled_tools: ["fs_read", "browser_navigate"]  # browser_navigate not in plan, ignored

  # This step has all plan-level tools (no step restriction)
  - step:
      name: "full_access"
      instruction: "Read, write, or search as needed"
```

### Tool Filtering in Submodules

Submodules are **independent workflows** - they manage their own tool filtering via their own `config` section. The parent's `enabled_tools` does **not** flow into submodules:

**main.yaml:**
```yaml
name: "main_workflow"
config:
  enabled_tools: ["fs_read"]  # Only affects steps in THIS file

workflow:
  - step:
      name: "read_data"
      instruction: "Read input"

  - call:
      module: "modules/writer.yaml"  # Has its own tool config
```

**modules/writer.yaml:**
```yaml
name: "writer_module"
config:
  enabled_tools: ["fs_read", "fs_write"]  # Independent - not restricted by parent

workflow:
  - step:
      name: "write_output"
      instruction: "Write the processed data"
```

### Submodules as Tools (Function Calls)

You can expose submodules as callable tools so the agent can invoke them like normal functions. Define which submodules are available at the top of the workflow, and add a `function` declaration inside each submodule file.

**Main workflow:**
```yaml
name: "main_workflow"
goal: "Use submodules as tools"

config:
  enabled_submodules: ["math_add", "echo_context"]  # optional plan-level filter

submodules:
  - name: math_add
    path: ./submodules/math_add.yaml
  - name: echo_context
    path: ./submodules/echo_context.yaml

workflow:
  - step:
      name: "call_math_add"
      enabled_submodules: ["math_add"]  # optional step-level filter
      instruction: |
        Call the tool `math_add` with a=2 and b=3.
        Return the tool result only.
```

**Submodule with function declaration:**
```yaml
name: "math_add"
goal: "Add two numbers"

function:
  name: "math_add"
  description: "Add two numbers and return the sum."
  parameters:
    model:
      - name: "a"
        type: "number"
        description: "First number"
        required: true
      - name: "b"
        type: "number"
        description: "Second number"
        required: true
    context:
      - name: "request_id"
        type: "string"
        description: "Optional request id from parent context"
  return: "sum"

workflow:
  - step:
      name: "compute_sum"
      instruction: |
        Add the two numbers and return ONLY the numeric sum.
        a={{a}}
        b={{b}}
      save_as: "sum"
  - return: "sum"
```

**Notes:**
- `submodules` are declared at the top-level of the main YAML. Paths are relative to that YAML file.
- The `function.parameters.model` list defines inputs the agent must fill when calling the tool.
- The `function.parameters.context` list defines context values injected by the parent workflow (if present).
- `enabled_submodules` works like tool filtering: plan-level + step-level are intersected.

### Supported Step Types

Tool filtering works with all LLM-based step types:
- `step`
- `task`

### Available Tools

The exact tools available depend on your MCP server configuration. Common tools include:
- `fs_read` - Read files
- `fs_write` - Write files
- `web_search` - Search the web
- `browser_navigate` - Browse websites
- `memory` - Persistent memory operations
- `code_execute` - Run code

To see all available tools, check the agent logs at startup.

---

## Advanced Features

### 1. Multi-Level Parallelization

Execute nested parallel operations for maximum performance.

**Example - 3-Level Parallel Deep Research:**

```yaml
name: "parallel_deep_research"
goal: "Multi-level parallel research pipeline"

parameters:
  user_queries: ["query1", "query2", "query3"]
  max_user_query_workers: 8
  max_serp_workers: 4
  max_content_workers: 5

workflow:
  # Level 1: Parallel user queries
  - parallel:
      module: "modules/process_user_query.yaml"
      parameters_list: "user_query_params"
      save_results_as: "user_results"
      max_workers: "max_user_query_workers"
```

**process_user_query.yaml:**
```yaml
name: "process_user_query"
parameters:
  user_query: "${USER_QUERY}"
  max_serp_workers: "${MAX_SERP_WORKERS}"

workflow:
  - step:
      instruction: "Generate SERP queries for {{user_query}}"
      save_as: "serp_queries"

  # Level 2: Parallel SERP queries
  - parallel:
      module: "modules/process_serp.yaml"
      parameters_list: "serp_params"
      save_results_as: "serp_results"
      max_workers: "max_serp_workers"

  - return: "serp_results"
```

---

### 2. Dynamic Parameter Lists

Build parameter lists dynamically for parallel execution.

```yaml
- set_variable:
    name: "params_list"
    value: "[]"

- for_each:
    variable: "item"
    in: "items"
    steps:
      - step:
          instruction: |
            Create parameter dict for {{item}}:
            [{"item_id": "{{item}}", "config": "{{config}}"}]
            Return ONLY the JSON array.
          save_as: "param_json"

      - set_variable:
          name: "params_list"
          value: "{{params_list}} + {{param_json}}"

- parallel:
    module: "modules/processor.yaml"
    parameters_list: "params_list"
    save_results_as: "results"
    max_workers: 10
```

---

### 3. Hierarchical Modules

Create reusable module hierarchies.

```
workflows/
├── main_workflow.yaml
└── modules/
    ├── level1_module.yaml
    └── level2_module.yaml
```

**main_workflow.yaml:**
```yaml
workflow:
  - call:
      module: "modules/level1_module.yaml"
      parameters:
        data: "{{input_data}}"
```

**modules/level1_module.yaml:**
```yaml
workflow:
  - step:
      instruction: "Process data at level 1"

  - call:
      module: "modules/level2_module.yaml"
      parameters:
        processed_data: "{{prev_output}}"
```

---

### 4. Error Recovery Patterns

**Using If-Then:**
```yaml
- step:
    name: "perform_operation"
    instruction: "Perform complex operation"
    save_as: "result"

- step:
    name: "check_quality"
    instruction: |
      Evaluate the quality of {{result}}.
      Return a score from 0.0 to 1.0.
    save_as: "quality_score"

- if:
    condition: "quality_score < 0.7"
    then:
      - step:
          instruction: "Improve quality based on score {{quality_score}}"
          save_as: "result"
      - step:
          name: "recheck_quality"
          instruction: |
            Re-evaluate the quality of {{result}}.
            Return a score from 0.0 to 1.0.
          save_as: "quality_score"
```

---

### 5. Iterative Refinement

```yaml
parameters:
  max_iterations: 3
  current_iteration: 0
  quality_threshold: 0.8

workflow:
  - step:
      instruction: "Generate initial draft"
      save_as: "draft"

  - while:
      condition: "current_iteration < max_iterations"
      steps:
        - step:
            name: "evaluate_quality"
            instruction: |
              Evaluate the draft quality on a scale of 0.0 to 1.0.
              Return ONLY the numeric score.
            save_as: "quality"

        - if:
            condition: "quality >= quality_threshold"
            then:
              - step:
                  instruction: "Quality sufficient, breaking loop"
              - set_variable:
                  name: "current_iteration"
                  value: "{{max_iterations}}"  # Force exit
            else:
              - step:
                  instruction: |
                    Improve draft based on quality score {{quality}}.
                    Focus on weak areas.
                  save_as: "draft"

              - increment: "current_iteration"
```

---

## Complete Examples

### Example 1: Simple Research Report

```yaml
name: "simple_research"
goal: "Research a topic and create a report"

parameters:
  topic: "${RESEARCH_TOPIC}"
  max_sources: 5

workflow:
  # Step 1: Search for information
  - step:
      name: "web_search"
      instruction: |
        Search for information about {{topic}}.
        Find {{max_sources}} high-quality sources.
        Return a list of URLs and brief descriptions.
      save_as: "sources"

  # Step 2: Extract URLs for iteration
  - step:
      name: "extract_urls"
      instruction: |
        From {{sources}}, extract all URLs as a clean JSON array.
        Return ONLY the JSON array.
      save_as: "source_urls"

  # Step 3: Analyze each source
  - for_each:
      variable: "url"
      in: "source_urls"
      steps:
        - step:
            name: "analyze_source"
            instruction: |
              Read and analyze content from {{url}}.
              Extract:
              1. Main points relevant to {{topic}}
              2. Key data or statistics
              3. Unique insights
              Write 200-300 words.

  # Step 4: Create final report
  - step:
      name: "final_report"
      instruction: |
        Based on all source analyses, write a comprehensive report on {{topic}}.

        Structure:
        - Executive Summary (200 words)
        - Detailed Findings (800 words)
        - Conclusions (200 words)

        Total target: 1200 words.
        Write the report to research_report.md in the output directory.
```

---

### Example 2: Interactive Multi-Stage Research

```yaml
name: "interactive_research"
goal: "Research with user clarification and iterative deepening"

parameters:
  topic: "${RESEARCH_TOPIC}"
  max_depth: 3
  current_depth: 0
  breadth: 4

workflow:
  # Phase 1: Clarify with user
  - step:
      name: "generate_questions"
      instruction: |
        Given topic: {{topic}}
        Generate 3 clarifying questions.
        Return as JSON array.
      save_as: "questions_json"

  - step:
      name: "parse_questions"
      instruction: |
        Parse the questions from {{questions_json}}.
        Return as a clean JSON array of strings.
      save_as: "questions"

  - for_each:
      variable: "question"
      in: "questions"
      steps:
        - input:
            prompt: "{{question}}"
            save_as: "answer"

        - step:
            instruction: |
              Store Q&A:
              Q: {{question}}
              A: {{answer}}
              Return confirmation.

  - step:
      name: "create_enhanced_query"
      instruction: |
        Combine original topic {{topic}} with user answers.
        Create enhanced research query.
      save_as: "enhanced_query"

  # Phase 2: Iterative deepening
  - set_variable:
      name: "current_queries"
      value: '["{{enhanced_query}}"]'

  - while:
      condition: "current_depth < max_depth"
      steps:
        - step:
            instruction: |
              For queries: {{current_queries}}
              Generate {{breadth}} search queries per query.
              Return as JSON array.
          save_as: "search_queries_json"

        - step:
            name: "parse_search_queries"
            instruction: |
              Parse the queries from {{search_queries_json}}.
              Return as a clean JSON array of strings.
            save_as: "search_queries"

        - for_each:
            variable: "query"
            in: "search_queries"
            limit: "{{breadth}}"
            steps:
              - step:
                  instruction: |
                    Search: {{query}}
                    Extract key learnings.
                    Return 2-3 insights.

        - step:
            instruction: |
              Based on learnings at depth {{current_depth}},
              generate follow-up queries.
              Return as JSON array.
          save_as: "next_queries_json"

        - step:
            name: "parse_next_queries"
            instruction: |
              Parse the queries from {{next_queries_json}}.
              Return as a clean JSON array of strings.
            save_as: "current_queries"

        - set_variable:
            name: "breadth"
            value: "max({{breadth}} // 2, 1)"

        - increment: "current_depth"

  # Phase 3: Create report
  - step:
      name: "deep_research_report"
      instruction: |
        Create comprehensive report using all learnings.
        Target: 2000+ words.
        Write the report to deep_research_report.md in the output directory.
```

---

### Example 3: Parallel Processing Pipeline

```yaml
name: "parallel_analysis"
goal: "Analyze multiple datasets in parallel"

parameters:
  datasets: ["data1", "data2", "data3", "data4", "data5"]
  max_workers: 3

workflow:
  # Prepare parameters for parallel processing
  - step:
      name: "prepare_params"
      instruction: |
        Create parameter list for datasets: {{datasets}}
        Format:
        [
          {"dataset_id": "data1", "config": "standard"},
          {"dataset_id": "data2", "config": "standard"},
          ...
        ]
        Return ONLY JSON array.
      save_as: "params_list"

  # Process all datasets in parallel
  - parallel:
      module: "modules/dataset_analyzer.yaml"
      parameters_list: "params_list"
      save_results_as: "all_results"
      max_workers: "max_workers"

  # Aggregate results
  - step:
      instruction: |
        Aggregate results from {{all_results}}.
        Compute:
        - Overall statistics
        - Trends across datasets
        - Anomalies or outliers

  # Generate visualizations
  - step:
      instruction: |
        Create visualizations for aggregated results.
        Generate:
        1. Summary charts
        2. Comparison plots
        3. Trend analysis

  # Create report
  - step:
      name: "analysis_report"
      instruction: |
        Write comprehensive analysis report.
        Include all visualizations and findings.
        Write the report to parallel_analysis_report.md in the output directory.
```

**modules/dataset_analyzer.yaml:**
```yaml
name: "dataset_analyzer"
goal: "Analyze a single dataset"

parameters:
  dataset_id: "${DATASET_ID}"
  config: "${CONFIG}"

workflow:
  - step:
      instruction: |
        Load dataset {{dataset_id}} with config {{config}}.
        Perform statistical analysis.
      save_as: "stats"

  - step:
      instruction: |
        Identify patterns in {{dataset_id}}.
        Return key insights.
      save_as: "insights"

  - step:
      instruction: |
        Create summary:
        {
          "dataset": "{{dataset_id}}",
          "stats": {{stats}},
          "insights": {{insights}}
        }
        Return ONLY JSON.

  - return: "prev_output"
```

---

## Best Practices

### 1. Clear Naming and Documentation

```yaml
# Good
- step:
    name: "extract_arxiv_papers_metadata"
    instruction: |
      Search arXiv for papers on {{topic}}.
      For each paper, extract:
      - Title
      - Authors
      - Abstract
      - arXiv ID
      Return as structured JSON array.

# Avoid
- step:
    name: "process"
    instruction: "Do stuff with {{topic}}"
```

---

### 2. Modular Design

Break complex workflows into reusable modules:

```yaml
# Main workflow
workflow:
  - call:
      module: "modules/data_collection.yaml"
      save_as: "raw_data"

  - call:
      module: "modules/data_processing.yaml"
      parameters:
        input_data: "{{raw_data}}"
      save_as: "processed_data"

  - call:
      module: "modules/report_generation.yaml"
      parameters:
        data: "{{processed_data}}"
```

---

### 3. Error Handling

Always include validation for critical steps:

```yaml
- step:
    instruction: "Perform critical operation"
    save_as: "result"

- step:
    name: "check_result"
    instruction: |
      Check whether {{result}} is valid:
      - Result is not empty
      - Result contains required fields
      Return "pass" or "fail".
    save_as: "check_status"

- if:
    condition: "check_status == fail"
    then:
      - step:
          instruction: "Log error and retry with different approach"
```

---

### 4. Memory Management

Use memory for large data to avoid context overflow:

```yaml
# Good - Store in memory
- step:
    instruction: |
      Analyze large document.
      Store in memory:
      memory("store",
             key="doc_analysis",
             content="[full analysis]",
             memory_file="{{memory_file}}")
      Return only: "Analysis complete, stored in memory"

# Avoid - Overloading context
- step:
    instruction: "Return full 10,000 word analysis here"
```

---

### 5. Progressive Detail

Start broad, then narrow focus:

```yaml
workflow:
  - step:
      instruction: "Identify top 10 relevant areas for {{topic}}"
      save_as: "areas"

  - step:
      instruction: |
        From {{areas}}, select top 3 most important.
        Justify selection.
      save_as: "priority_areas"

  - for_each:
      variable: "area"
      in: "priority_areas"
      steps:
        - step:
            instruction: "Deep dive into {{area}}"
```

---

### 6. Explicit Instructions

Be specific about desired outputs:

```yaml
# Good
- step:
    instruction: |
      Search for Python testing frameworks.
      Return ONLY a JSON array of framework names:
      ["pytest", "unittest", "nose2"]
      No explanations or extra text.

# Avoid
- step:
    instruction: "Find Python testing frameworks"
```

---

### 7. Use Limits

Prevent runaway loops:

```yaml
- while:
    condition: "quality < threshold"
    max_iterations: 5  # Always set a limit
    steps:
      - step:
          instruction: "Improve quality"
```

---

### 8. Organize File Structure

```
workflows/
├── main_task.yaml
├── modules/
│   ├── data_collector.yaml
│   ├── analyzer.yaml
│   └── reporter.yaml
└── outputs/
    └── main_task/
        ├── agent_run.log
        ├── final_report.md
        └── step-*.txt
```

---

## Running Your Workflows

### Basic Execution

```bash
bash ./scripts/run_agent.sh workflows/my_task.yaml
```

### Configuration

Model and agent settings go in the YAML `config:` section:

```yaml
config:
  model: "gpt-4o"
  max_tokens_per_step: 120000
  max_tool_calls_per_step: 10
  temperature: 0.7
  plan_revision_max_steps: 0
```

API keys and base URLs should be set in `config/vm.env` or exported in your shell:

```bash
export OPENAI_API_KEY=your-key-here
```

### Output Files

After execution, find outputs in:
```
workspace/outputs/[task_name]/
├── agent_run.log          # Detailed execution log
├── step-1-output.txt      # Output of step 1
├── step-2-output.txt      # Output of step 2
├── ...
├── final-output.txt       # Final workflow output
└── [custom output files]  # Files created by workflow steps
```

### Monitoring Execution

```bash
# Watch the log file during execution
tail -f workspace/outputs/[task_name]/agent_run.log

# Check memory usage
cat workspace/outputs/[task_name]/memory.json
```

### Common Issues

**Issue: Variables not expanding**
```yaml
# Wrong
instruction: "Process $TOPIC"

# Correct
instruction: "Process {{topic}}"
```

**Issue: Module not found**
```yaml
# Use relative paths from project root
module: "workflows/modules/my_module.yaml"
```

**Issue: Memory not persisting**
```yaml
# Always specify memory_file parameter
parameters:
  memory_file: "${EPISODIC_MEMORY_FILE}"

# And use it in memory operations
memory("store", key="...", content="...", memory_file="{{memory_file}}")
```

---

## Summary

The YAML Task Language provides a powerful way to define complex, multi-step workflows for AI agents. Key takeaways:

1. **Start Simple**: Begin with basic steps and gradually add complexity
2. **Use Modules**: Break complex tasks into reusable modules
3. **Leverage Parallelism**: Use parallel execution for independent operations
4. **Manage Memory**: Use the memory system for large data and context persistence
5. **Verify**: Include verification and error recovery in critical workflows
6. **Document**: Use clear names and instructions

For more examples, explore the `workflows/` directory in the repository.

---

## Quick Reference Card

```yaml
# Basic step
- step:
    name: "step_name"
    instruction: "What to do"
    save_as: "variable"

# Loop
- for_each:
    variable: "item"
    in: "list"
    steps: [...]

# While loop
- while:
    condition: "x < 10"
    steps: [...]

# Conditional
- if:
    condition: "x == value"
    then: [...]
    else: [...]

# Variables
- set_variable:
    name: "var"
    value: "value"

- increment: "counter"

# Input
- input:
    prompt: "Question?"
    save_as: "answer"

# Memory
memory("store", key="k", content="c", tags="t", memory_file="{{memory_file}}")
memory("get", key="k", memory_file="{{memory_file}}")
memory("search", query="tag", memory_file="{{memory_file}}")

# Modules
- call:
    module: "path.yaml"
    parameters: {...}
    save_as: "result"

# Parallel
- parallel:
    module: "mod.yaml"
    parameters_list: "params"
    max_workers: 5

# Return (in modules)
- return: "variable"

# Tool filtering (plan-level)
config:
  enabled_tools: ["fs_read", "fs_write"]

# Tool filtering (step-level)
- step:
    name: "restricted"
    instruction: "..."
    enabled_tools: ["fs_read"]

# Tool filtering (submodule-level)
# Use config.enabled_tools in the module file (top-level enabled_tools is ignored)
module: "modules/writer.yaml"
```

---

## Additional Resources

- **Examples**: Explore the [workflows/](../workflows/) directory for real-world examples
- **Source Code**: Browse [src/harness/](../src/harness/) for the execution engine

Happy workflow building! 🚀
