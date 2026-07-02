import Lean
import Mathlib
import AgentVerifier.DynamicVerification.DynamicUnifiedReport

/-!
# Section 6 — IO / External-Python boundary (online query mode)

The IO-mode utilities: the **external-Python verification method's live path**
(`runExternalVerification` → `checker.py`) and the IO twins of the variable /
graph verifiers. This is the §6 of the dynamic layer.

Two execution modes coexist across the layer:
  * **Injection mode** (§1–§5, `native_decide`-friendly): tool/LLM verdicts are
    pre-computed outside Lean and injected as data.
  * **IO mode** (this file): Lean shells out to `checker.py` live for the
    external-tool method. (The LLM method's "online query" is performed by the
    Python/agent harness and still reaches Lean as an injected verdict — Lean
    never calls an LLM directly, mirroring the original design.)

Ported from the original `AgentVerifier/DynamicVerification/DynamicVerificationUtils.lean`,
re-homed under `namespace AgenticKernel.Dyn`, with the **L7 legacy dependency
removed**: `verifyGraphPredicateIO` no longer has the `isLLMPortKey` /
`substringAspectFallback` two-tier path (those went with the deprecated aspect
model). It uses the same clean 3-method dispatch with a Lean floor as §3's
injection-mode `verifyGraphPredicate`.
-/

namespace AgenticKernel
namespace Dyn

/-!
## §6.1 — Execution-state / injection-result constructors
-/

/-- Make an execution state from a list of variable name and raw string explanations. -/
def makeExecutionState (vars : List (String × String)) : NodeExecutionState :=
  vars.map fun (name, rawStr) => (name, NodeExecutionValue.fromString rawStr)

/-- Make an execution state with a list of variable name, raw string explanations, and parsed values. -/
def makeExecutionStateWithValues (vars : List (String × String × Value)) : NodeExecutionState :=
  vars.map fun (name, rawStr, value) => (name, NodeExecutionValue.withParsed rawStr value)

/-- Create an `ExternalVerificationResult` for a predicate checked by an external
    Python tool call or LLM judgement (injection mode). Pass the actual
    `PredicateType` that this result answers for. -/
def makeExternalVerificationResult
  (varName : String)
  (predicateType : PredicateType)
  (externalToolResult : Option ExternalToolJudgementResult := none)
  (llmJudgementResult : Option LLMJudgementResult := none) : ExternalVerificationResult :=
  { varName := varName, predicateType := predicateType,
    externalToolResult := externalToolResult, llmJudgementResult := llmJudgementResult }

/-- Register a tool for the runtime environment (as a `.toolExists` injection). -/
def registerExternalTool (toolName : String) : ExternalVerificationResult :=
  let externalToolResult : ExternalToolJudgementResult :=
    makeExternalToolJudgementResult "tool_registry" true s!"Tool '{toolName}' successfully registered"
  makeExternalVerificationResult toolName .toolExists (some externalToolResult) none

/-- Determine which conditional branch the trajectory took. -/
def determineBranchInConditionalNode
  (conditionalNode : SemanticConditionalNode)
  (nextExecutedNodeId : NodeId) : ConditionalBranchType :=
  if nextExecutedNodeId == conditionalNode.thenTargetId then .thenBranch else .elseBranch

/-- Concise one-line-per-node verification summary. -/
def runDynamicVerification (specs : List DynamicNodeSpec) : String :=
  let reports := specs.map fun status =>
    let symbol := match getNodeVerifyStatus status with
      | .verified => "✓"
      | .precondFailed _ => "✗ Precondition Failed"
      | .postcondFailed _ => "✗ Postcondition Failed"
      | .pending _ => "⏳ Pending"
      | .skipped  => "⏭ Skipped"
    s!"{symbol} Node {status.id.val} ({status.trajectoryStepName})"
  (reports ++ [s!"\nResult: {if specs.all (·.nodeVerified) then "ALL VERIFIED" else "INCOMPLETE"}"])
    |> String.intercalate "\n"

/-!
## §6.2 — External verifier registry (tool_name → script)
-/

/-- Binds how a specific tool_name maps to an external verification script. -/
inductive ExternalVerifierBinding where
  | shellCommand (cmd : String)
  | pythonVerifierWithFunc (pythonVerifierPath : String) (functionName : String)
  deriving Repr, Inhabited

/-- Maps tool_name → which script to call. Separate from `VerificationRegistry`
    (which maps `PredicateKey` → method). -/
structure ExternalVerifierRegistry where
  bindings : List (String × ExternalVerifierBinding) := []
  defaultVerifierFilepath : String := "./checker.py"
  verifierName : String := "python3"
  fallbackToLean : Bool := true
  deriving Repr, Inhabited

namespace ExternalVerifierRegistry

def empty : ExternalVerifierRegistry := {}

def bind (baseRegistry : ExternalVerifierRegistry) (toolName : String)
    (binding : ExternalVerifierBinding) : ExternalVerifierRegistry :=
  { baseRegistry with bindings := (toolName, binding) :: baseRegistry.bindings }

def bindShellCommand (baseRegistry : ExternalVerifierRegistry)
    (toolName shellCommand : String) : ExternalVerifierRegistry :=
  baseRegistry.bind toolName (.shellCommand shellCommand)

def bindPythonVerifier (baseRegistry : ExternalVerifierRegistry)
    (toolName pythonVerifierPath : String) (functionName : String) : ExternalVerifierRegistry :=
  baseRegistry.bind toolName (.pythonVerifierWithFunc pythonVerifierPath functionName)

def bindManyOneVerifierToManyTools (baseRegistry : ExternalVerifierRegistry)
    (toolNames : List String) (pythonVerifierPath : String) (functionName : String) : ExternalVerifierRegistry :=
  toolNames.foldl (fun registry toolName =>
    registry.bindPythonVerifier toolName pythonVerifierPath functionName) baseRegistry

/-- Resolve tool_name → (executable command, base args). -/
def resolve (externalVerifierRegistry : ExternalVerifierRegistry)
    (toolName : String) : String × List String :=
  match externalVerifierRegistry.bindings.find? (fun (currToolName, _) => currToolName == toolName) with
  | some (_, .shellCommand cmd) => ("sh", ["-c", cmd])
  | some (_, .pythonVerifierWithFunc pythonVerifierPath functionName) =>
    (externalVerifierRegistry.verifierName, [pythonVerifierPath, "--func", functionName, toolName])
  | none => (externalVerifierRegistry.verifierName, [externalVerifierRegistry.defaultVerifierFilepath, toolName])

end ExternalVerifierRegistry

/-!
## §6.3 — External-Python verification (Method 2, live)
-/

/-- Call a Python verifier script for a single predicate via `IO.Process`.
    Protocol: argv `[tool_name, pred_json, var_name, raw_value]` where `pred_json`
    is `PredicateType.toJsonStr`; the script prints `{"passed": bool, "detail": string}`. -/
def runExternalVerification
  (registry : ExternalVerifierRegistry)
  (toolName predJson varName rawValue : String) : IO ExternalToolJudgementResult := do
  try
    let (executable, baseArgs) := registry.resolve toolName
    let args := baseArgs ++ [predJson, varName, rawValue]
    let result ← IO.Process.output { cmd := executable, args := args.toArray }
    if result.exitCode != 0 then
      return { toolName, passed := false, additionalInfo := s!"Exit code {result.exitCode}, stderr: {result.stderr}" }
    let stdout := result.stdout.trim
    match Lean.Json.parse stdout with
    | .ok json =>
      let passed := match json.getObjVal? "passed" with | .ok (.bool b) => b | _ => false
      let detail := match json.getObjVal? "detail" with | .ok (.str s) => s | _ => stdout
      return { toolName, passed, additionalInfo := detail }
    | .error err =>
      return { toolName, passed := false, additionalInfo := s!"Json parsing error: {err}, raw output: {stdout}" }
  catch exception =>
    return { toolName, passed := false, additionalInfo := s!"Execution error: {toString exception}" }

/-- IO-lifted predicate verification: run Lean first; on pending external-tool,
    call the Python verifier; on pending LLM-judge, stay pending (online LLM is the
    harness's job, injected back). -/
def verifyPredicateIO
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName rawValue : String)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO DynamicPredicateVerificationResult := do
  let leanResult := leanSymbolicPredicateVerification predType semanticEnv varName verificationRegistry true
  match leanResult with
  | .leanSymbolicVerificationFail _ =>
    match predType with
    | .isNonEmptyList | .isValidList =>
      let predJson := PredicateType.toJsonStr predType
      let externalResult ← runExternalVerification externalVerifierRegistry "list_validator" predJson varName rawValue
      if externalResult.passed then return .externalToolVerificationPass externalResult
      else return leanResult
    | _ => return leanResult
  | .pendingVerification (.externalToolVerification toolName) =>
    let predJson := PredicateType.toJsonStr predType
    let externalResult ← runExternalVerification externalVerifierRegistry toolName predJson varName rawValue
    if externalResult.passed then return .externalToolVerificationPass externalResult
    else if externalVerifierRegistry.fallbackToLean then
      match leanSymbolicPredicateVerification predType semanticEnv varName verificationRegistry false with
      | .leanSymbolicVerificationPass => return .leanSymbolicVerificationPass
      | _ => return .externalToolVerificationFail externalResult
    else return .externalToolVerificationFail externalResult
  | .pendingVerification .llmJudgeVerification =>
    return .pendingVerification .llmJudgeVerification
  | other => return other

/-- Verify a single variable requirement via IO. -/
def verifyVariablePredicateIO
  (requirement : VariablePredicateRequirement)
  (nodeExecutionState : NodeExecutionState)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO DynamicPredicateVerificationResult := do
  let env := nodeExecutionState.stateToSemanticEnv
  let rawValue := nodeExecutionState.getRawString requirement.varName |>.getD ""
  verifyPredicateIO requirement.requiredPredicate env requirement.varName rawValue externalVerifierRegistry verificationRegistry

/-- Verify a list of variable requirements via IO. -/
def verifyListVariablePredicateIO
  (requirements : List VariablePredicateRequirement)
  (nodeExecutionState : NodeExecutionState)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO (List PredicateVerificationEntry) := do
  let mut results : List PredicateVerificationEntry := []
  for curr_requirement in requirements do
    let result ← verifyVariablePredicateIO curr_requirement nodeExecutionState externalVerifierRegistry verificationRegistry
    results := results ++ [{ requirement := curr_requirement, dynamicVerificationResult := result }]
  return results

/-!
## §6.4 — IO node-spec builders
-/

def buildDynamicNodeSpecIO
  (semanticWorkflowNode : SemanticWorkflowNode)
  (preExecutionState postExecutionState : NodeExecutionState)
  (stepID stepName : String)
  (verificationStatus : ExecutionStatus := .completed)
  (externalVerficationRegistry : ExternalVerifierRegistry := {})
  (verficationRegistry : VerificationRegistry := .empty) : IO DynamicNodeSpec := do
  let precondVerificationResult ← verifyListVariablePredicateIO
    semanticWorkflowNode.precondVariables preExecutionState externalVerficationRegistry verficationRegistry
  let postcondVerificationResult ← verifyListVariablePredicateIO
    semanticWorkflowNode.postcondVariables postExecutionState externalVerficationRegistry verficationRegistry
  return {
    semanticNode := semanticWorkflowNode,
    preExecutionState := preExecutionState,
    postExecutionState := postExecutionState,
    precondVerificationEntries := precondVerificationResult,
    postcondVerificationEntries := postcondVerificationResult,
    trajectoryStepId := stepID,
    trajectoryStepName := stepName,
    executionStatus := verificationStatus }

/-- Resolve pending verifications in existing `DynamicNodeSpec`s via IO. -/
def runVerificationIO
  (dynamicNodeSpecs : List DynamicNodeSpec)
  (verifierRegistry : ExternalVerifierRegistry := {}) : IO String := do
  let mut resolved : List DynamicNodeSpec := []
  for currSpec in dynamicNodeSpecs do
    if currSpec.hasPending && currSpec.executionStatus != .skipped then
      let precondVerified ← verifyListVariablePredicateIO
        currSpec.semanticNode.precondVariables currSpec.preExecutionState verifierRegistry
      let postcondVerified ← verifyListVariablePredicateIO
        currSpec.semanticNode.postcondVariables currSpec.postExecutionState verifierRegistry
      resolved := resolved ++ [{ currSpec with
        precondVerificationEntries := precondVerified, postcondVerificationEntries := postcondVerified }]
    else resolved := resolved ++ [currSpec]
  return runDynamicVerification resolved

def buildDynamicConditionalNodeSpecIO
  (conditionalNode : SemanticConditionalNode)
  (preExecutationState postExecutionState : NodeExecutionState)
  (branchTaken : ConditionalBranchType)
  (stepId stepName : String)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO DynamicConditionalNodeSpec := do
  let baseNode ← buildDynamicNodeSpecIO conditionalNode preExecutationState postExecutionState
    stepId stepName .completed externalVerifierRegistry verificationRegistry
  let branchPostconds := match branchTaken with
    | .thenBranch => conditionalNode.thenPostcondVariables
    | .elseBranch => conditionalNode.elsePostcondVariables
  let branchPostcondVerificationResult ← verifyListVariablePredicateIO
    branchPostconds postExecutionState externalVerifierRegistry verificationRegistry
  return {
    toDynamicNodeSpec := { baseNode with postcondVerificationEntries := branchPostcondVerificationResult },
    conditionalNode := conditionalNode,
    conditionalBranchType := branchTaken }

def buildSingleLoopIterationRecordIO
  (loopNode : SemanticLoopNode)
  (iterIdx : Nat)
  (preExecutionState postExecutionState : NodeExecutionState)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO SingleLoopIterationRecord := do
  let precondVerifiedResult ← verifyListVariablePredicateIO
    loopNode.loopInvariant preExecutionState externalVerifierRegistry verificationRegistry
  let postcondVerifiedResult ← verifyListVariablePredicateIO
    loopNode.loopInvariant postExecutionState externalVerifierRegistry verificationRegistry
  return {
    iterationIndex := iterIdx,
    preExecutionState := preExecutionState,
    postExecutionState := postExecutionState,
    invariantPreIteration := precondVerifiedResult,
    invariantPostIteration := postcondVerifiedResult }

def buildDynamicLoopNodeSpecIO
  (loopNode : SemanticLoopNode)
  (preExecutionState postExecutionState : NodeExecutionState)
  (stepId stepName : String)
  (iterationRecords : List SingleLoopIterationRecord := [])
  (loopTerminatedNormally : Bool := true)
  (externalVerifierRegistry : ExternalVerifierRegistry := {})
  (verificationRegistry : VerificationRegistry := .empty) : IO DynamicLoopNodeSpec := do
  let baseNode ← buildDynamicNodeSpecIO loopNode.toSemanticWorkflowNode preExecutionState postExecutionState
    stepId stepName .completed externalVerifierRegistry verificationRegistry
  let loopExitVerification ← verifyListVariablePredicateIO
    loopNode.exitPostconditions postExecutionState externalVerifierRegistry verificationRegistry
  return {
    toDynamicNodeSpec := { baseNode with
      postcondVerificationEntries := baseNode.postcondVerificationEntries ++ loopExitVerification }
    loopNode := loopNode,
    iterationRecords := iterationRecords,
    loopTerminatedNormally := loopTerminatedNormally }

/-!
## §6.5 — Graph-level IO bridge (typed context → JSON for `checker.py`)

Serializes a `DynamicGraphCheckContext` into the JSON payload the Python checker's
graph handler expects. Every field is pre-computed in Lean — the Python handlers
do pure typed pattern matching.
-/

namespace DynamicGraphIO

private def natListJson (xs : List Nat) : Lean.Json :=
  Lean.Json.arr (xs.map Lean.Json.num |>.toArray)

private def nodeIdListJson (xs : List NodeId) : Lean.Json :=
  natListJson (xs.map (·.val))

def graphContextToJson (ctx : DynamicGraphCheckContext) : Lean.Json :=
  let graph := ctx.graph
  let allExecuted := executedCompletedNodes ctx.trace ctx.stepIdMap graph
  let contribReachesExit : List Lean.Json :=
    ctx.executedContributingNodes.flatMap fun c =>
      graph.exits.map fun e =>
        Lean.Json.mkObj [
          ("contrib", Lean.Json.num c.val),
          ("exit",    Lean.Json.num e.val),
          ("reaches", Lean.Json.bool (c == e || graph.reachable c e)) ]
  let contribVerifyOrdered : List Lean.Json :=
    ctx.executedContributingNodes.flatMap fun c =>
      ctx.executedVerificationNodes.filterMap fun v =>
        if c == v then none
        else
          let ordered := match ctx.stepIdMap.toStepId c, ctx.stepIdMap.toStepId v with
            | some csid, some vsid =>
              match ctx.trace.stepLastIndex csid, ctx.trace.stepFirstIndex vsid with
              | some cLast, some vFirst => vFirst > cLast
              | _, _ => graph.reachable c v
            | _, _ => graph.reachable c v
          some (Lean.Json.mkObj [
            ("contrib", Lean.Json.num c.val),
            ("verify",  Lean.Json.num v.val),
            ("ordered", Lean.Json.bool ordered) ])
  let iterCounts : List Lean.Json :=
    ctx.executedContributingNodes.filterMap fun n =>
      match ctx.stepIdMap.toStepId n with
      | some sid => some (Lean.Json.mkObj [
          ("node_id",  Lean.Json.num n.val),
          ("max_iter", Lean.Json.num (ctx.trace.maxIteration sid)) ])
      | none => none
  let staticLoopBackPassed := GraphLevelPredicate.check UnifiedLoopBackCheck.mk ctx.toGraphCheckContext
  let fallbackWriterIds : List NodeId :=
    graph.semanticNodes.filterMap fun fallbackNode =>
      let annotated := fallbackNode.postcondVariables.any fun req =>
        extractContributionFromPredicate req.requiredPredicate == some ctx.subGoalName
      if annotated then some fallbackNode.id else none
  let finalVars : List Lean.Json :=
    ctx.finalExecState.map fun (name, v) =>
      Lean.Json.mkObj [ ("name", Lean.Json.str name), ("raw",  Lean.Json.str v.rawString) ]
  Lean.Json.mkObj [
    ("sub_goal_name",                  Lean.Json.str ctx.subGoalName.val),
    ("executed_node_ids",              nodeIdListJson allExecuted),
    ("executed_contributing_node_ids", nodeIdListJson ctx.executedContributingNodes),
    ("executed_verification_node_ids", nodeIdListJson ctx.executedVerificationNodes),
    ("exit_node_ids",                  nodeIdListJson graph.exits),
    ("contrib_reaches_exit",           Lean.Json.arr contribReachesExit.toArray),
    ("contrib_verify_ordered",         Lean.Json.arr contribVerifyOrdered.toArray),
    ("node_iteration_counts",          Lean.Json.arr iterCounts.toArray),
    ("static_loop_back_passed",        Lean.Json.bool staticLoopBackPassed),
    ("fallback_writer_node_ids",       nodeIdListJson fallbackWriterIds),
    ("final_vars",                     Lean.Json.arr finalVars.toArray) ]

end DynamicGraphIO

/-!
## §6.6 — IO-mode graph predicate verification (de-legacied)

The clean 3-method dispatch (no `isLLMPortKey` / `substringAspectFallback`),
mirroring §3's `verifyGraphPredicate` with `checker.py` for the external-tool tier.
-/

/-- IO-mode verification of a single graph-level predicate. Dispatch on
    `defaultMethod`, Lean `checkLean` as floor:
      * `leanSymbolic`  : run `checkLean`.
      * `externalTool t`: call `checker.py` with the typed graph-context JSON;
        fall back to `checkLean` if the call fails (when `fallbackToLean`).
      * `llmJudge`      : use the injected LLM verdict, else fall back to `checkLean`. -/
def verifyGraphPredicateIO
    (entry : DynamicGraphLevelPredicateEntry)
    (subGoalName : SubGoalName)
    (required : Bool)
    (ctx : DynamicGraphCheckContext)
    (externalVerifierRegistry : ExternalVerifierRegistry := {})
    (injected : List GraphExternalVerificationResult := [])
    : IO DynamicGraphPredicateResult := do
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
  let leanPassed := entry.checkLean ctx
  match entry.defaultMethod with
  | .leanSymbolicVerification =>
    return mkBase .leanSymbolicVerification leanPassed
      (if leanPassed then "lean symbolic check passed" else "lean symbolic check failed")
  | .externalToolVerification toolName =>
    let predJson := (Lean.Json.mkObj [("predicateKey", Lean.Json.str entry.predicateKey.name)]).compress
    let rawValue := (DynamicGraphIO.graphContextToJson ctx).compress
    let toolRes ← runExternalVerification externalVerifierRegistry toolName predJson subGoalName.val rawValue
    if toolRes.passed then
      return mkBase (.externalToolVerification toolName) true toolRes.additionalInfo (some toolRes) none
    else if externalVerifierRegistry.fallbackToLean then
      return mkBase (.externalToolVerification toolName) leanPassed
        (if leanPassed then s!"tool failed; lean fallback passed. tool: {toolRes.additionalInfo}"
         else s!"tool failed; lean fallback failed. tool: {toolRes.additionalInfo}") (some toolRes) none
    else
      return mkBase (.externalToolVerification toolName) false toolRes.additionalInfo (some toolRes) none
  | .llmJudgeVerification =>
    match (findGraphExternalResult injected entry.predicateKey subGoalName).bind (·.llmJudgementResult) with
    | some j => return mkBase .llmJudgeVerification j.holds s!"LLM judge: {j.llmExplanation}" none (some j)
    | none =>
      return mkBase .llmJudgeVerification leanPassed
        (if leanPassed then "llm judge not injected; lean fallback passed"
         else "llm judge not injected; lean fallback failed")

/-- Run every registered graph-level predicate for a sub-goal (IO). -/
def runGraphPredicatesForSubGoalIO
    (reg : UnifiedDynamicPredicateRegistry)
    (ctx : DynamicGraphCheckContext)
    (requiredKeys : List PredicateKey := [])
    (externalVerifierRegistry : ExternalVerifierRegistry := {})
    (injected : List GraphExternalVerificationResult := [])
    : IO (List DynamicGraphPredicateResult) := do
  let mut acc : List DynamicGraphPredicateResult := []
  for entry in reg.graphEntries do
    let required := requiredKeys.any (· == entry.predicateKey) && !entry.informational
    let r ← verifyGraphPredicateIO entry ctx.subGoalName required ctx externalVerifierRegistry injected
    acc := acc ++ [r]
  return acc

/-- Load an execution trace from disk. -/
def loadDynamicTrace (path : System.FilePath) : IO ExecutionTrace :=
  ExecutionTrace.loadEventLog path

/-!
## §6.7 — IO-mode coverage + unified report (online query path)

IO twins of §5's injection-mode builders. The external-tool graph predicates hit
`checker.py` live; the variable channel uses live IO; the information channel is
structural (no IO).
-/

/-- IO-mode per-sub-goal verification (live tool calls for the variable predicate). -/
def verifySubGoalDynamicIO
    (subGoal : SubGoalSpec)
    (finalState : NodeExecutionState)
    (dynGraph : DynamicVerificationGraph)
    (graphAttrs : ExtractedGraphLevelAttributes)
    (externalVerifierRegistry : ExternalVerifierRegistry := {})
    (verificationRegistry : VerificationRegistry := .empty)
    (semanticJudgment : Option LLMJudgementResult := none)
    : IO DynamicSubGoalVerification := do
  let requirement : VariablePredicateRequirement := ⟨subGoal.variableName, subGoal.requiredPredicate⟩
  let varResult ← verifyVariablePredicateIO requirement finalState externalVerifierRegistry verificationRegistry
  let varEntry : PredicateVerificationEntry := ⟨requirement, varResult⟩
  let contributingNodeIds := graphAttrs.contributions |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
  let contribStatuses := contributingNodeIds.map fun nodeId => (nodeId, getNodeExecutionStatus dynGraph nodeId)
  let verificationNodeIds := graphAttrs.verifications |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
  let verifyStatuses := verificationNodeIds.map fun nodeId => (nodeId, getNodeExecutionStatus dynGraph nodeId)
  return { subGoal := subGoal
           variableVerification := varEntry
           contributingNodesExecuted := contribStatuses
           verificationNodesExecuted := verifyStatuses
           semanticJudgment := semanticJudgment }

/-- IO-mode dynamic goal-coverage report (live `checker.py` for graph external tools). -/
def buildDynamicGoalCoverageReportIO
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerifierRegistry : ExternalVerifierRegistry := {})
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (staticReport : GoalCoverageReport :=
      analyzeGoalCoverage dynGraph.semanticWorkflowGraph goalSpec)
    : IO DynamicGoalCoverageReport := do
  let finalState := getFinalExecutionState dynGraph
  let graphAttrs := extractGraphLevelAttributes dynGraph.semanticWorkflowGraph
  let mut subGoalVerifications : List DynamicSubGoalVerification := []
  for subGoal in goalSpec.subGoals do
    let judgment := semanticJudgments.find? (fun (name, _) => name == subGoal.name.val) |>.map (·.2)
    let baseV ← verifySubGoalDynamicIO subGoal finalState dynGraph graphAttrs
      externalVerifierRegistry unifiedReg.varRegistry judgment
    let contribNodes := graphAttrs.contributions |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
    let verifNodes := graphAttrs.verifications |>.filter (·.subGoalName == subGoal.name) |>.map (·.nodeId)
    let ctx := buildGraphCheckContext dynGraph trace subGoal.name contribNodes verifNodes [] PredicateRegistry.empty stepIdMap
    let graphRes ← runGraphPredicatesForSubGoalIO unifiedReg ctx subGoal.requiredGraphPredicates externalVerifierRegistry graphInjected
    subGoalVerifications := subGoalVerifications ++ [{ baseV with graphPredicateResults := graphRes }]
  let overallResult := computeDynamicGoalCoverageResult subGoalVerifications
  return { goalSpec := goalSpec
           subGoalVerifications := subGoalVerifications
           staticAnalysis := staticReport
           overallResult := overallResult }

/-- IO-mode unified entry point. Variable + information channels read the
    already-built (or IO-built) `dynGraph`; the graph/coverage channel runs live
    `checker.py` for the external-tool predicates. -/
def verifyDynamicWorkflowIO
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerifierRegistry : ExternalVerifierRegistry := {})
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (infoInjections : List DynamicInfoFlowInjection := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (label : String := "") : IO DynamicUnifiedVerificationReport := do
  let variable_ := dynGraph.verify
  let info := verifyDynamicInformationFlowFromSpecs dynGraph.semanticWorkflowGraph dynGraph.allNodeSpecs infoInjections
  let coverage ← buildDynamicGoalCoverageReportIO dynGraph trace goalSpec unifiedReg
    externalVerifierRegistry graphInjected semanticJudgments stepIdMap
  return { label := label
           variable_ := variable_
           info := info
           coverage := coverage
           nodeSpecs := dynGraph.dynamicNodeSpecs }

end Dyn
end AgenticKernel
