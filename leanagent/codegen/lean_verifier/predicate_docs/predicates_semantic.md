# Semantic Marker Predicates (#16–19)

> Back to [index](index.md)

---

<a id="16"></a>
## 16. `varContainsSentinel` — Contains Sentinel Substring

**PredicateType**: `.containsSubstring substring`
**Signature**: `varContainsSentinel (varName : String) (sentinel : String)`
**Semantics**: `envString env name (fun str => str.containsSubstr subString)`
**Use case**: **Loop termination conditions** — detecting sentinel strings in LLM output to exit loops.
**IR JSON**: `{"kind": "containsSubstring", "substring": "COMPLETE_TASK_AND_SUBMIT"}`

```lean
-- Example: SWE-bench loop exit postconditions
def loopNode : SemanticLoopNode := {
baseNode := node_while
precondVariables := [ varIsInt "iter" ]
postcondVariables := []
loopInvariant := [ ... ]
terminationSpec := .llmControlledExit nodeId_mainStep "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
exitPostconditions := [
    varContainsSentinel "final_output" "COMPLETE_TASK_AND_SUBMIT",
    varTaskCompleted "task_status"
]
}
```

**Source**: `SWE_bench_verification.lean` — `swe_loopNode_while.exitPostconditions`

---

<a id="17"></a>
## 17. `varFileExistsAtPath` — File Exists Marker

**PredicateType**: `.fileExistsAtPath`
**Semantics**: Equivalent to `isNonEmptyString` (semantic marker indicating a file exists at the given path).
**Use case**: Marking that a file has been created or downloaded to a specified path.
**IR JSON**: `{"kind": "fileExistsAtPath"}` · TypedVar: `"predicates": [{"kind": "fileExistsAtPath"}]`

```lean
-- Example: After downloading a file, mark file existence
def semNode_download : SemanticWorkflowNode := {
baseNode := node_download
precondVariables := [ varIsValidURL "download_url" ]
postcondVariables := [ varFileExistsAtPath "local_file_path" ]
}
```

---

<a id="18"></a>
## 18. `varTaskCompleted` — Task Completed Marker

**PredicateType**: `.taskCompleted`
**Semantics**: Equivalent to `nameExists` (pure semantic marker).
**Use case**: Marking a task/phase as completed (commonly used in loop exit conditions).
**IR JSON**: `{"kind": "taskCompleted"}` · VarPredicateIR: `{"var_name": "task_status", "predicate": {"kind": "taskCompleted"}}`

```lean
-- Example: After loop exit, mark task as completed
exitPostconditions := [
    varContainsSentinel "final_output" "COMPLETE_TASK_AND_SUBMIT",
    varTaskCompleted "task_status"
]
```

**Source**: `SWE_bench_verification.lean` — `swe_loopNode_while.exitPostconditions`

---

<a id="19"></a>
## 19. `varIsValidCustomPredicate` — Custom Predicate

**PredicateType**: `.custom name`
**Signature**: `varIsValidCustomPredicate (varName : String) (predicateName : String)`
**Semantics**: Falls back to `nameExists` (marker only).
**Use case**: Custom semantics not covered by built-in predicates.
**IR JSON**: `{"kind": "custom", "custom_name": "isWellFormedResponse"}`

```lean
-- Example
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidCustomPredicate "model_output" "isWellFormedResponse"
]
}
```
