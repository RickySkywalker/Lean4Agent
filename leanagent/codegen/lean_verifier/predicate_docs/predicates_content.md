# Content Format Predicates (#8–11)

> Back to [index](index.md)

---

<a id="8"></a>
## 8. `varIsValidBibtex` — Valid BibTeX

**PredicateType**: `.isValidBibtex`
**Semantics**: `envString env name (fun s => s.length > 0 ∧ s.containsSubstr "@")`
**Use case**: Output of citation extraction tools.
**Note**: Automatically implies `isNonEmptyString`.
**IR JSON**: `{"kind": "isValidBibtex"}` · TypedVar: `"predicates": [{"kind": "isValidBibtex"}]`

```lean
-- Example: BibTeX tool output
def semNode_bibtex : SemanticWorkflowNode := {
baseNode := node_bibtex
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

**Source**: `Verification_extract_single_citation.lean` — Node 1 postcond

---

<a id="9"></a>
## 9. `varIsValidLatex` — Valid LaTeX

**PredicateType**: `.isValidLatex`
**Semantics**: `envString env name (fun s => s.length > 0 ∧ s.containsSubstr "\\")`
**Use case**: LaTeX-formatted output content.
**Note**: Automatically implies `isNonEmptyString`.
**IR JSON**: `{"kind": "isValidLatex"}` · TypedVar: `"predicates": [{"kind": "isValidLatex"}]`

```lean
-- Example: Step generating LaTeX formulas
def semNode_latex : SemanticWorkflowNode := {
baseNode := node_genLatex
precondVariables := [ varIsNonEmptyString "equation_text" ]
postcondVariables := [ varIsValidLatex "latex_output" ]
}
```

---

<a id="10"></a>
## 10. `varIsValidJson` — Valid JSON

**PredicateType**: `.isValidJson`
**Semantics**: `∃ j, env.get name = some (.vJson j)`
**Use case**: JSON-formatted intermediate data. Typically used together with `matchesJsonSchema`.
**IR JSON**: `{"kind": "isValidJson"}` · TypedVar: `"predicates": [{"kind": "isValidJson"}]`

```lean
-- Example: prepare_return_dict output is valid JSON
def semNode_prepareReturnDict : SemanticWorkflowNode := {
baseNode := node_prepare
precondVariables := [
    varIsValidBibtex "bibtex_citation",
    varIsValidFilePath "file_path",
    varIsNonEmptyString "paper_title",
    varIsNonEmptyString "abstract"
]
postcondVariables := [
    varIsValidJson "return_dict",
    varIsValidJsonSchema "return_dict" returnDictSchema
]
}
```

**Source**: `Verification_extract_single_citation.lean` — Node 5

---

<a id="11"></a>
## 11. `varIsValidList` — Valid List

**PredicateType**: `.isValidList`
**Semantics**: `∃ l, env.get name = some (.vList l)` — allows empty lists.
**Use case**: List-type data that may be empty. For non-empty lists, use `varIsNonEmptyList`.
**IR JSON**: `{"kind": "isValidList"}` · TypedVar: `"predicates": [{"kind": "isValidList"}]`

```lean
-- Example: Collected results may be empty
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [ varIsValidList "collected_items" ]
}
```
