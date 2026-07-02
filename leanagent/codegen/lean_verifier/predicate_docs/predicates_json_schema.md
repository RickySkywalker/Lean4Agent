# JSON Schema Predicates (#14–15)

> Back to [index](index.md)

---

<a id="14"></a>
## 14. `varIsValidJsonSchema` — JSON Schema Match

**PredicateType**: `.matchesJsonSchema schema`
**Signature**: `varIsValidJsonSchema (varName : String) (schema : JsonSchema)`
**Semantics**: `∃ j, env.get name = some (.vJson j) ∧ JsonMatchesSchema j schema` — recursively checks JSON structure.
**Use case**: Structured JSON outputs (return_dict, extraction_params, etc.).
**Note**: Automatically implies `isValidJson` and `nameExists`.
**IR JSON**: `{"kind": "matchesJsonSchema", "schema": {"kind": "jObject", "fields": [["key", {"kind": "jString"}]]}}` *(see [ir_json_format.md](ir_json_format.md) for full JsonSchema format)*

```lean
-- Define schemas
def citationResultSchema : JsonSchema :=
.jObject [("bibtex", .jString), ("file_path", .jString),
            ("title", .jString), ("abstract", .jString)]

def extractionParamsSchema : JsonSchema :=
.jArray (.jObject [("url", .jString), ("file_path", .jString)])

-- Example: postcond using JsonSchema
def semNode_prepareDict : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [ ... ]
postcondVariables := [
    varIsValidJson "return_dict",
    varIsValidJsonSchema "return_dict" citationResultSchema
]
}

-- Example: precond using JsonSchema (downstream node consuming)
def semNode_returnResult : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    varIsValidJsonSchema "return_dict" citationResultSchema
]
postcondVariables := []
}
```

### Available JsonSchema types

```lean
.jString                                    -- string
.jNum                                       -- number
.jBool                                      -- boolean
.jNull                                      -- null
.jArray (.jString)                          -- array of strings
.jObject [("key1", .jString), ("key2", .jNum)]  -- object with typed fields
.jAny                                       -- any type
```

**Source**: `Verification_extract_single_citation.lean` — Node 5, Node 6 and `Verification_extract_citation.lean` — Node 1, Node 3, Node 4

---

<a id="15"></a>
## 15. `varIsValidJsonFields` — JSON Field Check

**PredicateType**: `.isJsonWithFields fields`
**Signature**: `varIsValidJsonFields (varName : String) (fields : List JsonFieldSpec)`
**Semantics**: JSON object contains specified keys with expected types (open-world assumption, extra fields allowed).
**Use case**: When only partial field validation is needed (more lenient than `matchesJsonSchema`).
**IR JSON**: *(not yet supported in IR — use `matchesJsonSchema` as substitute)*

```lean
-- Example
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := []
postcondVariables := [
    varIsValidJsonFields "config" [
    ⟨"name", .jString⟩,
    ⟨"version", .jNum⟩
    ]
]
}
```
