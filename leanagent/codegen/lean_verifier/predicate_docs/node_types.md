# Special Node Types & Predicate Patterns

> Back to [index](index.md)

---

## Parameter Node

Every `SemanticWorkflowGraph` has a `paramNode`, used to declare:

1. Type constraints on workflow parameters
2. Available tools and modules

```lean
def myParamNode : SemanticWorkflowNode := {
baseNode := {
    id := ⟨20041122⟩  -- Special ID for parameter node
    name := some "parameters"
    stepType := .setVariable
    reads := []
    writes := []
    llmInstruction := none
}
precondVariables := []   -- paramNode has no preconditions
postcondVariables := [
    -- Parameter constraints
    varIsNonEmptyString "query",
    varIsInt "max_papers",
    -- Tool declarations
    varIsValidTool "firecrawl_search",
    varIsValidTool "fs_read",
    -- Module declarations
    varIsValidModule "extract_single_citation"
]
}
```

---

## Loop Node

`SemanticLoopNode` has additional `loopInvariant` and `exitPostconditions` fields:

```lean
def myLoopNode : SemanticLoopNode := {
baseNode := node_while
precondVariables := [ varIsInt "iter" ]
postcondVariables := []
loopInvariant := [
    -- Must hold at the start of EVERY iteration
    varIsValidFilePath "code_path",
    varIsInt "iter",
    varIsValidTool "term_send"
]
terminationSpec := .llmControlledExit nodeId "DONE"
exitPostconditions := [
    -- Guaranteed to hold when loop exits
    varContainsSentinel "output" "DONE",
    varTaskCompleted "task_status"
]
}
```

---

## Conditional Node

`SemanticConditionalNode` has additional branch-specific postconditions:

```lean
def myCondNode : SemanticConditionalNode := {
baseNode := node_if
precondVariables := [ varNameExists "abstract" ]
postcondVariables := [ varNameExists "abstract" ]  -- default
thenTargetId := nodeId4
elseTargetId := nodeId5
thenPostcondVariables := [
    varNameExists "abstract"          -- then branch: abstract may be empty
]
elsePostcondVariables := [
    varIsNonEmptyString "abstract"    -- else branch: abstract is non-empty
]
}
```
