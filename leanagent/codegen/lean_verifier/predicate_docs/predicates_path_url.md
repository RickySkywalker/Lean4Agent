# Path & URL Predicates (#5–7)

> Back to [index](index.md)

---

<a id="5"></a>
## 5. `varIsValidURL` — Valid URL

**PredicateType**: `.isValidURL`
**Semantics**: `envString env name (fun s => s.length > 0 ∧ s.containsSubstr "://")`
**Use case**: Input parameter for tools requiring network access.
**Note**: Automatically implies `isNonEmptyString` and `nameExists`.
**IR JSON**: `{"kind": "isValidURL"}` · TypedVar: `{"name": "url", "base_type": "TString", "predicates": [{"kind": "isValidURL"}]}`

```lean
-- Example: paramNode declares url parameter as a valid URL
def paramNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidURL "url",
    varIsValidFilePath "file_path"
]
}

-- Example: Step using url requires isValidURL in precond
def semNode_getBibtex : SemanticWorkflowNode := {
baseNode := node_getBibtex
precondVariables := [
    varIsValidTool "get_bibtex_from_url",
    varIsValidURL "url",
    varIsNonEmptyString "paper_title"
]
postcondVariables := [
    varIsNonEmptyString "bibtex_citation",
    varIsValidBibtex "bibtex_citation"
]
}
```

**Source**: `Verification_extract_single_citation.lean` — paramNode and Node 1

---

<a id="6"></a>
## 6. `varIsValidFilePath` — Valid File Path

**PredicateType**: `.isValidFilePath`
**Semantics**: `envString env name (fun s => s.length > 0 ∧ s.containsSubstr "/")`
**Use case**: Path parameters for file read/write operations.
**Note**: Automatically implies `isNonEmptyString` and `nameExists`.
**IR JSON**: `{"kind": "isValidFilePath"}` · TypedVar: `{"name": "file_path", "base_type": "TString", "predicates": [{"kind": "isValidFilePath"}]}`

```lean
-- Example: SWE-bench code_path and memory_file are both file paths
def swe_paramNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsNonEmptyString "operation_rule",
    varIsValidTool "term_send",
    varIsValidTool "term_read",
    varIsValidTool "memory"
]
}
```

**Source**: `SWE_bench_verification.lean` — paramNode

---

<a id="7"></a>
## 7. `varIsValidPath` — Valid Path (Generalized)

**PredicateType**: `.isValidPath`
**Semantics**: `envString env name (fun s => s.length > 0)` — more lenient than `isValidFilePath`, does not require `"/"`.
**Use case**: Generic paths, directory names, or when unsure whether it's a file or directory.
**IR JSON**: `{"kind": "isValidPath"}` · TypedVar: `"predicates": [{"kind": "isValidPath"}]`

```lean
-- Example: Directory path
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [ varIsValidPath "output_dir" ]
postcondVariables := [ varIsNonEmptyString "result" ]
}
```
