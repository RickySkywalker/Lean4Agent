# IR JSON Representation — Detailed Format Reference

> Back to [index](index.md)

Predicates appear in two contexts in the IR JSON: inside **TypedVar** (reads/writes arrays) and as standalone **VarPredicateIR** entries.

---

## Context 1: Inside TypedVar (`reads` / `writes`)

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

## Context 2: VarPredicateIR (precond/postcond lists)

Used in: `param_postcond`, `precond_extra`, `postcond_extra`, `then_postcond`, `else_postcond`, `loop_invariant`, `exit_postcond`

```json
{ "var_name": "fs_read", "predicate": {"kind": "toolExists"} }
```

---

## Complex Predicate IR Formats

### `matchesJsonSchema` — with nested JsonSchema

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

#### JsonSchema IR types

| JsonSchema type      | IR JSON                                                       |
| -------------------- | ------------------------------------------------------------- |
| `.jString`         | `{"kind": "jString"}`                                       |
| `.jNum`            | `{"kind": "jNum"}`                                          |
| `.jBool`           | `{"kind": "jBool"}`                                         |
| `.jNull`           | `{"kind": "jNull"}`                                         |
| `.jAny`            | `{"kind": "jAny"}`                                          |
| `.jArray schema`   | `{"kind": "jArray", "element_schema": {…}}`                |
| `.jObject fields`  | `{"kind": "jObject", "fields": [["key1", {…}], ["key2", {…}]]}` |

#### Nested example — array of objects

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

### `containsSubstring` — with sentinel string

```json
{"kind": "containsSubstring", "substring": "COMPLETE_TASK_AND_SUBMIT"}
```

### `custom` — with custom predicate name

```json
{"kind": "custom", "custom_name": "isWellFormedResponse"}
```

### `predicateAnd` / `predicateOr` — with nested predicates

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

---

## Full Node IR Examples

### Step Node

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

### Conditional Node

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

### Loop Node

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
