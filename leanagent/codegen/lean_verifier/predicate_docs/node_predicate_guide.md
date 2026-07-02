# Node Predicate Annotation Guide

> Back to [index](index.md)

This document describes **how to write predicates for each node type** in the IR JSON so that `TaskPlanToLean.py` can generate correct Lean4 semantic verification code.

---

## Table of Contents

1. [Overview: How Predicates Flow Through Nodes](#1-overview)
2. [Regular Step Node](#2-regular-step-node)
3. [Conditional Node (`conditional`)](#3-conditional-node)
4. [While Loop Node (`whileLoop`)](#4-while-loop-node)
5. [ForEach Loop Node (`forEachLoop`)](#5-foreach-loop-node)
6. [Other Deterministic Nodes](#6-other-deterministic-nodes)
7. [SemanticWorkflowGraph Assembly](#7-semanticworkflowgraph-assembly)
8. [Common Pitfalls](#8-common-pitfalls)

---

## 1. Overview

### Predicate Placement in IR JSON

Every `NodeIR` has two categories of predicate locations:

| Location | Purpose | Lean Destination |
| --- | --- | --- |
| `reads[i].predicates` | What each read variable must satisfy | `precondVariables` |
| `writes[i].predicates` | What each write variable guarantees | `postcondVariables` |
| `precond_extra` | Additional preconditions (tools, modules) | `precondVariables` (prepended) |
| `postcond_extra` | Additional postconditions | `postcondVariables` (appended) |

### How `TaskPlanToLean.py` Collects Predicates

```python
# From NodeIR.collect_precond():
precond = precond_extra + [read.predicates for read in reads]  # deduplicated

# From NodeIR.collect_postcond():
postcond = [write.predicates for write in writes] + postcond_extra  # deduplicated
```

### Different Node Types → Different Lean Structures

| Node `step_type` | Lean Structure | `def` Name Pattern | Goes Into |
| --- | --- | --- | --- |
| `step`, `task` | `SemanticWorkflowNode` | `prefix_semNode{id}` | `semanticNodes` |
| `setVariable` | `SemanticWorkflowNode` | `prefix_semNode{id}` | `semanticNodes` |
| `incrementVariable` | `SemanticWorkflowNode` | `prefix_semNode{id}` | `semanticNodes` |
| `returnValue` | `SemanticWorkflowNode` | `prefix_semNode{id}` | `semanticNodes` |
| `conditional` | `SemanticConditionalNode` | `prefix_condNode{id}` | `conditionalNodes` |
| `whileLoop` | `SemanticLoopNode` | `prefix_loopNode{id}` | `loopNodes` |
| `forEachLoop` | `SemanticForEachLoopNode` | `prefix_loopNode{id}` | `loopNodes` |

> **Key insight**: Conditional and Loop nodes each have **two `def`s** — a specialized node (`_condNode` / `_loopNode`) and a conversion to `SemanticWorkflowNode` (`_semNode`) via `.toSemanticWorkflowNode`.

---

## 2. Regular Step Node

The simplest node type. Only needs `reads.predicates`, `writes.predicates`, and optionally `precond_extra`.

### IR JSON

```json
{
  "id": 0,
  "name": "extract_paper_title",
  "step_type": "step",
  "reads": [
    {
      "name": "file_path", "base_type": "TString",
      "predicates": [{"kind": "isValidFilePath"}]
    }
  ],
  "writes": [
    {
      "name": "paper_title", "base_type": "TString",
      "predicates": [{"kind": "isNonEmptyString"}]
    }
  ],
  "instruction": "...",
  "precond_extra": [
    { "var_name": "file_path", "predicate": {"kind": "isValidFilePath"} },
    { "var_name": "fs_read", "predicate": {"kind": "toolExists"} }
  ]
}
```

### Generated Lean

```lean
def prefix_semNode0 : SemanticWorkflowNode := {
  baseNode := prefix_node0
  precondVariables := [
    varIsValidFilePath "file_path",
    varIsValidTool "fs_read"
  ]
  postcondVariables := [
    varIsNonEmptyString "paper_title"
  ]
}
```

### Codegen Logic

`_gen_semantic_node()` detects `is_conditional == False` and `is_loop == False`, and generates a plain `SemanticWorkflowNode`.

---

## 3. Conditional Node

A conditional node (`step_type: "conditional"`) models an `if-else` branch. It needs **branch-specific postconditions** so the verifier knows different facts hold on each branch.

### Lean Structure

```lean
structure SemanticConditionalNode extends SemanticWorkflowNode where
  thenTargetId : NodeId                                    -- first node of then-branch
  elseTargetId : NodeId                                    -- first node of else-branch
  thenPostcondVariables : List VariablePredicateRequirement -- facts when condition = TRUE
  elsePostcondVariables : List VariablePredicateRequirement -- facts when condition = FALSE
```

### Two `def`s Generated

```lean
-- 1. The specialized conditional node
def prefix_condNode3 : SemanticConditionalNode := { ... }

-- 2. Conversion to SemanticWorkflowNode (for the semanticNodes list)
def prefix_semNode3 : SemanticWorkflowNode := prefix_condNode3.toSemanticWorkflowNode
```

### IR JSON — Required Fields

```json
{
  "id": 3,
  "name": "check_abstract == None",
  "step_type": "conditional",
  "reads": [
    {
      "name": "abstract", "base_type": "TString",
      "predicates": [{"kind": "nameExists"}]
    }
  ],
  "writes": [],
  "then_target_id": 4,
  "else_target_id": 5,
  "then_postcond": [
    { "var_name": "abstract", "predicate": {"kind": "nameExists"} }
  ],
  "else_postcond": [
    { "var_name": "abstract", "predicate": {"kind": "isNonEmptyString"} }
  ]
}
```

### Field Reference

| IR JSON Field | Type | Required | Lean Field |
| --- | --- | --- | --- |
| `then_target_id` | `int` | ✅ | `thenTargetId` |
| `else_target_id` | `int` | ✅ | `elseTargetId` |
| `then_postcond` | `list[VarPredicateIR]` | ✅ | `thenPostcondVariables` |
| `else_postcond` | `list[VarPredicateIR]` | ✅ | `elsePostcondVariables` |
| `reads[].predicates` | `list[PredicateIR]` | ✅ | `precondVariables` (via `collect_precond`) |

> `then_target_id` / `else_target_id` must match the `then_entry` / `else_entry` values in the corresponding `branch` edge.

### Generated Lean (Complete)

```lean
-- Semantic Node 3: conditional "check_abstract == None"
def prefix_condNode3 : SemanticConditionalNode := {
  baseNode := prefix_node3
  precondVariables := [varNameExists "abstract"]
  postcondVariables := []
  thenTargetId := prefix_nodeId4
  elseTargetId := prefix_nodeId5
  thenPostcondVariables := [varNameExists "abstract"]
  elsePostcondVariables := [varIsNonEmptyString "abstract"]
}
def prefix_semNode3 : SemanticWorkflowNode := prefix_condNode3.toSemanticWorkflowNode
```

### How to Choose Branch Predicates

| Pattern | `then_postcond` (condition TRUE) | `else_postcond` (condition FALSE) |
| --- | --- | --- |
| `check X == None` | `nameExists X` (weak — X may be None) | `isNonEmptyString X` (strong — X is not None) |
| `check X == "PASS"` | `containsSubstring X "PASS"` | `nameExists X` |
| `check X == true` | `nameExists X` | `nameExists X` |
| `check X > 0` | `isInt X` | `isInt X` |

**Principle**: The else branch is the **negation** of the condition. If the condition checks for a "bad" state (e.g., `== None`), the else branch gives you the stronger guarantee.

### Graph Assembly

The conditional node must appear in **both** `semanticNodes` (via `.toSemanticWorkflowNode`) and `conditionalNodes`:

```lean
def prefixSemanticGraph : SemanticWorkflowGraph := {
  ...
  semanticNodes := [..., prefix_semNode3, ...]   -- uses converted version
  conditionalNodes := [prefix_condNode3]          -- uses original
  ...
}
```

---

## 4. While Loop Node

A while loop (`step_type: "whileLoop"`) requires a **loop invariant**, a **termination specification**, and **exit postconditions**. This follows Hoare logic: when the loop exits, the exit facts equal `loopInvariant ∧ exitPostconditions`.

### Lean Structure

```lean
structure SemanticLoopNode extends SemanticWorkflowNode where
  loopInvariant : List VariablePredicateRequirement
  terminationSpec : LoopTerminationSpec
  exitPostconditions : List VariablePredicateRequirement := []
```

### Termination Spec Types

```lean
inductive LoopTerminationSpec where
  | finiteCondition (terminationVars : List String)
  | llmControlledExit (potentialExitNodeId : NodeId) (sentinelPattern : String)
  | externalTermination (mechanism : String)
  | allowUnbounded (justification : String)
```

### Two `def`s Generated

```lean
-- 1. The specialized loop node
def prefix_loopNode2 : SemanticLoopNode := { ... }

-- 2. Conversion to SemanticWorkflowNode (for the semanticNodes list)
def prefix_semNode2 : SemanticWorkflowNode := prefix_loopNode2.toSemanticWorkflowNode
```

### IR JSON — Required Fields

```json
{
  "id": 2,
  "name": "while_iter <= max_iters",
  "step_type": "whileLoop",
  "reads": [
    { "name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}] },
    { "name": "max_iters", "base_type": "TInt", "predicates": [{"kind": "isInt"}] },
    { "name": "solved", "base_type": "TBool", "predicates": [{"kind": "nameExists"}] }
  ],
  "writes": [],
  "loop_invariant": [
    { "var_name": "code_path", "predicate": {"kind": "isValidFilePath"} },
    { "var_name": "memory_file", "predicate": {"kind": "isValidFilePath"} },
    { "var_name": "operation_rule", "predicate": {"kind": "isNonEmptyString"} },
    { "var_name": "iter", "predicate": {"kind": "isInt"} },
    { "var_name": "term_send", "predicate": {"kind": "toolExists"} },
    { "var_name": "term_read", "predicate": {"kind": "toolExists"} },
    { "var_name": "memory", "predicate": {"kind": "toolExists"} }
  ],
  "termination_kind": "llmControlledExit",
  "termination_exit_node": 7,
  "termination_sentinel": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
  "exit_postcond": [
    { "var_name": "final_output", "predicate": {"kind": "containsSubstring", "substring": "COMPLETE_TASK_AND_SUBMIT"} },
    { "var_name": "task_status", "predicate": {"kind": "taskCompleted"} }
  ]
}
```

### Field Reference

| IR JSON Field | Type | Required | Lean Field |
| --- | --- | --- | --- |
| `loop_invariant` | `list[VarPredicateIR]` | ✅ | `loopInvariant` |
| `termination_kind` | `string` | ✅ | used to build `terminationSpec` |
| `termination_vars` | `list[string]` | for `finiteCondition` | `.finiteCondition [vars]` |
| `termination_exit_node` | `int` | for `llmControlledExit` | `.llmControlledExit nodeId sentinel` |
| `termination_sentinel` | `string` | for `llmControlledExit` | `.llmControlledExit nodeId sentinel` |
| `termination_mechanism` | `string` | for `externalTermination` | `.externalTermination mechanism` |
| `termination_justification` | `string` | for `allowUnbounded` | `.allowUnbounded justification` |
| `exit_postcond` | `list[VarPredicateIR]` | ✅ (can be `[]`) | `exitPostconditions` |
| `reads[].predicates` | `list[PredicateIR]` | ✅ | `precondVariables` (via `collect_precond`) |

### Termination Kind Mapping

| `termination_kind` | Additional Required Fields | Generated Lean |
| --- | --- | --- |
| `"finiteCondition"` | `termination_vars` | `.finiteCondition ["iter", "max_iters"]` |
| `"llmControlledExit"` | `termination_exit_node`, `termination_sentinel` | `.llmControlledExit ⟨7⟩ "DONE"` |
| `"externalTermination"` | `termination_mechanism` | `.externalTermination "timeout after 30 min"` |
| `"allowUnbounded"` | `termination_justification` | `.allowUnbounded "server loop, runs until shutdown"` |

### Generated Lean (Complete)

```lean
-- Semantic Node 2: whileLoop "while_iter <= max_iters"
def prefix_loopNode2 : SemanticLoopNode := {
  baseNode := prefix_node2
  precondVariables := [varIsInt "iter", varIsInt "max_iters", varNameExists "solved"]
  postcondVariables := []
  loopInvariant := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsNonEmptyString "operation_rule",
    varIsInt "iter",
    varIsValidTool "term_send",
    varIsValidTool "term_read",
    varIsValidTool "memory"
  ]
  terminationSpec := .llmControlledExit prefix_nodeId7 "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
  exitPostconditions := [
    varContainsSentinel "final_output" "COMPLETE_TASK_AND_SUBMIT",
    varTaskCompleted "task_status"
  ]
}
def prefix_semNode2 : SemanticWorkflowNode := prefix_loopNode2.toSemanticWorkflowNode
```

### How to Design Loop Invariants

The loop invariant must include **every variable** that:
1. Is **read by any node inside the loop body** (preconditions of body nodes)
2. Is **written by any node inside the loop body** and read again in the next iteration
3. Includes **tools and modules** used inside the loop body

**Critical rule**: The last node in the loop body's postconditions must **re-establish** the loop invariant. The verifier checks that the combined postconditions of the loop body imply the loop invariant.

```
Entry precond → establishes loopInvariant
  ↓
Loop body iteration:
  loopInvariant → body_node_1.precond
  body_node_1.postcond → body_node_2.precond
  ...
  body_node_N.postcond → must imply loopInvariant  ← CRITICAL
  ↓
Loop exit:
  exitFacts = loopInvariant ∧ exitPostconditions
```

### Graph Assembly

The loop node must appear in **both** `semanticNodes` (via `.toSemanticWorkflowNode`) and `loopNodes`:

```lean
def prefixSemanticGraph : SemanticWorkflowGraph := {
  ...
  semanticNodes := [..., prefix_semNode2, ...]   -- uses converted version
  loopNodes := [prefix_loopNode2]                 -- uses original
  ...
}
```

### No Explicit Exit — Exit Node Points to Self

When a loop has **no explicit exit path** (i.e., it is the last step in the workflow, or the program terminates from *within* a loop body node rather than by exiting the loop normally), the `exit_node` in the `loopEdge` must **point back to the loop header itself**.

This is the "infinite loop" pattern — the loop never structurally exits; instead, the agent breaks out from within a body node (e.g., by outputting a sentinel string that causes the workflow to end).

#### How `TaskPlanToLean.py` Handles This

In `parse_task_json()`, after building all edges, the code patches loop edges to set their `exit_node`. If no `seq` edge follows the loop header (meaning the loop is the last step in the workflow), the code automatically sets `exit_node = header_id`:

```python
# From TaskPlanToLean.py lines 1086-1091:
if not found:
    # No subsequent step after the loop (loop is the last step in the
    # workflow).  Use the header itself as exit so the loopEdge is still
    # valid.  This mirrors the infinite-while-loop pattern where exit
    # points back to the header.
    edges[edge_idx].exit_node = header_id
```

#### IR JSON — Edge

When the loop has no explicit exit, the `loop` edge's `exit_node` equals its `header`:

```json
{
  "edge_type": "loop",
  "header": 3,
  "body_entry": 4,
  "exit_node": 3
}
```

Note: `exit_node: 3` == `header: 3` — loop exits to itself.

#### Generated Lean — Edge & Graph

```lean
-- Loop edge: exit points back to header (no explicit exit)
.loopEdge prefix_nodeId3 prefix_nodeId4 prefix_nodeId3
```

The workflow graph's `exits` list must be **empty** for this pattern:

```lean
def prefixGraph : WorkflowGraph := {
  ...
  edges := [
    ...
    .loopEdge prefix_nodeId3 prefix_nodeId4 prefix_nodeId3,  -- exit → self
    ...
    .loopBackEdge prefix_nodeIdN prefix_nodeId3              -- back edge
  ]
  exits := []  -- No normal exit; the loop IS the last thing
  ...
}
```

#### Real-World Example: SWE-bench Agent

The SWE-bench agent workflow is a classic example of this pattern. The while loop is the final structure in the workflow — the agent loops until it outputs `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` from within the `main_step` node:

```lean
-- From SWE_bench_verification.lean:
def sweWorkflowGraph : WorkflowGraph := {
  ...
  edges := [
    .seqEdge swe_nodeId_readReadme swe_nodeId_analyze,
    .seqEdge swe_nodeId_analyze swe_nodeId_setIter,
    .seqEdge swe_nodeId_setIter swe_nodeId_whileHeader,
    -- Loop: exit points to header itself (infinite loop pattern)
    .loopEdge swe_nodeId_whileHeader swe_nodeId_ifCond swe_nodeId_whileHeader,
    ...
    .loopBackEdge swe_nodeId_setPrev swe_nodeId_whileHeader
  ]
  exits := []  -- Infinite loop, no normal exit
  ...
}

-- The loop node uses llmControlledExit to specify where the agent breaks out:
def swe_loopNode_while : SemanticLoopNode := {
  ...
  terminationSpec := .llmControlledExit swe_nodeId_mainStep
    "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
  exitPostconditions := [
    varContainsSentinel "final_output" "COMPLETE_TASK_AND_SUBMIT",
    varTaskCompleted "task_status"
  ]
}
```

#### When to Use This Pattern

| Scenario | `exit_node` | `exits` |
| --- | --- | --- |
| Loop followed by more steps (e.g., return node) | next node after loop | `[returnNodeId]` |
| Loop is the **last step** in workflow | **loop header itself** | `[]` |
| Agent breaks out from *within* a body node | **loop header itself** | `[]` |
| Infinite server/daemon loop | **loop header itself** | `[]` |

> **Key insight**: The `exit_node` field on the `loopEdge` is a structural requirement — every `loopEdge` must have a valid `exit_node`. When there is no real exit, pointing to the header itself satisfies this constraint while correctly modeling the infinite loop semantics.

---

## 5. ForEach Loop Node

A for-each loop (`step_type: "forEachLoop"`) is a loop that iterates over a list variable. It extends `SemanticLoopNode` with an `iterationVar` field.

### Lean Structure

```lean
structure SemanticForEachLoopNode extends SemanticLoopNode where
  iterationVar : String   -- the loop variable (e.g., "item" in "for item in list")
```

### Two `def`s Generated

```lean
-- 1. The specialized for-each loop node
def prefix_loopNode3 : SemanticForEachLoopNode := { ... }

-- 2. Conversion to SemanticWorkflowNode
def prefix_semNode3 : SemanticWorkflowNode := prefix_loopNode3.toSemanticWorkflowNode
```

### IR JSON — Required Fields

```json
{
  "id": 3,
  "name": "foreach_module_info",
  "step_type": "forEachLoop",
  "reads": [
    {
      "name": "parsed_module_results", "base_type": "TList TJson",
      "predicates": [{"kind": "isNonEmptyList"}]
    }
  ],
  "writes": [
    {
      "name": "module_info", "base_type": "TJson",
      "predicates": [{"kind": "isValidJson"}]
    }
  ],
  "iteration_var": "module_info",
  "loop_invariant": [
    { "var_name": "parsed_module_results", "predicate": {"kind": "isNonEmptyList"} },
    { "var_name": "staging_dir", "predicate": {"kind": "isValidFilePath"} }
  ],
  "termination_kind": "finiteCondition",
  "termination_vars": ["parsed_module_results"],
  "exit_postcond": [
    { "var_name": "parsed_module_results", "predicate": {"kind": "isNonEmptyList"} }
  ]
}
```

### Field Reference (extends While Loop fields)

| IR JSON Field | Type | Required | Lean Field |
| --- | --- | --- | --- |
| `iteration_var` | `string` | ✅ | `iterationVar` |
| All fields from [While Loop](#4-while-loop-node) | — | ✅ | — |

> **Note**: For a for-each loop, `termination_kind` is almost always `"finiteCondition"` because the loop iterates over a finite list.

### Generated Lean (Complete)

```lean
-- Semantic Node 3: forEachLoop "foreach_module_info"
def prefix_loopNode3 : SemanticForEachLoopNode := {
  baseNode := prefix_node3
  precondVariables := [varIsNonEmptyList "parsed_module_results"]
  postcondVariables := [varIsValidJson "module_info"]
  loopInvariant := [
    varIsNonEmptyList "parsed_module_results",
    varIsValidFilePath "staging_dir"
  ]
  terminationSpec := .finiteCondition ["parsed_module_results"]
  exitPostconditions := [
    varIsNonEmptyList "parsed_module_results"
  ]
  iterationVar := "module_info"
}
def prefix_semNode3 : SemanticWorkflowNode := prefix_loopNode3.toSemanticWorkflowNode
```

### Difference from While Loop

| Aspect | `whileLoop` | `forEachLoop` |
| --- | --- | --- |
| Lean Structure | `SemanticLoopNode` | `SemanticForEachLoopNode` |
| Extra field | — | `iterationVar` |
| Typical termination | varies (often `llmControlledExit`) | `finiteCondition` (bounded by list length) |
| Loop variable | managed manually (e.g., `iter`) | automatically assigned from list (e.g., `item`) |
| `writes` | usually empty | contains the iteration variable |

### Graph Assembly

Same as while loop — appears in **both** `semanticNodes` and `loopNodes`:

```lean
def prefixSemanticGraph : SemanticWorkflowGraph := {
  ...
  semanticNodes := [..., prefix_semNode3, ...]
  loopNodes := [prefix_loopNode3]      -- ForEachLoopNode coerces to LoopNode
  ...
}
```

---

## 6. Other Deterministic Nodes

These node types are deterministic (`needs_spec == False`) but still get semantic annotations.

### `setVariable`

```json
{
  "id": 1, "name": "set_iter", "step_type": "setVariable",
  "reads": [], "writes": [{"name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}]}]
}
```

→ Generates a plain `SemanticWorkflowNode`:
```lean
def prefix_semNode1 : SemanticWorkflowNode := {
  baseNode := prefix_node1
  precondVariables := []
  postcondVariables := [varIsInt "iter"]
}
```

### `incrementVariable`

```json
{
  "id": 8, "name": "increment_iter", "step_type": "incrementVariable",
  "reads": [{"name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}]}],
  "writes": [{"name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}]}]
}
```

→ Generates:
```lean
def prefix_semNode8 : SemanticWorkflowNode := {
  baseNode := prefix_node8
  precondVariables := [varIsInt "iter"]
  postcondVariables := [varIsInt "iter"]
}
```

### `returnValue`

```json
{
  "id": 6, "name": "return_result", "step_type": "returnValue",
  "reads": [{"name": "return_dict", "base_type": "TString", "predicates": [
    {"kind": "isValidJson"},
    {"kind": "matchesJsonSchema", "schema": {"kind": "jObject", "fields": [...]}}
  ]}],
  "writes": []
}
```

→ Generates:
```lean
def prefix_semNode6 : SemanticWorkflowNode := {
  baseNode := prefix_node6
  precondVariables := [
    varIsValidJson "return_dict",
    varIsValidJsonSchema "return_dict" (.jObject [...])
  ]
  postcondVariables := []
}
```

> **Important**: The return node's preconditions are critical for submodule composition — they define what the submodule guarantees to its parent.

---

## 7. SemanticWorkflowGraph Assembly

### The Three Lists

```lean
structure SemanticWorkflowGraph where
  baseGraph : WorkflowGraph
  paramNode : SemanticWorkflowNode
  semanticNodes : List SemanticWorkflowNode     -- ALL nodes (converted)
  loopNodes : List SemanticLoopNode := []        -- loop headers only
  conditionalNodes : List SemanticConditionalNode := [] -- conditional nodes only
  specInvariant : ...
```

### Rules

1. `semanticNodes` contains **one entry per node** in `baseGraph.nodes`, **in the same order**
2. Loop headers use `prefix_loopNode{id}.toSemanticWorkflowNode`
3. Conditional nodes use `prefix_condNode{id}.toSemanticWorkflowNode`
4. Regular nodes use `prefix_semNode{id}` directly
5. `loopNodes` contains the original `SemanticLoopNode` / `SemanticForEachLoopNode` defs
6. `conditionalNodes` contains the original `SemanticConditionalNode` defs

### Example with All Node Types

```lean
def prefixSemanticGraph : SemanticWorkflowGraph := {
  baseGraph := prefixGraph
  paramNode := prefix_paramNode
  semanticNodes := [
    prefix_semNode0,        -- regular step
    prefix_semNode1,        -- setVariable
    prefix_semNode2,        -- whileLoop (via .toSemanticWorkflowNode)
    prefix_semNode3,        -- step inside loop body
    prefix_semNode4,        -- step inside loop body
    prefix_semNode5,        -- conditional (via .toSemanticWorkflowNode)
    prefix_semNode6,        -- step (then branch)
    prefix_semNode7,        -- step (else branch)
    prefix_semNode8,        -- incrementVariable
    prefix_semNode9,        -- returnValue
  ]
  loopNodes := [prefix_loopNode2]
  conditionalNodes := [prefix_condNode5]
  specInvariant := by decide
}
```

---

## 8. Common Pitfalls

### ❌ Forgetting branch target IDs

Conditional nodes **must** have `then_target_id` and `else_target_id` matching the `branch` edge:
```json
// Edge:
{ "edge_type": "branch", "cond_node": 3, "then_entry": 4, "else_entry": 5 }
// Node 3 must have:
{ "then_target_id": 4, "else_target_id": 5 }
```

### ❌ Loop invariant not re-established

The last node in the loop body's postconditions must imply the loop invariant. If the invariant includes `varIsInt "iter"` but the last body node's postcond doesn't guarantee it, verification will fail.

### ❌ Missing tools in loop invariant

If a node inside the loop body requires `varIsValidTool "fs_read"`, the loop invariant must also include `varIsValidTool "fs_read"` — tools are not automatically propagated through loop iterations.

### ❌ Using `"predicate"` (singular) instead of `"predicates"` (plural)

In `TypedVar` (reads/writes), the field name is **`"predicates"`** (plural, a list):
```json
{ "name": "url", "base_type": "TString", "predicates": [{"kind": "isValidURL"}] }
```

In `VarPredicateIR` (precond_extra, postcond_extra, loop_invariant, then_postcond, else_postcond, exit_postcond), the field name is **`"predicate"`** (singular, one object):
```json
{ "var_name": "url", "predicate": {"kind": "isValidURL"} }
```

### ❌ Loop without explicit exit but `exit_node` not pointing to self

If the loop is the last step in the workflow (or the agent exits from within a body node), the `exit_node` in the `loopEdge` **must** point to the loop header itself, and the graph's `exits` must be `[]`:
```json
// ✅ Correct: exit_node == header (no explicit exit)
{ "edge_type": "loop", "header": 3, "body_entry": 4, "exit_node": 3 }
// graph: exits = []

// ❌ Wrong: exit_node pointing to a nonexistent node
{ "edge_type": "loop", "header": 3, "body_entry": 4, "exit_node": 99 }
```

### ❌ Omitting converted `_semNode` for loops/conditionals

Every loop/conditional node needs **both** its specialized def and the `.toSemanticWorkflowNode` conversion. The `semanticNodes` list uses the converted version; `loopNodes`/`conditionalNodes` use the original.

---

## Quick Reference: IR JSON Field Summary

### All Node Types

| Field | Type | Where Used |
| --- | --- | --- |
| `reads[].predicates` | `list[PredicateIR]` | All nodes |
| `writes[].predicates` | `list[PredicateIR]` | All nodes |
| `precond_extra` | `list[VarPredicateIR]` | All nodes (optional) |
| `postcond_extra` | `list[VarPredicateIR]` | All nodes (optional) |

### Conditional-Only Fields

| Field | Type | Example |
| --- | --- | --- |
| `then_target_id` | `int` | `4` |
| `else_target_id` | `int` | `5` |
| `then_postcond` | `list[VarPredicateIR]` | `[{"var_name": "x", "predicate": {"kind": "nameExists"}}]` |
| `else_postcond` | `list[VarPredicateIR]` | `[{"var_name": "x", "predicate": {"kind": "isNonEmptyString"}}]` |

### Loop-Only Fields (whileLoop + forEachLoop)

| Field | Type | Example |
| --- | --- | --- |
| `loop_invariant` | `list[VarPredicateIR]` | `[{"var_name": "iter", "predicate": {"kind": "isInt"}}]` |
| `termination_kind` | `string` | `"finiteCondition"` / `"llmControlledExit"` / `"externalTermination"` / `"allowUnbounded"` |
| `termination_vars` | `list[string]` | `["iter", "max_iters"]` (for `finiteCondition`) |
| `termination_exit_node` | `int` | `7` (for `llmControlledExit`) |
| `termination_sentinel` | `string` | `"DONE"` (for `llmControlledExit`) |
| `termination_mechanism` | `string` | `"timeout"` (for `externalTermination`) |
| `termination_justification` | `string` | `"server loop"` (for `allowUnbounded`) |
| `exit_postcond` | `list[VarPredicateIR]` | `[{"var_name": "output", "predicate": {"kind": "taskCompleted"}}]` |

### ForEachLoop-Only Field

| Field | Type | Example |
| --- | --- | --- |
| `iteration_var` | `string` | `"module_info"` |
