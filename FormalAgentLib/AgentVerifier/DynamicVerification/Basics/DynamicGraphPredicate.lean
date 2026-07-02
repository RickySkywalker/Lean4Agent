import Lean
import Mathlib
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates
import AgentVerifier.DynamicVerification.Basics.ExecutionTrace
import AgentVerifier.DynamicVerification.Basics.DynamicVariablePredicate

/-!
# Section 3 — Dynamic Graph-Level Predicates (Channel ③)

The runtime counterparts of Layer-2's graph-level checks
(`GraphLevelPredicates.lean`) and the bridge to that system
(`GraphCheckContext` / `GraphLevelPredicateKeys` / the static `…Check`
instances). This is the §3 of the dynamic layer (Basics, Channel ③).

Ported from the original
`AgentVerifier/DynamicVerification/DynamicGraphLevelVerification.lean`, **with all
seven legacy dependencies (`[L1]`–`[L6]` of that file, `[L7]` in §6) removed**:

  * `DynamicContextContinuityCheck` ([L1]) and `DynamicInformationSufficiencyCheck`
    ([L2]) — the two information-ish graph predicates that reused the DEPRECATED
    `GraphLevelPredicate_legacy.lean` — are **gone**. Information is now a
    first-class channel (§2 `DynamicInformationFlow`), so the graph channel no
    longer carries information predicates at all.
  * `requiredAspectsOf` ([L3]) / `substringAspectFallback` ([L4]) — the
    `coversAspect`/`extractAspectFromKey` aspect model that existed only to service
    [L1]/[L2] — are **gone**.
  * `isLLMPortKey` ([L5] two-tier branch) — **gone**; there is no special LLM-port
    path. Every predicate uses one uniform 3-method dispatch with a Lean floor.

This file carries **no dependency on the deprecated
`GraphLevelPredicate_legacy.lean`** and emits no `LEGACY-DEP` warnings.

## Container-free by design

The check context (`DynamicGraphCheckContext`) carries only what the checks
actually read (graph + trace + executed-node sets + final state); the old
`dynGraph : DynamicVerificationGraph` field was unused by every `checkLean`, so
it is dropped. This keeps the graph-predicate channel free of the runtime-graph
container — the container, the context *builder*, and the per-sub-goal
orchestration live in §4 (`DynamicVerificationGraph`), which imports this file.

## Three methods (orthogonal to the channel)

`verifyGraphPredicate` dispatches each predicate on its `defaultMethod`:
  1. `leanSymbolic`  → run `checkLean` (decidable structural check).
  2. `externalTool t`→ use the injected tool verdict, else fall back to `checkLean`.
  3. `llmJudge`      → use the injected LLM verdict, else fall back to `checkLean`.
The Lean structural check is always the floor; tool/LLM verdicts are injected
(injection mode) or resolved over IO (§6, online mode).
-/

namespace AgenticKernel
namespace Dyn

/-!
## §3.1 — Runtime check context

Extends Layer-2's `GraphCheckContext` with the trace-derived fields the runtime
checks need. No runtime-graph container (see file header).
-/

/-- Runtime context for a single graph-level predicate check. Extends the static
    `GraphCheckContext` with trace-derived fields. -/
structure DynamicGraphCheckContext extends GraphCheckContext where
  trace                     : ExecutionTrace
  stepIdMap                 : StepIdMap
  executedContributingNodes : List NodeId
  executedVerificationNodes : List NodeId
  finalExecState            : NodeExecutionState

/-!
## §3.2 — Graph-predicate external / LLM injection results

Parallel to §1's `ExternalVerificationResult` but keyed by
`(predicateKey, subGoalName)` since graph-level predicates are not attached to a
single variable.
-/

structure GraphExternalVerificationResult where
  predicateKey       : PredicateKey
  subGoalName        : SubGoalName
  externalToolResult : Option ExternalToolJudgementResult := none
  llmJudgementResult : Option LLMJudgementResult := none
  deriving Repr, Inhabited

def findGraphExternalResult
    (results : List GraphExternalVerificationResult)
    (key : PredicateKey)
    (subGoalName : SubGoalName) : Option GraphExternalVerificationResult :=
  results.find? fun r => r.predicateKey == key && r.subGoalName == subGoalName

/-!
## §3.3 — Type class

Runtime counterpart of Layer-2's `GraphLevelPredicate`. Each instance carries a
`PredicateKey`, a `defaultMethod`, a structural `checkLean`, and describe metadata.
-/

class DynamicGraphLevelPredicate (α : Type) where
  toKey           : α → PredicateKey
  defaultMethod   : α → VerificationMethod
  checkLean       : α → DynamicGraphCheckContext → Bool
  describe        : α → String
  shortLabel      : α → String
  isInformational : α → Bool := fun _ => false

/-!
## §3.4 — Result + report types
-/

/-- Verification outcome for a single graph-level predicate in a single sub-goal context. -/
structure DynamicGraphPredicateResult where
  predicateKey       : PredicateKey
  shortLabel         : String
  method             : VerificationMethod
  passed             : Bool
  required           : Bool := false
  informational      : Bool := false
  detail             : String := ""
  externalToolResult : Option ExternalToolJudgementResult := none
  llmJudgement       : Option LLMJudgementResult := none
  deriving Repr, Inhabited

/-- Combined report. Folded into the unified report (§5). -/
structure DynamicGraphLevelVerificationReport where
  perSubGoal  : List (String × List DynamicGraphPredicateResult) := []
  deriving Repr, Inhabited

/-!
## §3.5 — `StepIdMap.fromGraph` (static-graph bridge)

The agent writes `step_id : String` in the trace (`"1"`, `"2"`); the static
verifier carries numeric `NodeId`s. This map bridges them using
`toString nodeId.val`, which matches what the agent emits for YAML workflows
whose step ids are numeric indices.
-/

namespace StepIdMap

def fromGraph (graph : SemanticWorkflowGraph) : StepIdMap :=
  let pairs : List (String × NodeId) :=
    graph.semanticNodes.map fun n => (toString n.id.val, n.id)
  ofList pairs

end StepIdMap

/-!
## §3.6 — Runtime instances for the structural graph predicates

The five execution-aware structural predicates. The two old information-ish
predicates are removed — information is the §2 channel now.
-/

namespace DynamicGraphLevelPredicates

/-! ### 3.6a — Path coverage -/

structure DynamicPathCoverageCheck where deriving Repr, BEq, Inhabited

instance : DynamicGraphLevelPredicate DynamicPathCoverageCheck where
  toKey _ := GraphLevelPredicateKeys.pathCoverage
  defaultMethod _ := .externalToolVerification "graph_path_coverage_checker"
  describe _ := "Sub-goal is established on the actually-executed path to every exit"
  shortLabel _ := "path"
  checkLean _ ctx :=
    ctx.graph.exits.all fun exit =>
      ctx.executedContributingNodes.any fun n =>
        n == exit || ctx.graph.reachable n exit

/-! ### 3.6b — Verification coverage -/

structure DynamicVerificationCoverageCheck where deriving Repr, BEq, Inhabited

instance : DynamicGraphLevelPredicate DynamicVerificationCoverageCheck where
  toKey _ := GraphLevelPredicateKeys.verificationCoverage
  defaultMethod _ := .externalToolVerification "graph_verification_coverage_checker"
  describe _ := "An executed verification step exists after an executed contributing step"
  shortLabel _ := "verify"
  checkLean _ ctx :=
    ctx.executedVerificationNodes.any fun verifyId =>
      ctx.executedContributingNodes.any fun contribId =>
        contribId != verifyId &&
        (match ctx.stepIdMap.toStepId contribId, ctx.stepIdMap.toStepId verifyId with
         | some csid, some vsid =>
           match ctx.trace.stepLastIndex csid, ctx.trace.stepFirstIndex vsid with
           | some cLast, some vFirst => vFirst > cLast
           | _, _ => ctx.graph.reachable contribId verifyId
         | _, _ => ctx.graph.reachable contribId verifyId)

/-! ### 3.6c — Unified loop-back -/

structure DynamicUnifiedLoopBackCheck where deriving Repr, BEq, Inhabited

/-- Runtime evidence for retry: either the static check passes (loop present,
    implicit-retry annotation, or structured retry info), or an actual retry
    happened at runtime (iteration > 1 for a contributing node). -/
instance : DynamicGraphLevelPredicate DynamicUnifiedLoopBackCheck where
  toKey _ := GraphLevelPredicateKeys.unifiedLoopBack
  defaultMethod _ := .externalToolVerification "graph_unified_loop_back_checker"
  describe _ := "Retry capability: explicit loop, implicit task-chain retry, or runtime iteration evidence"
  shortLabel _ := "loop_back"
  checkLean _ ctx :=
    -- Runtime evidence: any executed contributing node with iteration ≥ 2
    let hasRuntimeRetry := ctx.executedContributingNodes.any fun nodeId =>
      match ctx.stepIdMap.toStepId nodeId with
      | some sid => ctx.trace.maxIteration sid ≥ 2
      | none => false
    -- Static evidence: fall back to the static (Layer-2) check
    let staticCheck := GraphLevelPredicate.check UnifiedLoopBackCheck.mk ctx.toGraphCheckContext
    hasRuntimeRetry || staticCheck

/-! ### 3.6d — Fail-safe (informational) -/

structure DynamicFailSafeCheck where deriving Repr, BEq, Inhabited

/-- Annotation-driven: a node reachable from the loop exit (per the static graph)
    executed **and** is annotated as contributing to the sub-goal. -/
instance : DynamicGraphLevelPredicate DynamicFailSafeCheck where
  toKey _ := GraphLevelPredicateKeys.failSafe
  defaultMethod _ := .externalToolVerification "graph_fail_safe_checker"
  describe _ := "After retry exhaustion, a fallback writer for the sub-goal executed"
  shortLabel _ := "failsafe"
  isInformational _ := true
  checkLean _ ctx :=
    ctx.executedContributingNodes.any fun nodeId =>
      if isNodeInsideLoop ctx.graph nodeId then
        match findLoopExitForNode ctx.graph nodeId with
        | none => false
        | some loopExitId =>
          ctx.graph.exits.any fun graphExit =>
            ctx.graph.semanticNodes.any fun fallbackNode =>
              fallbackNode.id != nodeId &&
              -- executed?
              (match ctx.stepIdMap.toStepId fallbackNode.id with
               | some sid => ctx.trace.stepCompleted sid
               | none => false) &&
              (fallbackNode.id == loopExitId || ctx.graph.reachable loopExitId fallbackNode.id) &&
              (fallbackNode.id == graphExit || ctx.graph.reachable fallbackNode.id graphExit) &&
              fallbackNode.postcondVariables.any fun req =>
                extractContributionFromPredicate req.requiredPredicate == some ctx.subGoalName
      else false

/-! ### 3.6e — Exit facts confirmed -/

structure DynamicExitFactsConfirmedCheck where
  variableName : String
  requiredPredicate : PredicateType
  deriving Repr, BEq, Inhabited

instance : DynamicGraphLevelPredicate DynamicExitFactsConfirmedCheck where
  toKey _ := GraphLevelPredicateKeys.exitFactsConfirmed
  defaultMethod _ := .leanSymbolicVerification
  describe _ := "Sub-goal predicate holds in the final execution state"
  shortLabel _ := "exit_facts"
  checkLean p ctx :=
    let env := ctx.finalExecState.stateToSemanticEnv
    p.requiredPredicate.checkBool env p.variableName

end DynamicGraphLevelPredicates

/-!
## §3.7 — Entry points (3-method dispatch, uniform Lean floor)
-/

/-- An erased registry entry — carries enough to verify a single graph predicate
    against a `DynamicGraphCheckContext`. -/
structure DynamicGraphLevelPredicateEntry where
  predicateKey   : PredicateKey
  defaultMethod  : VerificationMethod
  shortLabel     : String
  describe       : String
  informational  : Bool := false
  checkLean      : DynamicGraphCheckContext → Bool
  deriving Inhabited

def DynamicGraphLevelPredicateEntry.ofInstance [inst : DynamicGraphLevelPredicate α]
    (pred : α) : DynamicGraphLevelPredicateEntry :=
  { predicateKey  := DynamicGraphLevelPredicate.toKey pred
    defaultMethod := DynamicGraphLevelPredicate.defaultMethod pred
    shortLabel    := DynamicGraphLevelPredicate.shortLabel pred
    describe      := DynamicGraphLevelPredicate.describe pred
    informational := DynamicGraphLevelPredicate.isInformational pred
    checkLean     := DynamicGraphLevelPredicate.checkLean pred }

/-- Core injection-mode verification for a single graph-level predicate. Dispatch
    on `defaultMethod`, with the Lean structural check (`checkLean`) as the floor:
      * `leanSymbolic`  : use the Lean check.
      * `externalTool t`: use the injected tool verdict, else fall back to Lean.
      * `llmJudge`      : use the injected LLM verdict, else fall back to Lean.
    No special LLM-port / substring path (the de-legacied design). -/
def verifyGraphPredicate
    (entry : DynamicGraphLevelPredicateEntry)
    (subGoalName : SubGoalName)
    (required : Bool)
    (ctx : DynamicGraphCheckContext)
    (injected : List GraphExternalVerificationResult := []) : DynamicGraphPredicateResult :=
  let mkBase (method : VerificationMethod) (passed : Bool) (detail : String)
             (ext : Option ExternalToolJudgementResult := none)
             (llm : Option LLMJudgementResult := none) : DynamicGraphPredicateResult :=
    { predicateKey := entry.predicateKey
      shortLabel   := entry.shortLabel
      method       := method
      passed       := passed
      required     := required
      informational := entry.informational
      detail       := detail
      externalToolResult := ext
      llmJudgement := llm }
  -- The Lean structural check is always available as the floor.
  let leanPassed := entry.checkLean ctx
  match entry.defaultMethod with
  | .leanSymbolicVerification =>
    mkBase .leanSymbolicVerification leanPassed
      (if leanPassed then "lean symbolic check passed" else "lean symbolic check failed")
  | .externalToolVerification toolName =>
    match (findGraphExternalResult injected entry.predicateKey subGoalName).bind (·.externalToolResult) with
    | some tr =>
      mkBase (.externalToolVerification toolName) tr.passed tr.additionalInfo (some tr) none
    | none =>
      mkBase (.externalToolVerification toolName) leanPassed
        (if leanPassed then s!"tool {toolName} not injected; lean fallback passed"
         else s!"tool {toolName} not injected; lean fallback failed")
  | .llmJudgeVerification =>
    match (findGraphExternalResult injected entry.predicateKey subGoalName).bind (·.llmJudgementResult) with
    | some j =>
      mkBase .llmJudgeVerification j.holds s!"LLM judge: {j.llmExplanation}" none (some j)
    | none =>
      mkBase .llmJudgeVerification leanPassed
        (if leanPassed then "llm judge not injected; lean fallback passed"
         else "llm judge not injected; lean fallback failed")

/-!
## §3.8 — Registry and defaults
-/

structure UnifiedDynamicPredicateRegistry where
  varRegistry        : VerificationRegistry := .empty
  graphEntries       : List DynamicGraphLevelPredicateEntry := []
  deriving Inhabited

namespace UnifiedDynamicPredicateRegistry

def empty : UnifiedDynamicPredicateRegistry := {}

def registerGraph (reg : UnifiedDynamicPredicateRegistry)
    (entry : DynamicGraphLevelPredicateEntry) : UnifiedDynamicPredicateRegistry :=
  { reg with graphEntries := reg.graphEntries ++ [entry] }

def registerGraphInstance [inst : DynamicGraphLevelPredicate α]
    (reg : UnifiedDynamicPredicateRegistry) (pred : α) : UnifiedDynamicPredicateRegistry :=
  reg.registerGraph (DynamicGraphLevelPredicateEntry.ofInstance pred)

def withVarRegistry (reg : UnifiedDynamicPredicateRegistry)
    (varReg : VerificationRegistry) : UnifiedDynamicPredicateRegistry :=
  { reg with varRegistry := varReg }

end UnifiedDynamicPredicateRegistry

open DynamicGraphLevelPredicates in
/-- Pre-loaded with the four structural graph predicates. Unlike the old Layer-3
    registry, this does **not** register any information predicates — information
    is the §2 channel now (which is why the deprecated
    `DynamicContextContinuityCheck` / `DynamicInformationSufficiencyCheck` are
    gone, clearing legacy sites L1/L2/L6).

    `DynamicExitFactsConfirmedCheck` is **not** auto-registered because it requires
    a per-sub-goal `(variableName, requiredPredicate)` parameterization; its intent
    is already covered by the variable channel's exit-fact verification. Users who
    want an explicit graph-predicate slot for it can register it per sub-goal. -/
def defaultUnifiedDynamicRegistry : UnifiedDynamicPredicateRegistry :=
  UnifiedDynamicPredicateRegistry.empty
    |>.registerGraphInstance DynamicPathCoverageCheck.mk
    |>.registerGraphInstance DynamicVerificationCoverageCheck.mk
    |>.registerGraphInstance DynamicUnifiedLoopBackCheck.mk
    |>.registerGraphInstance DynamicFailSafeCheck.mk

/-!
## §3.9 — Trace-derived helpers (container-free)
-/

/-- Subset of node ids that actually completed per the trace. -/
def executedCompletedNodes (trace : ExecutionTrace) (stepIdMap : StepIdMap)
    (graph : SemanticWorkflowGraph) : List NodeId :=
  graph.semanticNodes.filterMap fun n =>
    match stepIdMap.toStepId n.id with
    | some sid => if trace.stepCompleted sid then some n.id else none
    | none     => none

/-- Run every graph-level entry in the registry for a given sub-goal. -/
def runGraphPredicatesForSubGoal
    (reg : UnifiedDynamicPredicateRegistry)
    (ctx : DynamicGraphCheckContext)
    (requiredKeys : List PredicateKey := [])
    (injected : List GraphExternalVerificationResult := [])
    : List DynamicGraphPredicateResult :=
  reg.graphEntries.map fun entry =>
    let required := requiredKeys.any (· == entry.predicateKey) && !entry.informational
    verifyGraphPredicate entry ctx.subGoalName required ctx injected

/-!
## §3.10 — Describe / formatting
-/

def formatGraphPredicateResult (r : DynamicGraphPredicateResult) : String :=
  if r.informational then
    if r.passed then s!"[~{r.shortLabel}]" else s!"[!{r.shortLabel}]"
  else if r.required then
    if r.passed then s!"[+{r.shortLabel}]" else s!"[-{r.shortLabel}]"
  else
    if r.passed then s!"[~{r.shortLabel}]" else s!"[.{r.shortLabel}]"

def DynamicGraphPredicateResult.describe (r : DynamicGraphPredicateResult) : String :=
  let methodTag := match r.method with
    | .leanSymbolicVerification => "lean"
    | .externalToolVerification t => s!"py:{t}"
    | .llmJudgeVerification => "llm"
  s!"  {formatGraphPredicateResult r} [{methodTag}] {r.detail}"

def DynamicGraphLevelVerificationReport.describe
    (report : DynamicGraphLevelVerificationReport) : String :=
  let perSub := report.perSubGoal.map fun (subName, results) =>
    let satisfied := results.filter (·.passed) |>.map formatGraphPredicateResult
    let failed := results.filter
      (fun r => !r.passed && (r.required || r.informational)) |>.map formatGraphPredicateResult
    let detailLines := results.map (DynamicGraphPredicateResult.describe ·)
    s!"  Sub-Goal {subName}:\n    Satisfied: {if satisfied.isEmpty then "(none)" else String.intercalate " " satisfied}\n    Failed:    {if failed.isEmpty then "(none)" else String.intercalate " " failed}\n{String.intercalate "\n" detailLines}"
  s!"═══════════════════════════════════════════════════════════
  LAYER 3: DYNAMIC GRAPH-LEVEL REPORT
═══════════════════════════════════════════════════════════
Graph Predicates (per sub-goal):
{String.intercalate "\n" perSub}
═══════════════════════════════════════════════════════════"

end Dyn
end AgenticKernel
