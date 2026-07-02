import Lean
import Mathlib
import AgentVerifier.DynamicVerification.Basics.DynamicInformationFlow
import AgentVerifier.DynamicVerification.DynamicVerificationGraph

/-!
# Section 5 — Dynamic Unified Report (the 3-channel fold)

The dynamic-layer analogue of Layer-2's `UnifiedVerification.lean`: it runs all
three channels against one runtime graph and bundles them into a single
`DynamicUnifiedVerificationReport`, mirroring `UnifiedVerificationReport`
(`{ hoare, info, coverage }` + `allSound`).

This file has two parts:

  * §5.1 — the **goal-coverage channel**: the per-sub-goal runtime verification
    (variable in final state + contributing/verification nodes executed + the §3
    graph predicates over the trace), ported from the old
    `DynamicGoalCoverageVerification.lean` (injection mode; the IO twin lives in
    §6). This is the dynamic analogue of Layer-2's `analyzeGoalCoverage`. It keeps
    the 3-line soundness discharge (`dynamicGoalCoverageDischargesSubGoalAxiom`) —
    the "living proof" that a second channel needs no heavy re-proof.
  * §5.2 — the **unified fold**: `DynamicUnifiedVerificationReport` packing the
    three channels + coverage, with `hoareSound / infoSound / graphSound /
    coverageSound / allSound`, the `verifyDynamicWorkflow` entry point, and the
    sectioned-banner `formatDynamicUnifiedReport`.

The three verification **methods** (Lean / external-Python / LLM) are exercised
*within* each channel (variable: §1; info: §2; graph: §3); this file only folds
their verdicts. Injection mode here is `native_decide`-friendly; the IO/online
path is §6.
-/

namespace AgenticKernel
namespace Dyn

/-!
## §5.1 — The goal-coverage channel (per-sub-goal runtime verification)
-/

/-- Runtime verification result for a single sub-goal. -/
structure DynamicSubGoalVerification where
  /-- The sub-goal spec from Layer 2. -/
  subGoal : SubGoalSpec
  /-- Verification of `variableName` against `requiredPredicate` in final execution state. -/
  variableVerification : PredicateVerificationEntry
  /-- Which contributing nodes were actually executed? -/
  contributingNodesExecuted : List (NodeId × ExecutionStatus)
  /-- Which verification nodes were actually executed? -/
  verificationNodesExecuted : List (NodeId × ExecutionStatus)
  /-- Optional LLM semantic judgment on whether the sub-goal was achieved. -/
  semanticJudgment : Option LLMJudgementResult := none
  /-- Per-graph-predicate runtime results for this sub-goal (Channel ③). -/
  graphPredicateResults : List DynamicGraphPredicateResult := []
  /-- Set by the §7 per-step reconciliation: the step that produces this sub-goal's
      exit-fact variable had its three-method composite FALSIFIED (Tool and/or LLM
      rejected the evidence even though it is structurally non-empty). Defaults to
      `false`, so an un-reconciled report is unchanged; once reconciled, this makes
      the sub-goal `!passed` so the coverage channel reflects the failed move. -/
  moveFalsified : Bool := false
  deriving Inhabited

namespace DynamicSubGoalVerification

def variablePassed (v : DynamicSubGoalVerification) : Bool := v.variableVerification.passed
def variableFailed (v : DynamicSubGoalVerification) : Bool := v.variableVerification.failed
def variablePending (v : DynamicSubGoalVerification) : Bool := v.variableVerification.isPending

def allContributionsExecuted (v : DynamicSubGoalVerification) : Bool :=
  v.contributingNodesExecuted.all fun (_, status) => status == .completed

def anyContributionExecuted (v : DynamicSubGoalVerification) : Bool :=
  v.contributingNodesExecuted.any fun (_, status) => status == .completed

def allVerificationsExecuted (v : DynamicSubGoalVerification) : Bool :=
  v.verificationNodesExecuted.all fun (_, status) => status == .completed

/-- All *required* graph predicates for this sub-goal passed. -/
def requiredGraphPassed (v : DynamicSubGoalVerification) : Bool :=
  (v.graphPredicateResults.filter (·.required)).all (·.passed)

/-- Overall sub-goal verification passed: variable predicate satisfied in final
    state, at least one contributing node executed, AND (once reconciled) the
    producing step's three-method move was not falsified. -/
def passed (v : DynamicSubGoalVerification) : Bool :=
  v.variablePassed && v.anyContributionExecuted && !v.moveFalsified

def isPending (v : DynamicSubGoalVerification) : Bool := v.variablePending

end DynamicSubGoalVerification

/-- Overall dynamic goal coverage verdict. -/
inductive DynamicGoalCoverageResult where
  | allSubGoalsVerified
  | someSubGoalsFailed (failed : List (String × String))
  | hasPending (pending : List String)
  | noGoalSpec
  deriving Repr, Inhabited

/-- Complete dynamic goal-coverage report (the coverage + graph channels). -/
structure DynamicGoalCoverageReport where
  goalSpec : GoalSpecification
  subGoalVerifications : List DynamicSubGoalVerification
  /-- Static Layer-2 analysis (for comparison/integration). -/
  staticAnalysis : GoalCoverageReport
  overallResult : DynamicGoalCoverageResult
  deriving Inhabited

/-- Look up a node's execution status from the runtime graph. -/
def getNodeExecutionStatus
    (graph : DynamicVerificationGraph)
    (nodeId : NodeId) : ExecutionStatus :=
  match graph.dynamicNodeSpecs.find? (·.id == nodeId) with
  | some spec => spec.executionStatus
  | none =>
    match graph.conditionalNodeSpecs.find? (·.id == nodeId) with
    | some spec => spec.executionStatus
    | none =>
      match graph.loopNodeSpecs.find? (·.id == nodeId) with
      | some spec => spec.executionStatus
      | none => .skipped

/-- Final execution state: the post-execution state of the last completed node,
    or the initial state if none. (Same as §4 `finalExecStateOf`.) -/
def getFinalExecutionState
    (graph : DynamicVerificationGraph) : NodeExecutionState :=
  let completedSpecs := graph.dynamicNodeSpecs.filter (·.executionStatus == .completed)
  match completedSpecs.getLast? with
  | some lastSpec => lastSpec.postExecutionState
  | none => graph.initialExecutionState

/-- Verify a single sub-goal against runtime execution state (injection mode):
    (1) `variableName` satisfies `requiredPredicate` in `finalState`,
    (2) contributing nodes executed, (3) verification nodes executed,
    (4) optional pre-injected LLM semantic judgment. -/
def verifySubGoalDynamic
    (subGoal : SubGoalSpec)
    (finalState : NodeExecutionState)
    (dynGraph : DynamicVerificationGraph)
    (graphAttrs : ExtractedGraphLevelAttributes)
    (externalVerificationResults : List ExternalVerificationResult := [])
    (verificationRegistry : VerificationRegistry := .empty)
    (semanticJudgment : Option LLMJudgementResult := none)
    : DynamicSubGoalVerification :=
  let requirement : VariablePredicateRequirement := ⟨subGoal.variableName, subGoal.requiredPredicate⟩
  let semanticEnv := finalState.stateToSemanticEnv
  let varResult := verifyVariablePredicate requirement semanticEnv externalVerificationResults verificationRegistry
  let varEntry : PredicateVerificationEntry := ⟨requirement, varResult⟩
  let contributingNodeIds := graphAttrs.contributions
    |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
  let contribStatuses := contributingNodeIds.map fun nodeId => (nodeId, getNodeExecutionStatus dynGraph nodeId)
  let verificationNodeIds := graphAttrs.verifications
    |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
  let verifyStatuses := verificationNodeIds.map fun nodeId => (nodeId, getNodeExecutionStatus dynGraph nodeId)
  { subGoal := subGoal
    variableVerification := varEntry
    contributingNodesExecuted := contribStatuses
    verificationNodesExecuted := verifyStatuses
    semanticJudgment := semanticJudgment }

/-- Compute the overall dynamic goal coverage result. -/
def computeDynamicGoalCoverageResult
    (verifications : List DynamicSubGoalVerification) : DynamicGoalCoverageResult :=
  let pending := verifications.filter (·.isPending)
  let failed := verifications.filter fun v => !v.passed && !v.isPending
  if failed.isEmpty && pending.isEmpty then .allSubGoalsVerified
  else if !failed.isEmpty then
    let failReasons := failed.map fun v =>
      let reason := if !v.variablePassed then s!"variable '{v.subGoal.variableName}' did not satisfy predicate"
        else if !v.anyContributionExecuted then "no contributing node was executed"
        else if v.moveFalsified then s!"per-step move falsified — Tool/LLM rejected the evidence for '{v.subGoal.variableName}'"
        else "unknown failure"
      (v.subGoal.name.val, reason)
    .someSubGoalsFailed failReasons
  else .hasPending (pending.map (·.subGoal.name.val))

/-- Build the dynamic goal-coverage report with the §3 graph predicates run over
    the trace (injection mode). The static Layer-2 report is computed internally by
    default (for the static-vs-dynamic comparison line in the report). -/
def buildDynamicGoalCoverageReport
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerificationResults : List ExternalVerificationResult := [])
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (staticReport : GoalCoverageReport :=
      analyzeGoalCoverage dynGraph.semanticWorkflowGraph goalSpec)
    : DynamicGoalCoverageReport :=
  let finalState := getFinalExecutionState dynGraph
  let graphAttrs := extractGraphLevelAttributes dynGraph.semanticWorkflowGraph
  let subGoalVerifications := goalSpec.subGoals.map fun subGoal =>
    let judgment := semanticJudgments.find? (fun (name, _) => name == subGoal.name.val) |>.map (·.2)
    let baseV := verifySubGoalDynamic subGoal finalState dynGraph graphAttrs
      externalVerificationResults unifiedReg.varRegistry judgment
    let contribNodes := graphAttrs.contributions |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
    let verifNodes := graphAttrs.verifications |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
    let ctx := buildGraphCheckContext dynGraph trace subGoal.name contribNodes verifNodes [] PredicateRegistry.empty stepIdMap
    let graphRes := runGraphPredicatesForSubGoal unifiedReg ctx subGoal.requiredGraphPredicates graphInjected
    { baseV with graphPredicateResults := graphRes }
  let overallResult := computeDynamicGoalCoverageResult subGoalVerifications
  { goalSpec := goalSpec
    subGoalVerifications := subGoalVerifications
    staticAnalysis := staticReport
    overallResult := overallResult }

/-!
### §5.1.1 — Soundness: dynamic coverage discharges the sub-goal assumption

The "living proof" (3-line delegation to the §4 variable lemma) that a second
channel needs no heavy re-proof.
-/

/-- If a sub-goal's variable predicate is verified at runtime, its required
    proposition holds in the final semantic environment. -/
theorem dynamicGoalCoverageDischargesSubGoalAxiom
    (subGoal : SubGoalSpec)
    (postExecSemanticEnv : SemanticEnv)
    (hVerified : (verifyVariablePredicate
      ⟨subGoal.variableName, subGoal.requiredPredicate⟩ postExecSemanticEnv).passed = true) :
    subGoal.requiredPredicate.toProp postExecSemanticEnv subGoal.variableName :=
  verifyVariablePredicatePassedImpliesToProp
    ⟨subGoal.variableName, subGoal.requiredPredicate⟩ postExecSemanticEnv hVerified

/-!
### §5.1.2 — Coverage formatting
-/

def DynamicSubGoalVerification.describe (v : DynamicSubGoalVerification) : String :=
  let varStatus := v.variableVerification.describe
  let contribStr := v.contributingNodesExecuted.map fun (nodeId, status) => s!"    Node {nodeId.val}: {repr status}"
  let verifyStr := v.verificationNodesExecuted.map fun (nodeId, status) => s!"    Node {nodeId.val}: {repr status}"
  let judgmentStr := match v.semanticJudgment with
    | some j => let verdict := if j.holds then "✓ PASS" else "✗ FAIL"
               s!"\n  LLM Semantic Judgment: {verdict} (conf={j.confidence})\n    {j.llmExplanation}"
    | none => ""
  let overallStatus := if v.passed then "✓ VERIFIED" else if v.isPending then "⏳ PENDING" else "✗ FAILED"
  s!"Sub-Goal: {v.subGoal.name.val} [{overallStatus}]\n  Variable ({v.subGoal.variableName}):\n{varStatus}\n  Contributing Nodes:\n{String.intercalate "\n" contribStr}\n  Verification Nodes:\n{String.intercalate "\n" verifyStr}{judgmentStr}"

def DynamicGoalCoverageResult.describe : DynamicGoalCoverageResult → String
  | .allSubGoalsVerified => "✓ ALL SUB-GOALS VERIFIED AT RUNTIME"
  | .someSubGoalsFailed failed =>
    let details := failed.map fun (name, reason) => s!"  - {name}: {reason}"
    s!"✗ SOME SUB-GOALS FAILED:\n{String.intercalate "\n" details}"
  | .hasPending pending => s!"⏳ PENDING: {String.intercalate ", " pending}"
  | .noGoalSpec => "— No goal specification provided"

/-!
## §5.2 — The unified report (the 3-channel fold)
-/

/-- Flatten all per-node specs (basic + conditional + loop) for the info channel's
    executed-set computation. -/
def DynamicVerificationGraph.allNodeSpecs (g : DynamicVerificationGraph) : List DynamicNodeSpec :=
  g.dynamicNodeSpecs
    ++ g.conditionalNodeSpecs.map (·.toDynamicNodeSpec)
    ++ g.loopNodeSpecs.map (·.toDynamicNodeSpec)

/-- The dynamic unified verification report — three channels at once over one
    runtime graph, mirroring Layer-2's `UnifiedVerificationReport`. The graph
    channel's per-sub-goal results live inside `coverage`. -/
structure DynamicUnifiedVerificationReport where
  label : String := ""
  /-- Channel ① — the variable/Hoare node-level result. -/
  variable_ : DynamicVerificationGraphVerifyResult
  /-- Channel ② — the dynamic information-flow result. -/
  info : DynamicInformationFlowResult
  /-- Channel ③ + goal coverage — per-sub-goal graph predicates and coverage. -/
  coverage : DynamicGoalCoverageReport
  /-- The per-node specs, retained for per-node rendering. -/
  nodeSpecs : List DynamicNodeSpec
  deriving Inhabited

namespace DynamicUnifiedVerificationReport

/-- Channel ① clean: every node's pre/post verified. -/
def hoareSound (r : DynamicUnifiedVerificationReport) : Bool :=
  match r.variable_ with | .allVerified => true | _ => false

/-- Channel ② clean: no node runs information-starved. -/
def infoSound (r : DynamicUnifiedVerificationReport) : Bool := r.info.passed

/-- Channel ③ clean: every required graph predicate passed across sub-goals. -/
def graphSound (r : DynamicUnifiedVerificationReport) : Bool :=
  r.coverage.subGoalVerifications.all (·.requiredGraphPassed)

/-- Goal coverage clean: every sub-goal verified at runtime. -/
def coverageSound (r : DynamicUnifiedVerificationReport) : Bool :=
  match r.coverage.overallResult with | .allSubGoalsVerified => true | _ => false

/-- A run is fully verified iff all three channels AND coverage are clean. -/
def allSound (r : DynamicUnifiedVerificationReport) : Bool :=
  r.hoareSound && r.infoSound && r.graphSound && r.coverageSound

/-- Are any channel verdicts still pending (unresolved injection)? -/
def hasPending (r : DynamicUnifiedVerificationReport) : Bool :=
  (match r.variable_ with | .hasPending _ => true | _ => false)
  || r.coverage.subGoalVerifications.any (·.isPending)

end DynamicUnifiedVerificationReport

/-- THE DYNAMIC UNIFIED ENTRY POINT. Run all three channels (variable §1, info §2,
    graph+coverage §3/§5.1) against one runtime graph + trace, and bundle them.
    Injection mode (verdicts pre-injected; `native_decide`-friendly). -/
def verifyDynamicWorkflow
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerificationResults : List ExternalVerificationResult := [])
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (infoInjections : List DynamicInfoFlowInjection := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (label : String := "") : DynamicUnifiedVerificationReport :=
  let variable_ := dynGraph.verify
  let info := verifyDynamicInformationFlowFromSpecs dynGraph.semanticWorkflowGraph dynGraph.allNodeSpecs infoInjections
  let coverage := buildDynamicGoalCoverageReport dynGraph trace goalSpec unifiedReg
    externalVerificationResults graphInjected semanticJudgments stepIdMap
  { label := label
    variable_ := variable_
    info := info
    coverage := coverage
    nodeSpecs := dynGraph.dynamicNodeSpecs }

/-- Boolean entry point, for `native_decide` soundness theorems. -/
def isDynamicWorkflowFullyVerifiedBool
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace) : Bool :=
  (verifyDynamicWorkflow dynGraph trace).allSound

/-!
### §5.2.1 — Pretty printing: the sectioned banner (mirrors Layer-2 `formatUnifiedReport`)
-/

private def checkMark (b : Bool) : String := if b then "✓" else "✗"

private def bannerHeader (r : DynamicUnifiedVerificationReport) : String :=
  let title := if r.label.isEmpty then "LAYER-3 REPORT" else s!"LAYER-3 REPORT · {r.label}"
  let varLine := match r.variable_ with
    | .allVerified => " Variables  ✓ SOUND     (all nodes pre/post verified)"
    | .someNodesFailed fs => s!" Variables  ✗ UNSOUND   ({fs.length} node(s) failed)"
    | .hasPending ps => s!" Variables  ⏳ PENDING   ({ps.length} node(s) pending)"
    | .structuralMismatch reason => s!" Variables  ✗ UNSOUND   ({reason})"
  let blocked := r.info.failingNodes.length
  let starved := r.info.starvedNodes.length
  let infoLine :=
    if r.info.passed then " Info flow  ✓ SOUND     (0 nodes starved)"
    else s!" Info flow  ✗ UNSOUND   ({blocked} node(s) blocked, {starved} starved)"
  let total := r.coverage.goalSpec.subGoals.length
  let verified := r.coverage.subGoalVerifications.filter (·.passed) |>.length
  let covMark := checkMark r.coverageSound
  let covLine := s!" Coverage   {covMark} {verified}/{total} sub-goals verified"
  let graphMark := checkMark r.graphSound
  let graphLine := s!" Graph      {graphMark} {if r.graphSound then "all required graph predicates passed" else "some required graph predicate failed"}"
  -- Per-step moves (the three-method composite, folded in by the §7 reconciliation).
  let movesFalsified := r.coverage.subGoalVerifications.filter (·.moveFalsified) |>.length
  let movesLine :=
    if movesFalsified == 0 then " Moves      ✓ all step moves confirmed (Lean ∧ Tool ∧ LLM)"
    else s!" Moves      ✗ {movesFalsified} step move(s) FALSIFIED by Tool/LLM (evidence is hollow)"
  let bar := "══════════════════════════════════════════════════════════════"
  s!"{bar}\n {title}\n{bar}\n{varLine}\n{infoLine}\n{graphLine}\n{covLine}\n{movesLine}"

/-- Per-sub-goal coverage line: level mark + the per-predicate flags. -/
private def subGoalCoverageLine (v : DynamicSubGoalVerification) : String :=
  let flag (res : DynamicGraphPredicateResult) : String :=
    if res.informational then (if res.passed then s!"~{res.shortLabel}" else s!"!{res.shortLabel}")
    else if res.required then (if res.passed then s!"+{res.shortLabel}" else s!"-{res.shortLabel}")
    else (if res.passed then s!"~{res.shortLabel}" else s!".{res.shortLabel}")
  let predFlags := v.graphPredicateResults.map flag
  let varFlag := if v.variablePassed then "+var" else "-var"
  let moveFlag := if v.moveFalsified then ["!move"] else []
  let flags := String.intercalate " " (predFlags ++ [varFlag] ++ moveFlag)
  let mark := if v.passed then "✓" else if v.isPending then "⏳" else "✗"
  s!"  {mark} {v.subGoal.name.val}   [{flags}]"

private def subGoalSection (r : DynamicUnifiedVerificationReport) : String :=
  if r.coverage.subGoalVerifications.isEmpty then "  (no sub-goals specified)"
  else String.intercalate "\n" (r.coverage.subGoalVerifications.map subGoalCoverageLine)

/-- Issues: required variable / move / graph failures + info-starved nodes, merged. -/
private def issuesSection (r : DynamicUnifiedVerificationReport) : String :=
  let covIssues := r.coverage.subGoalVerifications.filterMap fun v =>
    if v.passed || v.isPending then none
    else if !v.variablePassed then some s!"  - coverage: sub-goal '{v.subGoal.name.val}' variable '{v.subGoal.variableName}' empty/absent"
    else if v.moveFalsified then some s!"  - moves: sub-goal '{v.subGoal.name.val}' step move FALSIFIED — Tool/LLM rejected the evidence for '{v.subGoal.variableName}'"
    else if !v.anyContributionExecuted then some s!"  - coverage: sub-goal '{v.subGoal.name.val}' had no contributing node execute"
    else none
  let graphIssues := r.coverage.subGoalVerifications.flatMap fun v =>
    v.graphPredicateResults.filterMap fun res =>
      if res.required && !res.passed then some s!"  - graph: '{v.subGoal.name.val}' / {res.shortLabel} failed ({res.detail})" else none
  let infoIssues := r.info.failingNodes.map fun nr =>
    s!"  - info: node {nr.nodeId.val} cannot see {formatDynInfoList nr.missing}"
  let all := covIssues ++ graphIssues ++ infoIssues
  if all.isEmpty then "  None" else String.intercalate "\n" all

/-- Per-node summary: variable state · information flow (3 subfields). -/
private def formatNodeDetail (r : DynamicUnifiedVerificationReport) (spec : DynamicNodeSpec) : String :=
  let name := spec.name.getD s!"node_{spec.id.val}"
  let statusStr := match getNodeVerifyStatus spec with
    | .verified => "✓ verified" | .skipped => "- skipped"
    | .precondFailed _ => "✗ precond failed" | .postcondFailed _ => "✗ postcond failed"
    | .pending _ => "⏳ pending"
  let hdr := s!"  ── node {spec.id.val} \"{name}\" [{repr spec.executionStatus}] {statusStr} ──"
  let infoNode := r.info.nodeResults.find? (·.nodeId == spec.id)
  -- atoms this node WRITES (producesContextInfo / producesVariableInfo) — shown alongside requires/starved so the summary is not misread as consumers-only
  let writesCtx := if spec.semanticNode.producesContextInfo.isEmpty then "(none)" else formatDynInfoList spec.semanticNode.producesContextInfo
  let writesVar := if spec.semanticNode.producesVariableInfo.isEmpty then "" else "\n        writes (variable): " ++ String.intercalate ", " (spec.semanticNode.producesVariableInfo.map (fun vi => s!"{vi.varName}→{formatDynInfoList vi.carries}"))
  let writesLine := s!"        writes (context): {writesCtx}{writesVar}"
  let reqPart := match infoNode with
    | none => "        (no information required)"
    | some ir =>
      if ir.required.isEmpty then "        (no information required)"
      else s!"        requires: {formatDynInfoList ir.required}\n        starved:  {formatDynInfoList ir.starved}  absent: {formatDynInfoList ir.absent}"
  let infoStr := s!"      [information flow]\n{reqPart}\n{writesLine}"
  s!"{hdr}\n{infoStr}"

private def perNodeSection (r : DynamicUnifiedVerificationReport) : String :=
  if r.nodeSpecs.isEmpty then "  (no nodes)"
  else String.intercalate "\n" (r.nodeSpecs.map (formatNodeDetail r))

/-- Render the full sectioned-banner report. -/
def formatDynamicUnifiedReport (r : DynamicUnifiedVerificationReport) : String :=
  let bar := "──────────────────────────────────────────────────────────────"
  s!"{bannerHeader r}\n{bar}\n SUB-GOAL COVERAGE  (legend: +req·pass  -req·FAIL  ~opt/info·pass  !info·FAIL  ±var)\n{subGoalSection r}\n{bar}\n ISSUES\n{issuesSection r}\n{bar}\n PER-NODE SUMMARY  (variable state · information flow)\n{perNodeSection r}\n══════════════════════════════════════════════════════════════"

/-- Convenience: verify and format in one call. -/
def verifyDynamicWorkflowReport
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerificationResults : List ExternalVerificationResult := [])
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (infoInjections : List DynamicInfoFlowInjection := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (label : String := "") : String :=
  formatDynamicUnifiedReport (verifyDynamicWorkflow dynGraph trace goalSpec unifiedReg
    externalVerificationResults graphInjected semanticJudgments infoInjections stepIdMap label)

end Dyn
end AgenticKernel
