# Tool & Module Predicates (#12–13)

> Back to [index](index.md)

---

<a id="12"></a>
## 12. `varIsValidTool` — Tool Available

**PredicateType**: `.toolExists`
**Semantics**: `nameExists env toolName` — essentially a variable existence check, semantically marking a tool as available.
**Use case**: **Declare available tools in `paramNode` postcond**, require tool availability in step precond.
**IR JSON**: `{"kind": "toolExists"}` · VarPredicateIR: `{"var_name": "fs_read", "predicate": {"kind": "toolExists"}}`

```lean
-- Example: Declaring available tools (in paramNode)
def paramNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidTool "firecrawl_search",
    varIsValidTool "fs_read",
    varIsValidTool "get_bibtex_from_url",
    varIsValidTool "get_abstract_from_url"
]
}

-- Example: Step using a tool (precond requires tool existence)
def semNode_search : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    varIsValidTool "firecrawl_search",
    varIsNonEmptyString "query"
]
postcondVariables := [
    varIsNonEmptyString "search_results"
]
}
```

**Source**: `Verification_extract_citation.lean` — paramNode and Node 0

---

<a id="13"></a>
## 13. `varIsValidModule` — Submodule Available

**PredicateType**: `.moduleExists`
**Semantics**: `nameExists env moduleName` — same semantics as `toolExists`, but marks a submodule.
**Use case**: Declare available submodules in `paramNode` (for parallel or submodule calls).
**IR JSON**: `{"kind": "moduleExists"}` · VarPredicateIR: `{"var_name": "extract_single_citation", "predicate": {"kind": "moduleExists"}}`

```lean
-- Example: Declaring a submodule as available
def paramNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidTool "firecrawl_search",
    varIsValidModule "extract_single_citation"
]
}
```

**Source**: `Verification_extract_citation.lean` — paramNode
