# Basic Predicates (#1–4)

> Back to [index](index.md)

---

<a id="1"></a>
## 1. `varNameExists` — Variable Exists

**PredicateType**: `.nameExists`
**Semantics**: Only requires the variable to have been assigned; no restriction on type or value.
**Use case**: Precondition for conditional branches (only need to know the variable exists); weakest guarantee.
**IR JSON**: `{"kind": "nameExists"}` · TypedVar: `"predicates": [{"kind": "nameExists"}]`

```lean
-- Example: Conditional node only needs to know abstract exists
def condNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    varNameExists "abstract"
]
postcondVariables := [
    varNameExists "abstract"
]
}
```

**Source**: `Verification_extract_single_citation.lean` — conditional node `check_abstract == None`

---

<a id="2"></a>
## 2. `varIsNonEmptyString` — Non-Empty String

**PredicateType**: `.isNonEmptyString`
**Semantics**: `∃ s, env.get name = some (.vString s) ∧ s.length > 0`
**Use case**: LLM-generated text outputs, analysis results, intermediate text variables. This is one of the most commonly used predicates.
**IR JSON**: `{"kind": "isNonEmptyString"}` · TypedVar: `"predicates": [{"kind": "isNonEmptyString"}]`

```lean
-- Example: LLM step outputs paper_title as a non-empty string
def semNode_extractTitle : SemanticWorkflowNode := {
baseNode := node_extract_title
precondVariables := [
    varIsValidFilePath "file_path",
    varIsValidTool "fs_read"
]
postcondVariables := [
    varIsNonEmptyString "paper_title"
]
}
```

**Source**: `Verification_extract_single_citation.lean` — Node 0 postcond

---

<a id="3"></a>
## 3. `varIsNonEmptyList` — Non-Empty List

**PredicateType**: `.isNonEmptyList`
**Semantics**: `∃ l, env.get name = some (.vList l) ∧ l.length > 0`
**Use case**: Search result lists, batch processing inputs.
**IR JSON**: `{"kind": "isNonEmptyList"}` · TypedVar: `"predicates": [{"kind": "isNonEmptyList"}]`

```lean
-- Example: Search step guarantees non-empty result list
def semNode_search : SemanticWorkflowNode := {
baseNode := node_search
precondVariables := [
    varIsNonEmptyString "query"
]
postcondVariables := [
    varIsNonEmptyList "search_results"
]
}
```

---

<a id="4"></a>
## 4. `varIsInt` — Integer Variable

**PredicateType**: `.isInt`
**Semantics**: `∃ n : Int, env.get name = some (.vInt n)`
**Use case**: Loop counters, iteration variables (`iter`, `prev`).
**IR JSON**: `{"kind": "isInt"}` · TypedVar: `{"name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}]}`

```lean
-- Example: Setting loop iterator iter = 1
def semNode_setIter : SemanticWorkflowNode := {
baseNode := node_setIter
precondVariables := []
postcondVariables := [
    varIsInt "iter"
]
}

-- Example: After incrementing iter, it remains an int
def semNode_increment : SemanticWorkflowNode := {
baseNode := node_increment
precondVariables := [ varIsInt "iter" ]
postcondVariables := [ varIsInt "iter" ]
}
```

**Source**: `SWE_bench_verification.lean` — Node 2 (`set_iter`) and Node 9 (`increment_iter`)
