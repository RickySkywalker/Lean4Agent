# Agent Verifier: PredicateType ↔ Variable Predicate Quick Reference

> **Purpose**: This document serves as a lookup table for automated formalization of Agent Plans. Each `PredicateType` maps to a `VariablePredicateRequirement` shorthand constructor (`var*`), used in the `precondVariables` / `postcondVariables` fields of `SemanticWorkflowNode`.

---

## Architecture Overview

```
YAML Agent Plan
    ↓  (auto-translate)
WorkflowGraph          ← Layer 1: Structural verification (reads/writes/edges)
    ↓  (add semantic annotations)
SemanticWorkflowGraph  ← Layer 2: Semantic verification (precond/postcond chaining)
    ↓
Soundness Theorem    ← Proved via native_decide
```

Each `SemanticWorkflowNode` has:

- `precondVariables : List VariablePredicateRequirement` — conditions that variables must satisfy **before** this step executes
- `postcondVariables : List VariablePredicateRequirement` — conditions guaranteed to hold **after** this step executes

A `VariablePredicateRequirement` consists of two parts:

```lean
structure VariablePredicateRequirement where
varName : String            -- variable name
requiredPredicate : PredicateType  -- predicate the variable must satisfy
```

---

## Complete Mapping Table

| #  | PredicateType                 | Variable Predicate Shorthand                                      | Prop Semantics                                                                | Use Case                                                     |
| -- | ----------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------ |
| 1  | `.nameExists`               | `varNameExists`                                                 | Variable exists (`∃ v, env.get name = some v`)                             | Weakest condition; only requires the variable to be assigned |
| 2  | `.isNonEmptyString`         | `varIsNonEmptyString`                                           | Non-empty string (`∃ s, env.get name = some (.vString s) ∧ s.length > 0`) | Text content, analysis results, LLM outputs                  |
| 3  | `.isNonEmptyList`           | `varIsNonEmptyList`                                             | Non-empty list (`∃ l, env.get name = some (.vList l) ∧ l.length > 0`)     | Search result sets, batch data                               |
| 4  | `.isInt`                    | `varIsInt`                                                      | Integer value (`∃ n, env.get name = some (.vInt n)`)                       | Loop counters, iteration variables                           |
| 5  | `.isValidURL`               | `varIsValidURL`                                                 | Non-empty string containing `"://"`                                         | URL parameters                                               |
| 6  | `.isValidFilePath`          | `varIsValidFilePath`                                            | Non-empty string containing `"/"`                                           | File path parameters                                         |
| 7  | `.isValidPath`              | `varIsValidPath`                                                | Non-empty string (generalized path)                                           | Generic path (file or directory)                             |
| 8  | `.isValidBibtex`            | `varIsValidBibtex`                                              | Non-empty string containing `"@"`                                           | BibTeX citations                                             |
| 9  | `.isValidLatex`             | `varIsValidLatex`                                               | Non-empty string containing `"\\"`                                          | LaTeX content                                                |
| 10 | `.isValidJson`              | `varIsValidJson`                                                | JSON value (`∃ j, env.get name = some (.vJson j)`)                         | JSON-format data                                             |
| 11 | `.isValidList`              | `varIsValidList`                                                | List value (`∃ l, env.get name = some (.vList l)`)                         | List-type data (may be empty)                                |
| 12 | `.toolExists`               | `varIsValidTool`                                                | Tool name exists in environment (equivalent to `nameExists`)                | Declares a tool is available                                 |
| 13 | `.moduleExists`             | `varIsValidModule`                                              | Module name exists in environment (equivalent to `nameExists`)              | Declares a submodule is available                            |
| 14 | `.matchesJsonSchema schema` | `varIsValidJsonSchema`                                          | JSON value matches given schema (recursive check)                             | Structured JSON output                                       |
| 15 | `.isJsonWithFields fields`  | `varIsValidJsonFields`                                          | JSON object contains specified fields                                         | Partial structure validation                                 |
| 16 | `.containsSubstring s`      | `varContainsSentinel`                                           | String contains specified substring                                           | Loop termination sentinel detection                          |
| 17 | `.fileExistsAtPath`         | `varFileExistsAtPath`                                           | Equivalent to `isNonEmptyString` (semantic marker)                          | Marks a file has been created                                |
| 18 | `.taskCompleted`            | `varTaskCompleted`                                              | Equivalent to `nameExists` (semantic marker)                                | Marks a task as completed                                    |
| 19 | `.custom name`              | `varIsValidCustomPredicate`                                     | Equivalent to `nameExists` (custom fallback)                                | Custom semantic markers                                      |
| 20 | `.ext key`                  | Construct directly:`{ varName, requiredPredicate := .ext key }` | Semantics provided by `PredicateRegistry`                                   | Extensible predicates (e.g., DictAllValues)                  |
| 21 | `.predicateAnd p₁ p₂`     | `varPredicateAnd`                                               | `p₁ ∧ p₂`                                                                | Conjunction of conditions                                    |
| 22 | `.predicateOr p₁ p₂`      | `varPredicateOr`                                                | `p₁ ∨ p₂`                                                                | Disjunction of conditions                                    |

---

## IR JSON Representation

Predicates in the IR JSON file appear in two contexts: inside **TypedVar** (reads/writes arrays) and as standalone **VarPredicateIR** entries (param_postcond, precond_extra, etc.).

### Context 1: Inside TypedVar (`reads` / `writes`)

Each variable carries a `predicates` array of predicate objects:

```json
{
  "name": "bibtex_citation",
  "base_type": "TString",
  "predicates": [
    {"kind": "isNonEmptyString"},
    {"kind": "isValidBibtex"}
  ]
}
```

If a variable has no semantic annotations (Layer 1 IR), omit the `predicates` field entirely.

### Context 2: VarPredicateIR (precond/postcond lists)

Used in: `param_postcond`, `precond_extra`, `postcond_extra`, `then_postcond`, `else_postcond`, `loop_invariant`, `exit_postcond`

```json
{ "var_name": "fs_read", "predicate": {"kind": "toolExists"} }
```

### Per-Predicate IR Format

| #  | PredicateType             | IR JSON (`predicate` object)                                                              |
| -- | ------------------------- | ----------------------------------------------------------------------------------------- |
| 1  | `nameExists`            | `{"kind": "nameExists"}`                                                                |
| 2  | `isNonEmptyString`      | `{"kind": "isNonEmptyString"}`                                                          |
| 3  | `isNonEmptyList`        | `{"kind": "isNonEmptyList"}`                                                            |
| 4  | `isInt`                 | `{"kind": "isInt"}`                                                                     |
| 5  | `isValidURL`            | `{"kind": "isValidURL"}`                                                                |
| 6  | `isValidFilePath`       | `{"kind": "isValidFilePath"}`                                                           |
| 7  | `isValidPath`           | `{"kind": "isValidPath"}`                                                               |
| 8  | `isValidBibtex`         | `{"kind": "isValidBibtex"}`                                                             |
| 9  | `isValidLatex`          | `{"kind": "isValidLatex"}`                                                              |
| 10 | `isValidJson`           | `{"kind": "isValidJson"}`                                                               |
| 11 | `isValidList`           | `{"kind": "isValidList"}`                                                               |
| 12 | `toolExists`            | `{"kind": "toolExists"}`                                                                |
| 13 | `moduleExists`          | `{"kind": "moduleExists"}`                                                              |
| 14 | `matchesJsonSchema`     | `{"kind": "matchesJsonSchema", "schema": {…}}`  *(see below)*                          |
| 15 | `isJsonWithFields`      | *(not yet supported in IR — use `matchesJsonSchema` instead)*                           |
| 16 | `containsSubstring`     | `{"kind": "containsSubstring", "substring": "SENTINEL_STRING"}`                        |
| 17 | `fileExistsAtPath`      | `{"kind": "fileExistsAtPath"}`                                                          |
| 18 | `taskCompleted`         | `{"kind": "taskCompleted"}`                                                             |
| 19 | `custom`                | `{"kind": "custom", "custom_name": "myPredicateName"}`                                 |
| 20 | `ext`                   | `{"kind": "ext", "ext_key": "myExtensionKey"}`                                         |
| 21 | `predicateAnd`          | `{"kind": "predicateAnd", "left": {…}, "right": {…}}`  *(see below)*                  |
| 22 | `predicateOr`           | `{"kind": "predicateOr", "left": {…}, "right": {…}}`  *(see below)*                   |

### Detailed IR for Complex Predicates

#### `matchesJsonSchema` — with nested JsonSchema

```json
{
  "kind": "matchesJsonSchema",
  "schema": {
    "kind": "jObject",
    "fields": [
      ["bibtex", {"kind": "jString"}],
      ["file_path", {"kind": "jString"}],
      ["title", {"kind": "jString"}],
      ["abstract", {"kind": "jString"}]
    ]
  }
}
```

JsonSchema IR types:

| JsonSchema type      | IR JSON                                                                              |
| -------------------- | ------------------------------------------------------------------------------------ |
| `.jString`         | `{"kind": "jString"}`                                                              |
| `.jNum`            | `{"kind": "jNum"}`                                                                 |
| `.jBool`           | `{"kind": "jBool"}`                                                                |
| `.jNull`           | `{"kind": "jNull"}`                                                                |
| `.jAny`            | `{"kind": "jAny"}`                                                                 |
| `.jArray schema`   | `{"kind": "jArray", "element_schema": {…}}`                                       |
| `.jObject fields`  | `{"kind": "jObject", "fields": [["key1", {…}], ["key2", {…}]]}`                  |

Nested example — array of objects:

```json
{
  "kind": "matchesJsonSchema",
  "schema": {
    "kind": "jArray",
    "element_schema": {
      "kind": "jObject",
      "fields": [
        ["url", {"kind": "jString"}],
        ["file_path", {"kind": "jString"}]
      ]
    }
  }
}
```

#### `containsSubstring` — with sentinel string

```json
{"kind": "containsSubstring", "substring": "COMPLETE_TASK_AND_SUBMIT"}
```

#### `custom` — with custom predicate name

```json
{"kind": "custom", "custom_name": "isWellFormedResponse"}
```

#### `predicateAnd` / `predicateOr` — with nested predicates

```json
{
  "kind": "predicateAnd",
  "left": {"kind": "isValidJson"},
  "right": {
    "kind": "matchesJsonSchema",
    "schema": {"kind": "jObject", "fields": [["name", {"kind": "jString"}]]}
  }
}
```

```json
{
  "kind": "predicateOr",
  "left": {"kind": "isValidURL"},
  "right": {"kind": "isValidFilePath"}
}
```

> **Note**: For `predicateAnd`, in most cases it is more common (and equivalent) to use two separate entries in the `predicates` array or two separate `VarPredicateIR` entries.

### Full Node IR Example

```json
{
  "id": 1,
  "name": "extract_bibtex_by_tool",
  "step_type": "step",
  "reads": [
    {
      "name": "paper_title", "base_type": "TString",
      "predicates": [{"kind": "isNonEmptyString"}]
    },
    {
      "name": "url", "base_type": "TString",
      "predicates": [{"kind": "isValidURL"}]
    }
  ],
  "writes": [
    {
      "name": "bibtex_citation", "base_type": "TString",
      "predicates": [
        {"kind": "isNonEmptyString"},
        {"kind": "isValidBibtex"}
      ]
    }
  ],
  "instruction": "Use get_bibtex_from_url tool ...",
  "precond_extra": [
    { "var_name": "get_bibtex_from_url", "predicate": {"kind": "toolExists"} }
  ]
}
```

### Conditional Node IR Example

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

### Loop Node IR Example

```json
{
  "id": 3,
  "name": "main_loop",
  "step_type": "whileLoop",
  "reads": [
    { "name": "iter", "base_type": "TInt", "predicates": [{"kind": "isInt"}] }
  ],
  "writes": [],
  "loop_invariant": [
    { "var_name": "code_path", "predicate": {"kind": "isValidFilePath"} },
    { "var_name": "iter", "predicate": {"kind": "isInt"} },
    { "var_name": "term_send", "predicate": {"kind": "toolExists"} }
  ],
  "termination_kind": "llmControlledExit",
  "termination_sentinel": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
  "exit_postcond": [
    { "var_name": "final_output", "predicate": {"kind": "containsSubstring", "substring": "COMPLETE_TASK_AND_SUBMIT"} },
    { "var_name": "task_status", "predicate": {"kind": "taskCompleted"} }
  ]
}
```

### Workflow-Level `param_postcond` and `json_schemas`

```json
{
  "name": "my_module",
  "goal": "...",
  "parameters": [
    { "name": "url", "base_type": "TString", "predicates": [{"kind": "isValidURL"}] },
    { "name": "file_path", "base_type": "TString", "predicates": [{"kind": "isValidFilePath"}] }
  ],
  "param_postcond": [
    { "var_name": "url", "predicate": {"kind": "isValidURL"} },
    { "var_name": "file_path", "predicate": {"kind": "isValidFilePath"} },
    { "var_name": "fs_read", "predicate": {"kind": "toolExists"} },
    { "var_name": "my_module", "predicate": {"kind": "moduleExists"} }
  ],
  "json_schemas": {
    "mySchema": {
      "kind": "jObject",
      "fields": [["key1", {"kind": "jString"}], ["key2", {"kind": "jNum"}]]
    }
  },
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

> **Tip**: `json_schemas` is a top-level dictionary of named schemas. In node predicates, reference them by inlining the schema object directly into the `matchesJsonSchema` predicate's `schema` field.

---

## Implication Rules

The verifier has built-in implication rules. If a postcondition provides the left-side predicate, it can automatically satisfy a precondition requiring the right-side predicate.

### All Predicates → `nameExists`

The following predicates all automatically imply `nameExists`:
`isNonEmptyString`, `isNonEmptyList`, `isValidURL`, `isValidFilePath`, `isValidPath`, `isValidBibtex`, `isValidLatex`, `isValidJson`, `isValidList`, `toolExists`, `moduleExists`, `isInt`

### Special Implications

| Established (postcond)    | Can Satisfy (precond)                                |
| ------------------------- | ---------------------------------------------------- |
| `isValidURL`            | `isNonEmptyString`                                 |
| `isValidFilePath`       | `isNonEmptyString`                                 |
| `isValidBibtex`         | `isNonEmptyString`                                 |
| `isValidLatex`          | `isNonEmptyString`                                 |
| `matchesJsonSchema _`   | `isValidJson`                                      |
| `matchesJsonSchema _`   | `nameExists`                                       |
| `matchesJsonSchema s₁` | `matchesJsonSchema s₂` (when `s₁.implies s₂`) |

### Propositional Logic Rules

| Rule      | Meaning                                                  |
| --------- | -------------------------------------------------------- |
| And-Elim  | `(p₁ ∧ p₂) → p₁` and `(p₁ ∧ p₂) → p₂`      |
| Or-Intro  | `p₁ → (p₁ ∨ p₂)` and `p₂ → (p₁ ∨ p₂)`      |
| And-Intro | `p → (q₁ ∧ q₂)` when `p → q₁` and `p → q₂` |
| Or-Elim   | `(p₁ ∨ p₂) → q` when `p₁ → q` and `p₂ → q` |

---

## Detailed Per-Predicate Usage with Examples

### 1. `varNameExists` — Variable Exists

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

### 2. `varIsNonEmptyString` — Non-Empty String

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

### 3. `varIsNonEmptyList` — Non-Empty List

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

### 4. `varIsInt` — Integer Variable

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

---

### 5. `varIsValidURL` — Valid URL

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

### 6. `varIsValidFilePath` — Valid File Path

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

### 7. `varIsValidPath` — Valid Path (Generalized)

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

---

### 8. `varIsValidBibtex` — Valid BibTeX

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

### 9. `varIsValidLatex` — Valid LaTeX

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

### 10. `varIsValidJson` — Valid JSON

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

### 11. `varIsValidList` — Valid List

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

---

### 12. `varIsValidTool` — Tool Available

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

### 13. `varIsValidModule` — Submodule Available

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

---

### 14. `varIsValidJsonSchema` — JSON Schema Match

**PredicateType**: `.matchesJsonSchema schema`
**Signature**: `varIsValidJsonSchema (varName : String) (schema : JsonSchema)`
**Semantics**: `∃ j, env.get name = some (.vJson j) ∧ JsonMatchesSchema j schema` — recursively checks JSON structure.
**Use case**: Structured JSON outputs (return_dict, extraction_params, etc.).
**Note**: Automatically implies `isValidJson` and `nameExists`.
**IR JSON**: `{"kind": "matchesJsonSchema", "schema": {"kind": "jObject", "fields": [["key", {"kind": "jString"}]]}}` *(see IR JSON Representation section for full JsonSchema format)*

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

**Available JsonSchema types**:

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

### 15. `varIsValidJsonFields` — JSON Field Check

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

---

### 16. `varContainsSentinel` — Contains Sentinel Substring

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

### 17. `varFileExistsAtPath` — File Exists Marker

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

### 18. `varTaskCompleted` — Task Completed Marker

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

### 19. `varIsValidCustomPredicate` — Custom Predicate

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

---

### 20. `.ext key` — Extensible Predicate

**PredicateType**: `.ext (key : PredicateKey)`
**No shorthand function** — requires direct construction of `VariablePredicateRequirement`.
**Semantics**: Provided by `PredicateRegistry` at runtime.
**Use case**: Advanced scenarios — Dict value predicates for parallel submodules (`DictAllValuesPredicate`), etc.
**IR JSON**: `{"kind": "ext", "ext_key": "myExtensionKey"}`

```lean
-- Step 1: Define DictAllValuesPredicate
def myDictPred : DictAllValuesPredicate := {
dictValuePredicates := [.isValidJson, .matchesJsonSchema mySchema]
dictVarName := "all_results"
}

-- Step 2: Convert to PredicateKey and PredicateType
def myDictPredKey : PredicateKey := myDictPred.toPredicateKey
def myDictPredType : PredicateType := .ext myDictPredKey

-- Step 3: Use in precond (direct construction)
def semNode3 : SemanticWorkflowNode := {
baseNode := ...
precondVariables := [
    { varName := "all_results"
    requiredPredicate := myDictPredType }
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

### 21. `varPredicateAnd` — Predicate Conjunction

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

### 22. `varPredicateOr` — Predicate Disjunction

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

---

## Special Node Types and Their Predicate Usage

### Parameter Node

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

### Loop Node

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

### Conditional Node

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

---

## Quick Selection Guide

| Your variable is...            | Recommended Predicate                         |
| ------------------------------ | --------------------------------------------- |
| LLM-generated text output      | `varIsNonEmptyString`                       |
| File path                      | `varIsValidFilePath`                        |
| URL                            | `varIsValidURL`                             |
| Loop counter                   | `varIsInt`                                  |
| Tool name                      | `varIsValidTool`                            |
| Submodule name                 | `varIsValidModule`                          |
| Structured JSON output         | `varIsValidJson` + `varIsValidJsonSchema` |
| BibTeX citation                | `varIsValidBibtex`                          |
| Only need variable to exist    | `varNameExists`                             |
| Loop termination sentinel      | `varContainsSentinel`                       |
| Task completion marker         | `varTaskCompleted`                          |
| Parallel submodule Dict result | `.ext` + `PredicateRegistry`              |