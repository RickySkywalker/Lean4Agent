# Layer-3 IR & json→Lean codegen — design

This document specifies the **unified Layer-3 IR** and the single codegen that
turns it into Lean for **both** the SWE-bench and ELAIP pipelines. It replaces
the now-removed legacy SWE path (`TaskPlanToLean.generate_layer3_lean` /
`_gen_layer3_tail`, which targeted the old `AgentVerifier.DynamicVerification.*`).

The emitted Lean targets the rebuilt dynamic layer in
`FormalAgentLib/AgentVerifier/DynamicVerification/` (namespace `AgenticKernel.Dyn`)
— the same surface the hand-written references in
`FormalAgentLib/DynamicLayerExamples/` use.

---

## 1. The model: a Layer-3 eval = 4 input blocks, only 1 written by an LLM

A Layer-3 verification of `(workflow, trajectory)` against a Layer-2 contract is
assembled from four blocks. Three are mechanical; exactly one needs an LLM.

| # | Block | Who writes it | Source |
|---|---|---|---|
| 1 | **Layer-2 contract** (`semanticGraph` + `goalSpec`, incl. info-flow fields) | already exists | a `*_layer2_*.lean` module |
| 2 | **runtime wiring** (`execState`, `stepEntries`, `stepIdMap`, `dynamicGraph`) | **mechanical codegen** | `agent_events.log` |
| 3 | **Tool verdict** (did the tests actually pass) | **Lean, at runtime** | SWE: `report.json`; ELAIP: post-state |
| 4 | **`llmInjections`** (per-step: was each postcondition really achieved) | **← the only LLM-written block** | the LLM reads the trajectory evidence |

The three verification *methods* (Lean symbolic ∧ Tool ∧ LLM) are composed inside
the Lean layer by **authority routing** (`composePredicateVerdict` in §7): a
content-decidable predicate trusts Lean; a placeholder predicate trusts the Tool
if a real attribution rule fired, else the LLM, else does not veto. The codegen
never composes verdicts itself — it only supplies blocks 1, 2 and the *injected*
block 4, plus the path for block 3.

---

## 2. The unified IR (`ir_kind: "layer3_v2"`)

```jsonc
{
  "ir_kind": "layer3_v2",
  "benchmark": "swe" | "elaip",          // selects the Tool channel + runner
  "plan_name": "passed_workflow_1",
  "instance_id": "astropy__astropy-7166", // SWE id, or ELAIP question id
  "namespace_suffix": "astropy_7166",      // → namespace AgenticKernel.<plan>_<suffix>_v2

  // ── BLOCK 1 — Layer-2 reference ──────────────────────────────────────────
  "layer2_ref": {
    // (a) IMPORT mode — standalone files (ELAIP + the hand-written examples):
    "mode": "import",
    "layer2_module":      "VerificationExamples.passed_workflow_1_layer2_new",
    "open_namespace":     "AgenticKernel.passed_workflow_1_layer2_new", // "" = no open
    "semantic_graph_def": "passed_workflow_1_v2SemanticGraph",
    "goal_spec_def":      "passed_workflow_1_v2_goalSpec"

    // (b) INLINE mode — the transfer pipeline (no importable L2 module):
    //   "mode": "inline", "prefix": "passed_workflow_1_v2", "workflow": { <WorkflowIR> }
    //   semantic_graph_def/goal_spec_def default to "<prefix>SemanticGraph"/"<prefix>_goalSpec"
  },

  // ── BLOCK 2 — runtime wiring (mechanical, from agent_events.log) ──────────
  "event_log_path": "/abs/.../astropy__astropy-7166_agent_events.log",
  "step_entries":  [["explore_repository","1"], ["reproduce_issue","2"], ...], // (l2_node_name, step_id)
  "dyn_nodes":     [{"node_name":"...","trajectory_step_name":"...",
                     "trajectory_step_id":"1","execution_status":"completed"}, ...],
  "exec_state":    [["problem_statement","..."], ["code_path","/testbed"], ...],

  // ── BLOCK 3 — Tool verdict path (SWE only; Lean reads it at runtime) ──────
  "report_path": "/abs/.../report.json",   // omit for ELAIP

  // ── BLOCK 4 — LLM judgements (THE ONLY LLM-WRITTEN BLOCK) ────────────────
  "llm_injections": [
    {"step_name":"explore_repository","var_name":"repository_understanding",
     "holds":true,"confidence":0.86,"llm_explanation":"...","node_instruction":""},
    ...
  ],

  // ── cosmetic (only in #eval! output) ─────────────────────────────────────
  "label": "astropy__astropy-7166",
  "header_comment": "..."
}
```

### `step_entries` vs `dyn_nodes`
`step_entries` is the canonical block-2 input: a list of
`(l2_node_name, trajectory_step_id)`. The by-name builders
(`ElaipBench.buildStepIdMapByName` / `buildDynamicGraphByName`) resolve each name
against the imported `semanticGraph` — so there is **no off-by-one** (the old
0-indexed `StepIdMap.fromGraph` mismatched 1-indexed agent traces). If
`step_entries` is omitted, it is derived from `dyn_nodes` (completed only), whose
`trajectory_step_name`/`trajectory_step_id` both pipelines already produce.

### Invariant: node name == trajectory step name
By-name resolution requires the Layer-2 node `name` to equal the trajectory step
name (e.g. `explore_repository`). This is how the agent framework pairs steps to
plan nodes anyway. A name that does not resolve is silently dropped by the
builder (same behaviour as the ELAIP path has always had).

---

## 3. Two modes: import vs inline

| | **import** | **inline** |
|---|---|---|
| When | ELAIP; standalone SWE examples | SWE transfer pipeline (no importable L2) |
| L2 | `import <module>` | emitted in-place via `TaskPlanToLean_v2.generate_layer2_lean_v2` |
| Namespace | `namespace AgenticKernel.<plan>_<suffix>_v2` | the inlined `namespace AgenticKernel` |
| L2 visibility | `open <open_namespace>` (or none) | same namespace — direct |

The **L3 tail is identical in both modes** (`render_l3_v2_tail`): it only
references `<semantic_graph_def>` (in scope either way) and the surface.

### Namespace convention (block 1) — SWE vs ELAIP
- SWE `*_layer2_new.lean` uses a **nested** `namespace AgenticKernel.<module>`,
  so the L3 file **needs** `open <open_namespace>`.
- ELAIP `*_layer2_v2.lean` declares the graph in the **flat** `namespace
  AgenticKernel`, which is visible from the nested analysis namespace **without**
  an `open` → the ELAIP adapter sets `open_namespace: ""`.

---

## 4. SWE vs ELAIP — the only real differences

| | SWE | ELAIP |
|---|---|---|
| Tool channel (block 3) | `let report ← InstanceReport.loadFromFile reportPath` + `SWEBench.rulesFromReport report` | `ElaipBench.rulesFromState execState` (no report.json) |
| `reportPath` def | emitted | absent |
| L2 namespace | nested → `open` needed | flat → no `open` |

Everything else — `execState`, `stepEntries`, `stepIdMap`, `dynamicGraph`,
`llmInjections`, `analyzeAllSteps`, `renderFullReport`, `layer3ToJson` — is
shared verbatim.

---

## 5. Emitted Lean (import mode, SWE)

```lean
import Lean ; import Mathlib ; import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates
import <layer2_module>
import AgentVerifier.DynamicVerification.DynamicVerification

namespace AgenticKernel.<plan>_<suffix>_v2
open AgenticKernel.Dyn
open <open_namespace>

def reportPath   : System.FilePath := "…"          -- SWE only
def eventLogPath : System.FilePath := "…"
def stepEntries  : List (String × String) := [ ("explore_repository","1"), … ]
def execState    : NodeExecutionState := makeExecutionState [ … ]
def stepIdMap    : StepIdMap := ElaipBench.buildStepIdMapByName <graph> stepEntries
def dynamicGraph : DynamicVerificationGraph := ElaipBench.buildDynamicGraphByName <graph> execState stepEntries
def llmInjections : List PerPredicateLLMInjection := [ … ]

#eval! (do
  let report ← SWEBench.InstanceReport.loadFromFile reportPath
  IO.println s!"… resolved={report.resolved}, F2P fail=…, P2P fail=…"
  let trace ← ExecutionTrace.loadEventLog eventLogPath
  let rules := SWEBench.rulesFromReport report
  let analyses := analyzeAllSteps dynamicGraph trace stepIdMap rules llmInjections
  IO.println (renderFullReport dynamicGraph trace analyses (stepIdMap := stepIdMap) (label := "…"))
  IO.println (layer3ToJson dynamicGraph trace analyses (stepIdMap := stepIdMap) (label := "…")).compress
  : IO Unit)

end AgenticKernel.<plan>_<suffix>_v2
```

ELAIP differs only in the two `let … := …` lines marked above (no `reportPath`;
`ElaipBench.rulesFromState execState`).

---

## 6. Code map & entry points

| file | role |
|---|---|
| `leanagent/codegen/lean_verifier/layer3_v2_codegen.py` | **canonical** unified codegen. `generate_layer3_v2_lean(ir)` + `render_l3_v2_tail(...)`. CLI: `--ir --out`. |
| `leanagent/codegen/lean_verifier/TaskPlanToLean_v2.py` | `generate_layer3_lean_v2(layer3_ir)` → builds a unified IR and calls the core (inline mode). `_LAYER3_IMPORTS`. |
| `leanagent/codegen/agent_evolve/ir_to_lean.py` | transfer-pipeline entry. `layer3_v2` IR → V2 always; legacy `layer3` IR → **legacy by default** (`--v2` to force V2) — see §7. |
| `experiments/elaip_LeanEvolve/elaip_layer3_codegen.py` | thin adapter: normalises the ELAIP IR (`elaip_layer3_ir_init.py`) → unified IR (benchmark=elaip) → core. |

`render_l3_v2_tail` is the single emitter both pipelines share, so SWE and ELAIP
stay in lock-step.

## 7. Back-compat

The core normalises three IR shapes into the unified one, so existing IR-init
scripts keep working unchanged:
- unified `ir_kind: "layer3_v2"` — pass-through;
- legacy SWE `ir_kind: "layer3"` (`leanagent/codegen/agent_evolve/layer3_ir_init.py`) — inline
  mode via the embedded `workflow` + `prefix`;
- ELAIP `ir_kind: "elaip_layer3"` (`…/elaip_layer3_ir_init.py`) — import mode
  (benchmark inferred = elaip).

**This is now the only path.** `ir_to_lean.py` always emits Lean — for both `layer3`
(legacy SWE) and `layer3_v2` IRs — and the V1 generator
(`TaskPlanToLean.generate_layer3_lean` / `_gen_layer3_tail`) plus the V1 dynamic
layer (`AgentVerifier.DynamicVerification.*`) have been removed. The `lean_query`
Layer-3 driver (`leanagent/lean_query/driver_gen._layer3_body` + `discovery.py`)
was migrated to the surface (`layer3ToJson` / `renderFullReport`, by-name
graph from the imported L2 module), so the whole transfer pipeline is unified.
