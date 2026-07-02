# Advanced Predicates (#20–22)

> Back to [index](index.md)

---

<a id="20"></a>
## 20. `.ext key` — Extensible Predicate

**PredicateType**: `.ext (key : PredicateKey)`
**No shorthand function** — requires direct construction of `VariablePredicateRequirement`.
**Semantics**: Provided by `PredicateRegistry` at runtime.
**Use case**: Advanced scenarios — Dict value predicates for parallel submodules (`DictAllValuesPredicate`), etc.

### IR JSON format

There are **three ways** to define/reference an ext predicate in node predicates:

#### Option A: Inline definition (recommended — per-node, auto-collected)
```json
{"kind": "ext", "ext_inline": {
  "family": "dictAllValues",
  "value_predicates": [
    {"kind": "isValidJson"},
    {"kind": "matchesJsonSchema", "schema": {"kind": "jObject", "fields": [["bibtex", {"kind": "jString"}]]}}
  ],
  "dict_var_name": "all_citations"
}}
```
**Recommended for LLM-driven workflows**: each node defines its ext predicate in-place
based on the node's instruction. The code generator automatically:
1. Scans all nodes for `ext_inline` definitions
2. Deduplicates by content (same `family` + `value_predicates` + `dict_var_name` = same predicate)
3. Generates the Lean definitions and registry
4. Resolves all references to the same generated Key name

**No workflow-level `ext_predicates` list needed.**

If multiple nodes reference the same `ext_inline` content (e.g., a postcond produces it
and the next node's precond consumes it), they are automatically deduplicated and both
resolve to the same Lean `PredicateKey`.

The Lean definition name is auto-derived from `dict_var_name` (e.g., `all_citations` →
`{prefix}_all_citations_dictPred`), or can be set explicitly via `lean_def_name`.

#### Option B: Direct ext_key (specify the generated Lean Key name manually)
```json
{"kind": "ext", "ext_key": "myDictPredKey"}
```

#### Option C: ext_ref (index into workflow-level ext_predicates list, auto-resolved)
```json
{"kind": "ext", "ext_ref": 0}
```
`ext_ref` is an integer index into the `ext_predicates` array defined at the workflow level.
During code generation, `ext_ref` is automatically resolved to the corresponding `ext_key`.

### ExtPredicateIR fields

The inline object (or workflow-level entry) has these fields:

- `family`: Must be `"dictAllValues"` for `DictAllValuesPredicate`
- `value_predicates`: List of `PredicateIR` that each dict value must satisfy
- `dict_var_name`: The variable name this predicate targets (optional, used for auto-naming)
- `lean_def_name`: Custom Lean definition name (optional; auto-derived from `dict_var_name` or index)

### Example: Inline usage in node predicates

Parallel node postcond (produces the ext predicate):
```json
{
  "postcond_extra": [
    {
      "var_name": "all_citations",
      "predicate": {
        "kind": "predicateAnd",
        "left": {"kind": "matchesJsonSchema", "schema": {"kind": "jObject", "fields": []}},
        "right": {
          "kind": "ext",
          "ext_inline": {
            "family": "dictAllValues",
            "value_predicates": [{"kind": "isValidJson"}],
            "dict_var_name": "all_citations"
          }
        }
      }
    }
  ]
}
```

Next node precond (consumes it — same `ext_inline` content, auto-deduplicated):
```json
{
  "precond_extra": [
    {
      "var_name": "all_citations",
      "predicate": {
        "kind": "ext",
        "ext_inline": {
          "family": "dictAllValues",
          "value_predicates": [{"kind": "isValidJson"}],
          "dict_var_name": "all_citations"
        }
      }
    }
  ]
}
```

### Full Lean example

```lean
-- Step 1: Define DictAllValuesPredicate
def myDictPred : DictAllValuesPredicate := {
  dictValuePredicates := [.isValidJson, .matchesJsonSchema mySchema]
  dictVarName := "all_results"
}

-- Step 2: Convert to PredicateKey and PredicateType
def myDictPredKey : PredicateKey := myDictPred.toPredicateKey
def myDictPredPredType : PredicateType := .ext myDictPredKey

-- Step 3: Use in precond (direct construction)
def semNode3 : SemanticWorkflowNode := {
  baseNode := ...
  precondVariables := [
    { varName := "all_results"
      requiredPredicate := myDictPredPredType }
  ]
  postcondVariables := [ ... ]
}

-- Step 4: Register in the Registry (for verify to use)
def myRegistry : PredicateRegistry :=
  makeDictAllValuesRegistry [myDictPred]

-- Step 5: Pass registry during verification
theorem myGraph_sound :
    mySemanticGraph.isSemanticallySoundBool myRegistry = true := by
  native_decide
```

**Source**: `Verification_extract_citation.lean` — `sc_semNode2`, `sc_semNode3`, `searchCitationsRegistry`

---

<a id="21"></a>
## 21. `varPredicateAnd` — Predicate Conjunction

**PredicateType**: `.predicateAnd p₁ p₂`
**Signature**: `varPredicateAnd (varName : String) (pred₁ pred₂ : PredicateType)`
**Semantics**: `p₁.toProp env name ∧ p₂.toProp env name`
**Use case**: A single variable must satisfy multiple conditions simultaneously.
**IR JSON**: `{"kind": "predicateAnd", "left": {"kind": "isValidJson"}, "right": {"kind": "matchesJsonSchema", "schema": {…}}}`

```lean
-- Example: Variable must be valid JSON AND match a specific schema
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    varPredicateAnd "data" .isValidJson (.matchesJsonSchema mySchema)
]
postcondVariables := [ ... ]
}
```

**Note**: In most cases, you can use two separate `VariablePredicateRequirement` entries instead:

```lean
-- Equivalent (and more common) pattern
precondVariables := [
    varIsValidJson "data",
    varIsValidJsonSchema "data" mySchema
]
```

---

<a id="22"></a>
## 22. `varPredicateOr` — Predicate Disjunction

**PredicateType**: `.predicateOr p₁ p₂`
**Signature**: `varPredicateOr (varName : String) (pred₁ pred₂ : PredicateType)`
**Semantics**: `p₁.toProp env name ∨ p₂.toProp env name`
**Use case**: Variable needs to satisfy at least one of two conditions.
**IR JSON**: `{"kind": "predicateOr", "left": {"kind": "isValidURL"}, "right": {"kind": "isValidFilePath"}}`

```lean
-- Example: Source path can be either a URL or a file path
def semNode : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    varPredicateOr "source" .isValidURL .isValidFilePath
]
postcondVariables := [ ... ]
}
```
