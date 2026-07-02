# Predicate System Index

> **Purpose**: Compact lookup table for automated formalization of Agent Plans. Each `PredicateType` maps to a `VariablePredicateRequirement` shorthand (`var*`), used in `precondVariables` / `postcondVariables` of `SemanticWorkflowNode`. For detailed usage with Lean/IR examples, see the linked files.

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

- `precondVariables : List VariablePredicateRequirement` — conditions **before** step executes
- `postcondVariables : List VariablePredicateRequirement` — conditions guaranteed **after** step executes

```lean
structure VariablePredicateRequirement where
  varName : String
  requiredPredicate : PredicateType
```

---

## Complete Predicate Mapping Table

> **Details file column**: Click the link for full Lean examples, IR JSON format, and use case guidance.

| #  | PredicateType                 | Var Shorthand              | Semantics (brief)                                      | Typical Use Case                    | Details                                            |
| -- | ----------------------------- | -------------------------- | ------------------------------------------------------ | ----------------------------------- | -------------------------------------------------- |
| 1  | `.nameExists`                 | `varNameExists`            | Variable exists (`∃ v, env.get name = some v`)         | Weakest check; conditional branches | [predicates_basic.md](predicates_basic.md#1)       |
| 2  | `.isNonEmptyString`           | `varIsNonEmptyString`    | Non-empty string                                       | LLM text outputs, analysis results  | [predicates_basic.md](predicates_basic.md#2)       |
| 3  | `.isNonEmptyList`             | `varIsNonEmptyList`      | Non-empty list                                         | Search results, batch data          | [predicates_basic.md](predicates_basic.md#3)       |
| 4  | `.isInt`                      | `varIsInt`               | Integer value                                          | Loop counters (`iter`)              | [predicates_basic.md](predicates_basic.md#4)       |
| 5  | `.isValidURL`                 | `varIsValidURL`          | Non-empty string containing `"://"`                  | URL parameters                      | [predicates_path_url.md](predicates_path_url.md#5) |
| 6  | `.isValidFilePath`            | `varIsValidFilePath`     | Non-empty string containing `"/"`                    | File path parameters                | [predicates_path_url.md](predicates_path_url.md#6) |
| 7  | `.isValidPath`                | `varIsValidPath`         | Non-empty string (generalized)                         | Generic path                        | [predicates_path_url.md](predicates_path_url.md#7) |
| 8  | `.isValidBibtex`              | `varIsValidBibtex`       | Non-empty string containing `"@"`                    | BibTeX citations                    | [predicates_content.md](predicates_content.md#8)   |
| 9  | `.isValidLatex`               | `varIsValidLatex`        | Non-empty string containing `"\\"`                   | LaTeX content                       | [predicates_content.md](predicates_content.md#9)   |
| 10 | `.isValidJson`                | `varIsValidJson`         | JSON value                                             | JSON-format data                    | [predicates_content.md](predicates_content.md#10)  |
| 11 | `.isValidList`              | `varIsValidList`         | List value (may be empty)                              | List-type data                      | [predicates_content.md](predicates_content.md#11)  |
| 12 | `.toolExists`               | `varIsValidTool`         | Tool name exists (≡ `nameExists`)                    | Declare tool available              | [predicates_tool_module.md](predicates_tool_module.md#12) |
| 13 | `.moduleExists`             | `varIsValidModule`       | Module name exists (≡ `nameExists`)                  | Declare submodule available         | [predicates_tool_module.md](predicates_tool_module.md#13) |
| 14 | `.matchesJsonSchema schema` | `varIsValidJsonSchema`   | JSON matches schema (recursive)                        | Structured JSON output              | [predicates_json_schema.md](predicates_json_schema.md#14) |
| 15 | `.isJsonWithFields fields`  | `varIsValidJsonFields`   | JSON object contains fields                            | Partial structure validation        | [predicates_json_schema.md](predicates_json_schema.md#15) |
| 16 | `.containsSubstring s`      | `varContainsSentinel`    | String contains substring                              | Loop termination sentinel           | [predicates_semantic.md](predicates_semantic.md#16) |
| 17 | `.fileExistsAtPath`         | `varFileExistsAtPath`    | ≡ `isNonEmptyString` (semantic marker)               | File created marker                 | [predicates_semantic.md](predicates_semantic.md#17) |
| 18 | `.taskCompleted`            | `varTaskCompleted`       | ≡ `nameExists` (semantic marker)                     | Task completion marker              | [predicates_semantic.md](predicates_semantic.md#18) |
| 19 | `.custom name`              | `varIsValidCustomPredicate` | ≡ `nameExists` (custom fallback)                  | Custom semantic markers             | [predicates_semantic.md](predicates_semantic.md#19) |
| 20 | `.ext key`                  | *(direct construction)*  | Semantics via `PredicateRegistry`                    | Dict predicates, extensions         | [predicates_advanced.md](predicates_advanced.md#20) |
| 21 | `.predicateAnd p₁ p₂`     | `varPredicateAnd`        | `p₁ ∧ p₂`                                          | Conjunction                         | [predicates_advanced.md](predicates_advanced.md#21) |
| 22 | `.predicateOr p₁ p₂`      | `varPredicateOr`         | `p₁ ∨ p₂`                                          | Disjunction                         | [predicates_advanced.md](predicates_advanced.md#22) |

---

## IR JSON Quick Reference

> Full IR format details, complex predicate IR, and node IR examples: **[ir_json_format.md](ir_json_format.md)**

### Per-Predicate IR Format

| PredicateType             | IR JSON (`predicate` object)                                            |
| ------------------------- | ----------------------------------------------------------------------- |
| `nameExists`            | `{"kind": "nameExists"}`                                             |
| `isNonEmptyString`      | `{"kind": "isNonEmptyString"}`                                       |
| `isNonEmptyList`        | `{"kind": "isNonEmptyList"}`                                         |
| `isInt`                 | `{"kind": "isInt"}`                                                  |
| `isValidURL`            | `{"kind": "isValidURL"}`                                             |
| `isValidFilePath`       | `{"kind": "isValidFilePath"}`                                        |
| `isValidPath`           | `{"kind": "isValidPath"}`                                            |
| `isValidBibtex`         | `{"kind": "isValidBibtex"}`                                          |
| `isValidLatex`          | `{"kind": "isValidLatex"}`                                           |
| `isValidJson`           | `{"kind": "isValidJson"}`                                            |
| `isValidList`           | `{"kind": "isValidList"}`                                            |
| `toolExists`            | `{"kind": "toolExists"}`                                             |
| `moduleExists`          | `{"kind": "moduleExists"}`                                           |
| `matchesJsonSchema`     | `{"kind": "matchesJsonSchema", "schema": {…}}`                     |
| `containsSubstring`     | `{"kind": "containsSubstring", "substring": "..."}`                 |
| `fileExistsAtPath`      | `{"kind": "fileExistsAtPath"}`                                       |
| `taskCompleted`         | `{"kind": "taskCompleted"}`                                          |
| `custom`                | `{"kind": "custom", "custom_name": "..."}`                          |
| `ext`                   | `{"kind": "ext", "ext_key": "..."}`                                 |
| `predicateAnd`          | `{"kind": "predicateAnd", "left": {…}, "right": {…}}`             |
| `predicateOr`           | `{"kind": "predicateOr", "left": {…}, "right": {…}}`              |

> `isJsonWithFields` is not yet supported in IR — use `matchesJsonSchema` instead.

---

## Implication Rules

The verifier has built-in implication rules. If a postcondition provides the left-side predicate, it can automatically satisfy a precondition requiring the right-side predicate.

### All Predicates → `nameExists`

These predicates all automatically imply `nameExists`:
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

---

## Special Node Types

> Lean structure examples: **[node_types.md](node_types.md)**
> **How to write predicates per node type (IR JSON → Lean codegen)**: **[node_predicate_guide.md](node_predicate_guide.md)**

- **Parameter Node** — Declares workflow parameters, available tools, and modules (postcond only, no precond)
- **Loop Node** — Has `loopInvariant` + `exitPostconditions` + `terminationSpec`
- **Conditional Node** — Has `thenPostcondVariables` + `elsePostcondVariables` for branch-specific guarantees

---

## File Index

| File                                                          | Contents                                                    |
| ------------------------------------------------------------- | ----------------------------------------------------------- |
| [ir_json_format.md](ir_json_format.md)                        | IR JSON contexts, complex predicates, node IR examples      |
| [predicates_basic.md](predicates_basic.md)                    | #1-4: nameExists, isNonEmptyString, isNonEmptyList, isInt   |
| [predicates_path_url.md](predicates_path_url.md)              | #5-7: isValidURL, isValidFilePath, isValidPath              |
| [predicates_content.md](predicates_content.md)                | #8-11: isValidBibtex, isValidLatex, isValidJson, isValidList |
| [predicates_tool_module.md](predicates_tool_module.md)        | #12-13: toolExists, moduleExists                            |
| [predicates_json_schema.md](predicates_json_schema.md)        | #14-15: matchesJsonSchema, isJsonWithFields                 |
| [predicates_semantic.md](predicates_semantic.md)              | #16-19: containsSubstring, fileExistsAtPath, taskCompleted, custom |
| [predicates_advanced.md](predicates_advanced.md)              | #20-22: ext, predicateAnd, predicateOr                      |
| [node_types.md](node_types.md)                                | Parameter / Loop / Conditional node patterns (Lean examples) |
| [node_predicate_guide.md](node_predicate_guide.md)            | How to annotate each node type in IR JSON for codegen       |
