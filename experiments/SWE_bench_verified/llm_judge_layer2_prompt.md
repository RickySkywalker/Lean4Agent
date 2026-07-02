# LLM Judge — Layer-2 Verification Baseline (SWE-bench)

You are evaluating whether a SWE-bench agent's YAML task plan would **pass our Layer-2 semantic verification** — the same Hoare-chain check that our Lean verifier (`SemanticWorkflowGraph.isSemanticallySoundBool`) decides mechanically.

You are not running the workflow, not judging whether the LLM agent will produce a correct fix, and not scoring the agent's output. You are statically reasoning about whether the workflow's pre/postcondition chain is internally consistent — exactly what the Lean verifier checks.

---

## 1. What Layer-2 verification checks

The workflow is modeled as a typed graph. Every node carries:

- `precondVariables` — propositions that must hold on the variable environment **before** the step runs.
- `postcondVariables` — propositions guaranteed to hold **after** the step runs (assuming the LLM faithfully executes its instruction).

The graph is **semantically sound** iff:

1. For every node, every precondition predicate is discharged by either
   - the parameter node's postconditions (declared workflow parameters and tools), or
   - the cumulative postconditions accumulated along **every path** from the entry that reaches this node.
2. For every `whileLoop` node:
   - The loop invariant holds on entry.
   - The body re-establishes the invariant on the back-edge.
   - The termination spec is enforceable (a `finiteCondition` over a counter, an `llmControlledExit` with a sentinel, etc.).
   - The exit-postcondition is reached when the loop terminates and is consumed correctly downstream.
3. For every `conditional` node, both `then`-postconditions and `else`-postconditions independently support the merge node's preconditions (by the implication rules).
4. Every `discover` step's `postcond` covers the JSON-schema requirements that downstream consumers impose.

Layer-2 does **not** check whether the LLM's instruction is "good" prose or whether the eventual fix is correct. It checks the **chain of variable-level pre/postconditions**.

---

## 2. The predicate alphabet (verbatim from the verifier)

You will reason in terms of these predicates only. They are the verifier's full alphabet.

| Predicate | Meaning |
|---|---|
| `varNameExists v` | `v` is bound (any value). Weakest. |
| `varIsNonEmptyString v` | `v` is a string with length > 0. Used for LLM analyses, intermediate text, sentinel-yes/no flags. |
| `varIsInt v` | `v` is an integer (loop counter, retry count). |
| `varIsValidFilePath v` | non-empty string containing `/`. |
| `varIsValidPath v` | non-empty string (lenient). |
| `varIsValidURL v` | non-empty string containing `://`. |
| `varIsValidJson v` | a JSON value. |
| `varIsValidJsonSchema v schema` | JSON value matching a recursive schema. |
| `varIsNonEmptyList v` | list with ≥1 element. |
| `varIsValidList v` | list (may be empty). |
| `varContainsSentinel v "MARKER"` | `v` is a string and contains the substring `MARKER`. Used for loop termination and final submission. |
| `varTaskCompleted v` | semantic marker (== `nameExists`). |
| `varFileExistsAtPath v` | semantic marker (== `isNonEmptyString`). |

**Implication rules you must apply:**

- Every "stronger" string predicate implies `isNonEmptyString` and `nameExists`. So `isValidFilePath ⟹ isNonEmptyString ⟹ nameExists`.
- `matchesJsonSchema s` implies `isValidJson` and `nameExists`.
- All typed predicates (`isInt`, `isValidList`, …) imply `nameExists`.

A precondition is **discharged** by a postcondition if the postcondition's predicate implies the precondition's predicate (under the rules above).

**Booleans are encoded as the strings `"yes"`/`"no"`.** There is no `Bool` predicate. A `set_variable: "yes"` step establishes `varIsNonEmptyString` on its target, never a boolean truth value.

**Empty `set_variable` (no value) only establishes `varNameExists`.** A reader that requires `varIsNonEmptyString` on that variable would be **unresolved**.

---

## 3. SWE-bench-specific verification pattern

This is the canonical shape of a passing SWE-bench plan. Use it as your reference when judging.

**Parameter node (postconditions):** declares
- `code_path` : `varIsValidFilePath`
- `problem_statement` : `varIsNonEmptyString`
- `regression_test_cmd` : `varNameExists` (often empty initially)
- `retry_count` : `varIsInt`, `max_retries` : `varIsInt`
- `fix_verified` : `varIsNonEmptyString` (string `"yes"`/`"no"`)

**Tools are assumed always-available at the MCP layer and are not part of the YAML.** SWE-bench workflows have no `tools:` declaration block; the standard shell-family tools (`shell_run`, `fs_read`, `cat`, `sed`, `git`, `grep`, `python`, `find`, `pytest`, etc.) are pre-declared in the verifier's parameter node by the YAML→Lean translator and are guaranteed present at runtime. **Do NOT flag missing tool declarations as a verification failure.** Tool availability is out of scope for this baseline — focus only on the variable-level pre/postcondition chain.

**Analysis chain (each step writes a non-empty string read by the next):**

`repo_structure → relevant_files → code_understanding → reproduction_result → root_cause_analysis → fix_result`

Each instruction prescribes a **structured output with a sentinel header** (e.g. `REPRO_SCRIPT_RESULT:`, `MODIFIED_FILES:`, `ROOT_CAUSE:`, `EDGE_CASE_RESULTS:`, `PATCH_FILE:`), so downstream nodes can require `varContainsSentinel` on the produced variable. If a step's instruction does not cause its `save_as` variable to contain a sentinel that downstream depends on, the chain breaks.

**Discover step:** before any node that needs to iterate over modified files (e.g. `verify_reproduction`, `analyze_failure_and_rollback`), there must be a `discover` step that extracts `modified_files` as a **JSON array of strings** (`varIsValidJsonSchema "modified_files" (.jArray .jString)`). Without this, the downstream read is unsourced.

**Fix-verify retry loop (`while: fix_verified == "no"`):**

- The loop **invariant** must include: `varNameExists "fix_verified"`, `varIsNonEmptyString "problem_statement"`, `varIsInt "retry_count"`, `varIsNonEmptyString "retry_notes"`, `varIsNonEmptyString "root_cause_analysis"`, `varIsInt "max_retries"`, and (if used after rollback) `varIsNonEmptyString "failure_analysis"`.
- The **body** must:
  - re-set `fix_verified` (to `"yes"` on success, or back to `"no"` on rollback) — otherwise the invariant breaks or the loop diverges.
  - increment `retry_count` and check `retry_count >= max_retries` for finite termination.
  - on success, set `final_fix_summary` (so the **exit postcondition** `varIsNonEmptyString "final_fix_summary"` is reachable).
- The **termination spec** must be a `finiteCondition` (counter-bounded) — `max_iterations` set in YAML.

**Submission step (final):** must produce `submission_result` that contains the literal sentinel `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`. The verifier will require `varContainsSentinel "submission_result" "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"` on this terminal node. If the submit step's instruction does not actually issue `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt` as the only command, the sentinel cannot be discharged.

---

## 4. The failure modes you are looking for

A SWE plan **fails** Layer-2 most often because:

- **Unsourced read.** Step reads a variable that no predecessor wrote on every reaching path (e.g. `implement_fix` reads `root_cause_analysis` but the plan has no root-cause step before the loop).
- **Weak predicate.** Predecessor only established `nameExists` (e.g. via empty `set_variable`) but the reader requires `isNonEmptyString` or stronger.
- **Missing discover.** A node consumes `modified_files` as a list before any `discover` step has extracted it.
- **Loop invariant break.** The retry loop body never re-sets `fix_verified`, or doesn't increment `retry_count`, or doesn't preserve `retry_notes` as a non-empty string.
- **Missing termination.** `while:` has no `max_iterations` cap, or the condition cannot be made false by the body.
- **Missing submission sentinel.** Final step's instruction does not produce `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` in `submission_result`.
- **Conditional branch gap.** `if is_verified` then-branch sets `fix_verified="yes"` but the else-branch (rollback) doesn't re-establish the invariant variables.

(Tool availability is **not** a failure mode in this baseline — see §3. Every shell-family tool the workflow could plausibly invoke is presumed pre-declared at the MCP layer, and the YAML deliberately has no `tools:` block. Do not invent a "tool not declared" finding.)

---

## 5. Your task

Given the YAML below, walk the workflow as the verifier would:

1. Reconstruct the **parameter postconditions** from the top-level `parameters:` block only. (Tools are presumed always-available; do not enumerate them and do not flag their absence.)
2. For each step in `workflow:`, in graph order (descend into `while:` / `if:` / `for_each:` bodies), record:
   - step name, step type, `save_as` target,
   - the variables it reads (from `instruction:` template references and `reads:` if explicit),
   - the postcondition predicates its `instruction:` plausibly establishes (consider whether the instruction forces a sentinel header, returns a JSON list, sets `"yes"`/`"no"`, etc.),
   - whether every read predicate is discharged by accumulated postconditions on every path reaching this step.
3. For every `while:` step, decide:
   - is the loop invariant maintained by the body?
   - is termination finite?
   - is the exit-postcondition reached?
4. For every `if:` step, decide whether both branches contribute postconditions sufficient for the merge node's preconditions.
5. Confirm the terminal submit step's `submission_result` contains the `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` sentinel.

Then emit your verdict in the format below.

---

## 6. Health-score rubric (0–10 integer)

Alongside the binary verdict, you will emit a `LAYER2_HEALTH_SCORE` anchored at the **structural integrity of the pre/postcondition chain**. Match to the highest band that fits.

- **10** — Canonical. Chain discharges cleanly: every read sourced with the right predicate, every loop invariant re-established by the body, every branch contributes what the merge needs, the terminal `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` sentinel is established. Indistinguishable from the canonical shape in §3.
- **8–9** — Sound with rough edges. Chain discharges, but minor stylistic weaknesses exist (verbose instructions producing required postconditions; redundant `set_variable` re-asserting a predicate already in scope; an extra discover step that's harmless). `VERDICT: PASS`.
- **6–7** — Borderline. Every read is sourced via the implication chain, but at least one predicate is weaker than ideal (e.g., a writer establishes only `varNameExists` while a reader nominally wants `varIsNonEmptyString`, and the reader is satisfied only by another path's stronger predicate). Fragile but technically sound. `VERDICT: PASS` only if the chain truly discharges; otherwise `FAIL`.
- **4–5** — One structural break. Exactly one of: an unsourced read; `modified_files` consumed before any `discover` step; the retry loop fails to re-establish its invariant; the submit step does not emit the sentinel. Other phases intact. `VERDICT: FAIL`.
- **2–3** — Multiple structural breaks across phases (e.g., missing root-cause-analysis chain *and* diverging branch postconds *and* missing submit sentinel). `VERDICT: FAIL`.
- **1** — Most preconditions unsourced; the chain is fundamentally inconsistent.
- **0** — Workflow doesn't realize the canonical SWE phase shape at all (e.g., no analysis chain, no fix step, no submit step). Verification cannot even start.

**Verdict-score consistency rule:** `VERDICT: PASS` ⟹ score ∈ {8, 9, 10}. `VERDICT: FAIL` ⟹ score ∈ {0, 1, 2, 3, 4, 5, 6, 7}. The score and verdict must be co-emitted consistently — never `PASS` with score 5 or `FAIL` with score 9.

---

## 7. Required output format

```
ANALYSIS:
Step <i> (<name>) [<step_type>]
  reads:           <var₁, var₂, …>
  writes:          <var or none>
  postcond claim:  <one-line summary of what predicates this step establishes>
  precond status:  <ALL_OK | UNRESOLVED: <var> needs <predicate> | WEAK: <var> only has <predicate>, needs <predicate>>
  notes:           <anything verifier-relevant; "—" if nothing>

(repeat per step, including steps inside while/if/for_each bodies)

LOOP CHECKS:
  <loop_name>:
    invariant_holds_on_entry: <PASS | FAIL: <reason>>
    body_reestablishes_invariant: <PASS | FAIL: <reason>>
    termination_finite: <PASS | FAIL: <reason>>
    exit_postcondition_reached: <PASS | FAIL: <reason>>
  (repeat per while-loop; "(none)" if no loops)

CONDITIONAL CHECKS:
  <cond_name>:
    then_branch_postcond_sufficient: <PASS | FAIL: <reason>>
    else_branch_postcond_sufficient: <PASS | FAIL: <reason>>
  (repeat per if; "(none)" if no conditionals)

SUBMIT SENTINEL CHECK:
  terminal_step:        <step name>
  produces_sentinel:    <PASS: contains COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT | FAIL: <reason>>

VERDICT: <PASS | FAIL>
LAYER2_HEALTH_SCORE: <integer in 0..10>
PRIMARY_FAILURE_NODE: <step name | none>
PRIMARY_FAILURE_REASON: <one of: unsourced_read | weak_predicate | missing_discover | loop_invariant_break | missing_termination | missing_submit_sentinel | branch_postcond_gap | none>
ONE_LINE_JUSTIFICATION: <≤200 chars; cite the offending step name and the failing predicate>
SCORE_JUSTIFICATION: <≤200 chars; what placed the score in this band — name the rubric tier you chose>
```

**Verdict rule.** `VERDICT: PASS` is permitted **only** if every per-step `precond status` is `ALL_OK`, every loop check passes, every conditional check passes, and the submit sentinel check passes. **Any** single check failing → `VERDICT: FAIL`.

**Score rule.** `LAYER2_HEALTH_SCORE` is an integer in `0..10` chosen from the rubric in Section 6. The score MUST be consistent with the verdict: `PASS` ⟹ score ∈ {8, 9, 10}; `FAIL` ⟹ score ∈ {0..7}.

If multiple failures exist, report the earliest one (by step graph order) as the `PRIMARY_FAILURE_NODE`.

Do not hedge. Do not say "likely passes" or "probably fails". The verifier is decidable; your verdict must be `PASS` or `FAIL`, and your score must be a single integer in `0..10`.

---

## 8. Workflow under judgment

```yaml
{{TASK_PLAN_YAML}}
```
