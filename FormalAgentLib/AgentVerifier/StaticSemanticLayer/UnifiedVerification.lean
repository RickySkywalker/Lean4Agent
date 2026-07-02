import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.SemanticGraph
import AgentVerifier.StaticSemanticLayer.SemanticVerification
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.InformationSystem

namespace AgenticKernel

/-!
# Unified Layer-2 Verification (Solution 2 — summarization & integration layer)

This module is the **integration layer** the redesign pulls OUT of the
`WorkflowQualityAnalysis` folder (Solution 2 §2.1): the WQA submodules keep only
the predicate/information *definitions and primitives*; the *summarization* — run
all three judgments and render one report — lives here.

A workflow is now judged on **three channels at once**, all read off the
restructured `SemanticWorkflowGraph` (no separate overlays):

  1. **Variables** — the Hoare pre/post chain (`SemanticWorkflowGraph.verify`),
     over each node's `precondVariables` / `postcondVariables`.
  2. **Information flow** — `verifyInformationFlow` over the per-node information
     fields, surfaced as an overlay by `InformationFlowSpec.fromGraph`.
  3. **Goal coverage** — `analyzeGoalCoverage` over the per-node graph-predicate
     fields and the graph's embedded `goalSpec` (the workflow's requirements,
     provided at construction).

`SemanticWorkflowGraph.verifyWorkflow` returns all three in one
`UnifiedVerificationReport`; `formatUnifiedReport` renders the sectioned-banner
layout: an overall verdict banner first, then per-node detail, then per-sub-goal
coverage.
-/

/-! ## Part 1: the unified report -/

structure UnifiedVerificationReport where
  /-- A human label for the workflow (e.g. the plan name). -/
  label : String := ""
  /-- Variable channel — the Hoare chain result. -/
  hoare : GraphVerifyResult
  /-- Information channel — per-node information-flow result. -/
  info : InformationFlowResult
  /-- Goal-coverage channel — graph-level structural coverage + exit facts. -/
  coverage : GoalCoverageReport
  /-- The semantic nodes, retained so the report can render per-node detail. -/
  nodes : List SemanticWorkflowNode
  deriving Inhabited

namespace UnifiedVerificationReport

def hoareSound (r : UnifiedVerificationReport) : Bool :=
  match r.hoare with | .success _ => true | _ => false

def infoSound (r : UnifiedVerificationReport) : Bool := r.info.passed

def coverageLevel (r : UnifiedVerificationReport) : GoalCoverageLevel := r.coverage.coverageLevel

/-- A workflow is fully verified iff all three channels are clean. -/
def allSound (r : UnifiedVerificationReport) : Bool :=
  r.hoareSound && r.infoSound && (r.coverage.coverageLevel == .fullyCovered)

/-- Number of Hoare exit facts (0 if the chain failed). -/
def exitFactCount (r : UnifiedVerificationReport) : Nat :=
  match r.hoare with | .success fs => fs.length | _ => 0

end UnifiedVerificationReport

/-! ## Part 2: the entry point -/

/-- Run all three Layer-2 channels against the graph and bundle the results.
    The `goalSpec` is taken from the graph itself (§2.3.1); the information
    overlay is derived from the node fields; goal coverage reads the node
    graph-fields (and, for back-compat, legacy postcond markers — the extraction
    is a union). -/
def SemanticWorkflowGraph.verifyWorkflow
    (graph : SemanticWorkflowGraph)
    (registry : UnifiedPredicateRegistry := defaultUnifiedRegistry)
    (label : String := "") : UnifiedVerificationReport :=
  let coverage := analyzeGoalCoverage graph graph.goalSpec registry
  let info := verifyInformationFlow graph (InformationFlowSpec.fromGraph graph)
  { label := label
    hoare := coverage.semanticSoundness
    info := info
    coverage := coverage
    nodes := graph.semanticNodes }

/-- Boolean entry point for `native_decide` soundness theorems. -/
def SemanticWorkflowGraph.isFullyVerifiedBool
    (graph : SemanticWorkflowGraph)
    (registry : UnifiedPredicateRegistry := defaultUnifiedRegistry) : Bool :=
  (graph.verifyWorkflow registry).allSound

/-! ## Part 3: pretty printing — the sectioned banner -/

private def checkMark (b : Bool) : String := if b then "✓" else "✗"

/-- The three-line overall verdict banner header. -/
private def bannerHeader (r : UnifiedVerificationReport) : String :=
  let title := if r.label.isEmpty then "LAYER-2 REPORT" else s!"LAYER-2 REPORT · {r.label}"
  let varLine := match r.hoare with
    | .success fs => s!" Variables  ✓ SOUND     ({fs.length} exit facts)"
    | .failure fId name _ _ => s!" Variables  ✗ UNSOUND   (node {fId.val} \"{name}\")"
    | _ => " Variables  ✗ UNSOUND   (chain error)"
  let blocked := r.info.failingNodes.length
  let infoLine :=
    if r.info.passed then s!" Info flow  ✓ SOUND     (0 nodes blocked)"
    else s!" Info flow  ✗ UNSOUND   ({blocked} node{if blocked == 1 then "" else "s"} blocked)"
  let total := r.coverage.goalSpec.subGoals.length
  let full := r.coverage.subGoalAnalyses.filter
    (fun a => computeSubGoalCoverageLevel a == .fullyCovered) |>.length
  let covMark := if r.coverage.coverageLevel == .fullyCovered then "✓" else "✗"
  let covLine := s!" Coverage   {covMark} {full}/{total} sub-goals FULL  ({formatGoalCoverageLevel r.coverage.coverageLevel})"
  let bar := "══════════════════════════════════════════════════════════════"
  s!"{bar}\n {title}\n{bar}\n{varLine}\n{infoLine}\n{covLine}"

/-- Compact rendering of a variable-predicate list, sentinels filtered out. -/
private def fmtVarReqs (reqs : List VariablePredicateRequirement) : String :=
  let real := reqs.filter (fun r => !isSentinelPredicate r.requiredPredicate)
  if real.isEmpty then "(none)"
  else String.intercalate ", " (real.map (fun r => s!"{r.varName}:{r.requiredPredicate.reprAux}"))

/-- The implicit-retry sub-goals a node provides (node field ∪ legacy markers). -/
private def nodeRetries (node : SemanticWorkflowNode) : List String :=
  ((node.graphImplicitRetries.map (·.val)) ++
   (node.postcondVariables.filterMap (fun req =>
      (extractImplicitRetryFromPredicate req.requiredPredicate).map (·.val)))).eraseDups

/-- Coverage level of a sub-goal by name, for annotating a node's contributions. -/
private def subGoalLevelOf (r : UnifiedVerificationReport) (sg : SubGoalName) : String :=
  match r.coverage.subGoalAnalyses.find? (fun a => a.subGoal.name == sg) with
  | some a => formatSubGoalCoverageLevel (computeSubGoalCoverageLevel a)
  | none   => "—"

/-- Step-type label. -/
private def stepTypeStr (st : StepType) : String :=
  match st with
  | .step => "step" | .task => "task" | .whileLoop => "whileLoop"
  | .forEachLoop => "forEachLoop" | .conditional => "conditional"
  | other => s!"{repr other}"

/-- The detailed per-node summary: variable state, information flow, and predicate
    coverage, each as its own labeled subfield. -/
private def formatNodeDetail (r : UnifiedVerificationReport) (node : SemanticWorkflowNode) : String :=
  let name := node.baseNode.name.getD s!"node_{node.id.val}"
  let hdr := s!"  ── node {node.id.val} \"{name}\" [{stepTypeStr node.baseNode.stepType}] ──"
  -- (1) variable state — the Hoare pre/post predicates this node needs / establishes
  let hoareNote := match r.hoare with
    | .failure fId _ m _ =>
      if fId == node.id then s!"        ✗ Hoare chain breaks here: missing {m.requiredPredicate.reprAux} for '{m.varName}'\n" else ""
    | _ => ""
  let vars :=
    s!"      [variable state]\n{hoareNote}" ++
    s!"        requires:     {fmtVarReqs node.precondVariables}\n" ++
    s!"        establishes:  {fmtVarReqs node.postcondVariables}"
  -- (2) information flow — required atoms (how each is satisfied) PLUS the atoms this node WRITES (producesContextInfo / producesVariableInfo); without the writes side the summary lists only consumers and is easy to misread
  let writesCtx := if node.producesContextInfo.isEmpty then "(none)" else formatInfoList node.producesContextInfo
  let writesVar := if node.producesVariableInfo.isEmpty then ""
    else "\n        writes (variable): " ++ String.intercalate ", " (node.producesVariableInfo.map (fun vi => s!"{vi.varName}→{formatInfoList vi.carries}"))
  let writesLine := s!"        writes (context): {writesCtx}{writesVar}"
  let reqPart := match r.info.nodeResults.find? (·.nodeId == node.id) with
    | none => "        (no information required)"
    | some ir =>
      if ir.required.isEmpty then "        (no information required)"
      else
        s!"        requires:     {formatInfoList ir.required}\n" ++
        s!"        via variable: {formatInfoList ir.satisfiedViaVariable}\n" ++
        s!"        via context:  {formatInfoList ir.satisfiedViaContext}\n" ++
        s!"        missing:      {formatInfoList ir.missing}"
  let info := s!"      [information flow]\n{reqPart}\n{writesLine}"
  -- (3) predicate coverage — which sub-goals this node contributes/verifies/retries
  let contribs := (extractSubGoalContributions node).map (·.subGoalName)
  let verifs := (extractSubGoalVerifications node).map (·.subGoalName.val)
  let retries := nodeRetries node
  let contribStr := if contribs.isEmpty then "(none)"
    else String.intercalate ", " (contribs.map (fun sg => s!"{sg.val} → {subGoalLevelOf r sg}"))
  let cov :=
    s!"      [predicate coverage]\n" ++
    s!"        contributes:    {contribStr}\n" ++
    s!"        verifies:       {if verifs.isEmpty then "(none)" else String.intercalate ", " verifs}\n" ++
    s!"        implicit retry: {if retries.isEmpty then "(none)" else String.intercalate ", " retries}"
  s!"{hdr}\n{vars}\n{info}\n{cov}"

private def perNodeDetailSection (r : UnifiedVerificationReport) : String :=
  if r.nodes.isEmpty then "  (no nodes)"
  else String.intercalate "\n" (r.nodes.map (formatNodeDetail r))

/-- One compact line per sub-goal: level + the per-predicate flags + exit facts.
    `+lbl` required-pass, `-lbl` required-FAIL, `~lbl` optional/info pass,
    `!lbl` info FAIL. -/
private def subGoalCoverageLine (a : SubGoalAnalysis) : String :=
  let level := formatSubGoalCoverageLevel (computeSubGoalCoverageLevel a)
  let flag (res : GraphPredicateResult) : String :=
    if res.informational then (if res.passed then s!"~{res.shortLabel}" else s!"!{res.shortLabel}")
    else if res.required then (if res.passed then s!"+{res.shortLabel}" else s!"-{res.shortLabel}")
    else (if res.passed then s!"~{res.shortLabel}" else s!".{res.shortLabel}")
  let predFlags := a.predicateResults.map flag
  let exitFlag := if a.presentInExitFacts then "+exit_facts" else "-exit_facts"
  let flags := String.intercalate " " (predFlags ++ [exitFlag])
  let pad := let n := a.subGoal.name.val.length; if n >= 22 then "" else String.mk (List.replicate (22 - n) ' ')
  s!"  {a.subGoal.name.val}{pad}{level}   [{flags}]"

private def subGoalSection (r : UnifiedVerificationReport) : String :=
  if r.coverage.subGoalAnalyses.isEmpty then "  (no sub-goals specified)"
  else String.intercalate "\n" (r.coverage.subGoalAnalyses.map subGoalCoverageLine)

private def issuesSection (r : UnifiedVerificationReport) : String :=
  let covIssues := r.coverage.issues.map (fun i => s!"  - {formatGraphLevelIssue i}")
  let infoIssues := r.info.failingNodes.map fun nr =>
    s!"  - info: node {nr.nodeId.val} cannot see {formatInfoList nr.missing}"
  let all := covIssues ++ infoIssues
  if all.isEmpty then "  None" else String.intercalate "\n" all

/-- Render the full sectioned-banner report: overall verdict, then per-sub-goal
    coverage, then the consolidated issue list, then — at the bottom — the
    per-node summary with three subfields (variable state · information flow ·
    predicate coverage). -/
def formatUnifiedReport (r : UnifiedVerificationReport) : String :=
  let bar := "──────────────────────────────────────────────────────────────"
  s!"{bannerHeader r}\n{bar}\n SUB-GOAL COVERAGE  (legend: +req·pass  -req·FAIL  ~opt/info·pass  !info·FAIL)\n{subGoalSection r}\n{bar}\n ISSUES\n{issuesSection r}\n{bar}\n PER-NODE SUMMARY  (variable state · information flow · predicate coverage)\n{perNodeDetailSection r}\n══════════════════════════════════════════════════════════════"

/-- Convenience: verify and format in one call. -/
def SemanticWorkflowGraph.verifyWorkflowReport
    (graph : SemanticWorkflowGraph)
    (registry : UnifiedPredicateRegistry := defaultUnifiedRegistry)
    (label : String := "") : String :=
  formatUnifiedReport (graph.verifyWorkflow registry label)

end AgenticKernel
