# Node Reference — YAML Mapping

This document lists each **node type** in the YAML Flow Editor, its **YAML key** in the workflow `workflow`, and the **fields** you can edit in the right panel or in YAML.

The workflow root has: `name`, `goal`, `config`, `parameters`, and `workflow` (a list of steps). Each step is a single key–value pair (e.g. `step: { ... }`, `if: { ... }`).

---

## Start / End

- **Graph**: Special nodes "Start" and "End" bracket the workflow. They are not workflow steps.
- **YAML**: No direct key. The converter walks from Start along edges to build the linear `workflow` list; End marks the end of the main flow.

---

## Task (Stateless)

- **YAML key**: `task`
- **Panel fields**: Name, Instruction, Save as
- **Behavior**: Each task starts a fresh conversation — no memory of prior tasks or steps.

```yaml
- task:
    name: "task_name"
    instruction: "What the agent should do"
    save_as: "result_key"      # optional: save output in context
```

---

## Step (Conversation History)

- **YAML key**: `step`
- **Panel fields**: Name, Instruction, Save as, Output file
- **Behavior**: Steps share a workflow-level conversation history. The LLM remembers all prior step exchanges.

```yaml
- step:
    name: "step_name"
    instruction: "What the agent should do"
    save_as: "result_key"      # optional: save output in context
    output_file: "path.txt"    # optional
```

---

## If

- **YAML key**: `if`
- **Panel fields**: Condition; nested **then** and **else** branches (each is a list of steps, edited as inner steps or subgraph).

```yaml
- if:
    condition: "{{some_var}} == 'value'"
    then:
      - step: { name: "then_step", instruction: "..." }
    else:
      - step: { name: "else_step", instruction: "..." }
```

---

## While

- **YAML key**: `while`
- **Panel fields**: Condition, Max iterations; nested **steps** (loop body).

```yaml
- while:
    condition: "{{counter}} < 10"
    max_iterations: 100
    steps:
      - step: { name: "loop_body", instruction: "..." }
```

---

## For Each

- **YAML key**: `for_each`
- **Panel fields**: Variable name, **in** (expression or list), Max iterations; nested **steps**.

```yaml
- for_each:
    variable: "item"
    in: "{{items_list}}"   # or a YAML list
    max_iterations: 50
    steps:
      - step: { name: "process_item", instruction: "..." }
```

---

## Switch

- **YAML key**: `switch`
- **Panel fields**: Variable; **cases** (map of value → step list); optional **default** step list.

```yaml
- switch:
    variable: "{{choice}}"
    cases:
      "a":
        - step: { name: "case_a", instruction: "..." }
      "b":
        - step: { name: "case_b", instruction: "..." }
    default:
      - step: { name: "default_step", instruction: "..." }
```

---

## Gather

- **YAML key**: `gather`
- **Panel fields**: Two modes:
  - **Format 1**: **calls** — list of `{ module, parameters?, save_as? }`.
  - **Format 2**: **module** + **parameters_list** (same module, different params); optional **save_as_prefix** / **save_as_list**.
  - Common: **save_results_as**, **max_workers**.

```yaml
# Format 1: different modules
- gather:
    calls:
      - module: "workflows/modules/web_search.yaml"
        parameters: { search_query: "A" }
        save_as: "result_a"
      - module: "workflows/modules/web_search.yaml"
        parameters: { search_query: "B" }
        save_as: "result_b"
    save_results_as: "search_results"
    max_workers: 4

# Format 2: same module, different parameters
- gather:
    module: "workflows/modules/delay_module.yaml"
    parameters_list: [{ delay_seconds: "1" }, { delay_seconds: "2" }]
    save_as_prefix: "delay"
    save_results_as: "delays"
```

---

## Parallel

- **YAML key**: `parallel`
- **Panel fields**: Module, **parameters_list** (array of param objects or context variable name), Save results as, Max workers.

```yaml
- parallel:
    module: "workflows/modules/delay_module.yaml"
    parameters_list: [{ delay_seconds: "1" }, { delay_seconds: "2" }]
    save_results_as: "outputs"
    max_workers: 4
```

---

## Call

- **YAML key**: `call`
- **Panel fields**: Module path, Parameters (YAML object), Save as.

```yaml
- call:
    module: "workflows/modules/web_search.yaml"
    parameters:
      search_query: "{{query}}"
      max_results: "5"
    save_as: "search_result"
```

You can drag a **module** from the sidebar onto the canvas to create a Call node pre-filled with that module path and default parameters.

---

## Input

- **YAML key**: `input`
- **Panel fields**: Prompt (text shown to user), Save as (context variable), Default (optional).

```yaml
- input:
    prompt: "Enter your name"
    save_as: "user_name"
    default: "Guest"
```

---

## Return

- **YAML key**: `return`
- **Panel fields**: Variable (context variable name to return).

```yaml
- return: "result_key"
# or
- return:
    variable: "result_key"
```

---

## Set Variable

- **YAML key**: `set_variable`
- **Panel fields**: Name (variable name), Value (YAML value).

```yaml
- set_variable:
    name: "counter"
    value: 0
```

---

## Increment

- **YAML key**: `increment`
- **Panel fields**: Variable (name of counter to increment).

```yaml
- increment: "counter"
```

---

## Summary table

| Node type   | YAML key       | Main fields | Behavior |
|------------|-----------------|------------|----------|
| Task       | `task`          | name, instruction, save_as | Stateless (fresh conversation) |
| Step       | `step`          | name, instruction, save_as, output_file | Conversation history preserved |
| If         | `if`            | condition, then, else | |
| While      | `while`         | condition, max_iterations, steps |
| For Each   | `for_each`      | variable, in, max_iterations, steps |
| Switch     | `switch`        | variable, cases, default |
| Gather     | `gather`        | calls **or** module+parameters_list; save_results_as, max_workers |
| Parallel   | `parallel`      | module, parameters_list, save_results_as, max_workers |
| Call       | `call`          | module, parameters, save_as |
| Input      | `input`         | prompt, save_as, default |
| Return     | `return`        | variable (or scalar string) |
| Set Variable | `set_variable` | name, value |
| Increment  | `increment`     | variable (scalar string) |

For the full task language (parameters, template variables, tools, etc.), see the [Workflow Language Guide](../../docs/workflow-language.md).
