import Lean
import Mathlib
import AgentVerifier.DynamicVerification.DynamicUnifiedReport

/-!
# Section 7 — Per-Step View (a view over the unified pass)

The generic per-step framework answering Layer-3's core question for each step:

  > "Did the LLM in this step actually move precondition → postcondition?"

This is the §7 of the dynamic layer. Per the redesign, it is a **view** over
the single unified pass (§5): the Layer-2 contract / coverage header is rendered
by §5's unified report; this file contributes the per-step, three-method-AND
diagnosis + re-roll suggestions.

Ported from the original `PerStepMoveAnalysis.lean`, slimmed:
  * the local trace-summary helpers (`countLlm` / `summarizeStepTrace`) are gone —
    they now live on the trace itself (§0 `ExecutionTrace.summarizeStep`);
  * `renderLayer2Contract` / `renderExitFactsDischarge` are gone — `renderFullReport`
    embeds §5's unified report instead of re-deriving the Layer-2 result.

The per-step body format (`StepMoveAnalysis.render`: the `[Lean]/[Tool]/[LLM]`
lines and `STEP COMPOSITE` / `RE-ROLL` banners) is preserved verbatim — the
benchmark harnesses regex-parse it.

## Design

* Per-postcondition-predicate verdict from three methods (Lean symbolic / external
  tool / LLM judge), composed conservatively (any ✗ → falsified).
* Benchmark-specific rules plug in via `PerStepAnalysisRules`; the generic
  analyzer has no hardcoded benchmark knowledge. Ready-to-use SWE-bench glue is in
  the `SWEBench` namespace at the bottom (the ELAIP glue is §9).
-/

namespace AgenticKernel
namespace Dyn

/-!
## §7.1 — Verdict types
-/

structure MethodVerdict where
  passed : Bool
  detail : String
  confidence : Option Float := none
  /-- Whether this method can actually ACT on this predicate (not an N/A fallback).
      Tool: a real attribution rule fired (vs "assumed N/A"). LLM: a real injection
      exists (vs "default PASS"). Drives `composePredicateVerdict`'s authority routing:
      a method that isn't applicable does not get to decide the verdict. -/
  applicable : Bool := true
  deriving Repr, Inhabited

inductive PredicateMoveVerdict where
  | confirmed
  | falsified (rootCause : String)
  | sentinel
  deriving Repr, Inhabited

structure PredicateMoveAnalysis where
  predicate    : VariablePredicateRequirement
  isSentinel   : Bool
  leanVerdict  : Option MethodVerdict
  toolVerdict  : Option MethodVerdict
  llmVerdict   : Option MethodVerdict
  composite    : PredicateMoveVerdict
  deriving Repr, Inhabited

inductive StepMoveVerdict where
  | confirmed
  | falsified (failedPredicates : List String) (reRollSuggestion : String)
  | unknown
  deriving Repr, Inhabited

structure StepMoveAnalysis where
  stepId             : NodeId
  stepName           : String
  traceSummary       : String
  precondHeld        : Bool
  postcondVerdicts   : List PredicateMoveAnalysis
  stepComposite      : StepMoveVerdict
  deriving Inhabited

structure PerPredicateLLMInjection where
  stepName  : String
  varName   : String
  judgement : LLMJudgementResult
  deriving Inhabited

/-!
## §7.2 — Pluggable benchmark rules

Benchmarks plug in their own tool-attribution and re-roll suggestion logic. The
generic analyzer calls only these two functions — no other benchmark knowledge
leaks into the core.
-/

structure PerStepAnalysisRules where
  /-- Given the step name + the specific predicate, what does the external
      (test-result) evidence say about the postcondition's truth? -/
  externalToolVerdict : String → VariablePredicateRequirement → MethodVerdict
  /-- Given a falsified step name + the names of failing predicates, produce a
      re-roll instruction targeted at that step. -/
  reRollSuggestion : String → List String → String

/-- A benign default (all-PASS tool verdicts, generic re-roll messages). -/
def PerStepAnalysisRules.default : PerStepAnalysisRules :=
  { externalToolVerdict := fun _ _ => { passed := true, applicable := false, detail := "no external tool attribution configured" }
    reRollSuggestion := fun step names => s!"[{step}] predicates failed: {String.intercalate ", " names}" }

/-!
## §7.3 — Method 1: Lean symbolic check per predicate
-/

def leanSymbolicCheckOne
    (req : VariablePredicateRequirement)
    (state : NodeExecutionState) : MethodVerdict :=
  if isSentinelPredicate req.requiredPredicate then
    { passed := true, detail := "sentinel — runtime check N/A" }
  else
    let env := state.stateToSemanticEnv
    -- preferExternal := false: when a predicate has a Lean-decidable
    -- implementation (e.g. isValidJson, matchesJsonSchema, isJsonWithFields,
    -- isValidURL), evaluate it symbolically against the saved value rather
    -- than routing to .externalToolVerification → .pendingVerification.
    -- Without this, every per-step diagnosis collapses to the boilerplate
    -- "pending external verification (no result injected)" regardless of
    -- the actual saved trajectory value, and Stage B receives no
    -- per-instance signal.
    let r := verifyVariablePredicate (varPredRequirement := req)
                                      (semanticEnv := env)
                                      (preferExternal := false)
    if r.passed then
      { passed := true, detail := "typed-state predicate satisfied" }
    else
      let why := match r with
        | .leanSymbolicVerificationFail reason => reason
        | .variableNotFound => "variable absent in post-state"
        | .pendingVerification _ => "pending external verification (no result injected)"
        | _ => "unknown failure"
      { passed := false, detail := why }

/-!
## §7.4 — Method 3: LLM judge per predicate (injection)
-/

def llmJudgeVerdictForPredicate
    (stepName : String)
    (req : VariablePredicateRequirement)
    (injections : List PerPredicateLLMInjection) : MethodVerdict :=
  if isSentinelPredicate req.requiredPredicate then
    { passed := true, detail := "sentinel — LLM judge N/A" }
  else
    match injections.find? (fun inj => inj.stepName == stepName ∧ inj.varName == req.varName) with
    | some inj =>
      { passed := inj.judgement.holds, detail := inj.judgement.llmExplanation,
        confidence := some inj.judgement.confidence }
    | none =>
      { passed := true, applicable := false, detail := s!"no LLM injection for ({stepName}, {req.varName}); default PASS" }

/-- Render the §0 per-step trace summary (replaces the old local helpers). -/
def StepTraceSummary.render (s : StepTraceSummary) : String :=
  let toolStr := if s.toolNames.isEmpty then "no tools" else s!"tools: [{String.intercalate ", " s.toolNames}]"
  s!"{s.llmCount} LLM iter, {s.toolStartCount} tool call(s), {toolStr}"

/-!
## §7.5 — Composites and analyzers
-/

/-- Is this predicate's Lean check only a PLACEHOLDER — it asserts existence /
    non-emptiness, or is deferred to an external tool — so Lean alone is NOT
    authoritative about whether the work was really done? For these, the
    authoritative method is the Tool (if it can actually act) else the LLM.
    Lean-decidable *content* predicates (`isValidJson`, `matchesJsonSchema`,
    `isInt`, `containsSubstring`, `isValidURL`, the propositional combinators, …)
    are NOT placeholders — there Lean is authoritative. -/
def isPlaceholderPredicate : PredicateType → Bool
  | .nameExists | .isNonEmptyString | .isNonEmptyList | .taskCompleted
  | .fileExistsAtPath | .toolExists | .moduleExists | .custom _ | .ext _ => true
  | _ => false

/-- AUTHORITY-ROUTED composition (replaces the old conservative `lean ∧ tool ∧ llm`).
    Trust the one method that can actually adjudicate this predicate:
      • non-placeholder (Lean-decidable content) → trust Lean;
      • placeholder + Tool applicable (a real attribution rule fired) → trust Tool;
      • placeholder + Tool N/A but LLM applicable (a real injection) → trust the LLM;
      • placeholder with no applicable Tool/LLM signal → only a non-empty check
        exists, so do not veto (CONFIRMED).
    The other methods' verdicts are still recorded on `PredicateMoveAnalysis` for
    display; they just don't get to override the authoritative one. -/
def composePredicateVerdict
    (req : VariablePredicateRequirement)
    (lean tool llm : MethodVerdict) : PredicateMoveVerdict :=
  if isSentinelPredicate req.requiredPredicate then .sentinel
  else if !isPlaceholderPredicate req.requiredPredicate then
    if lean.passed then .confirmed else .falsified s!"[Lean·authoritative] {lean.detail}"
  else if tool.applicable then
    if tool.passed then .confirmed else .falsified s!"[Tool·authoritative] {tool.detail}"
  else if llm.applicable then
    if llm.passed then .confirmed else .falsified s!"[LLM·authoritative] {llm.detail}"
  else .confirmed

def analyzePredicate
    (req : VariablePredicateRequirement)
    (stepName : String)
    (postState : NodeExecutionState)
    (rules : PerStepAnalysisRules)
    (llmInjections : List PerPredicateLLMInjection) : PredicateMoveAnalysis :=
  if isSentinelPredicate req.requiredPredicate then
    { predicate := req, isSentinel := true,
      leanVerdict := none, toolVerdict := none, llmVerdict := none, composite := .sentinel }
  else
    let lean := leanSymbolicCheckOne req postState
    let tool := rules.externalToolVerdict stepName req
    let llm  := llmJudgeVerdictForPredicate stepName req llmInjections
    { predicate := req, isSentinel := false,
      leanVerdict := some lean, toolVerdict := some tool, llmVerdict := some llm,
      composite := composePredicateVerdict req lean tool llm }

def composeStepVerdict
    (rules : PerStepAnalysisRules)
    (stepName : String)
    (predicateAnalyses : List PredicateMoveAnalysis) : StepMoveVerdict :=
  let falsified := predicateAnalyses.filter fun pa =>
    match pa.composite with | .falsified _ => true | _ => false
  if falsified.isEmpty then .confirmed
  else
    let names := falsified.map (·.predicate.varName)
    .falsified names (rules.reRollSuggestion stepName names)

def analyzeOneStep
    (sem : SemanticWorkflowNode)
    (preState postState : NodeExecutionState)
    (traceSummary : String)
    (rules : PerStepAnalysisRules)
    (llmInjections : List PerPredicateLLMInjection)
    (externals : List ExternalVerificationResult := []) : StepMoveAnalysis :=
  let stepName := sem.baseNode.name.getD "(unnamed)"
  let realPrecond := sem.precondVariables.filter (fun r => !isSentinelPredicate r.requiredPredicate)
  let preEnv := preState.stateToSemanticEnv
  -- External-tool-verified predicates (e.g. `.toolExists` via checker.py) resolve from the
  -- injected `externals`; with none injected they pend exactly as before (default `[]`).
  let precondOk := realPrecond.all fun req =>
    (verifyVariablePredicate req preEnv (externalVerificationResults := externals)).passed
  let postcondAnalyses := sem.postcondVariables.map fun req => analyzePredicate req stepName postState rules llmInjections
  { stepId := sem.id
    stepName := stepName
    traceSummary := traceSummary
    precondHeld := precondOk
    postcondVerdicts := postcondAnalyses
    stepComposite := composeStepVerdict rules stepName postcondAnalyses }

def analyzeAllSteps
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (stepIdMap : StepIdMap)
    (rules : PerStepAnalysisRules)
    (llmInjections : List PerPredicateLLMInjection)
    (externals : List ExternalVerificationResult := []) : List StepMoveAnalysis :=
  dynGraph.dynamicNodeSpecs.map fun spec =>
    let stepIdStr := stepIdMap.toStepId spec.id |>.getD ""
    let summary := (trace.summarizeStep stepIdStr).render
    analyzeOneStep spec.semanticNode spec.preExecutionState spec.postExecutionState summary rules
      llmInjections externals

/-!
## §7.6 — Rendering (per-step body format preserved for harness parsers)
-/

private def methodLine (label : String) (v : Option MethodVerdict) : String :=
  match v with
  | none => s!"      [{label}]  —  N/A"
  | some mv =>
    let mark := if mv.passed then "✓" else "✗"
    s!"      [{label}]  {mark}  {mv.detail}"

def PredicateMoveAnalysis.render (idx : Nat) (pa : PredicateMoveAnalysis) : String :=
  let head := s!"    [{idx}] {pa.predicate.varName} : {repr pa.predicate.requiredPredicate}"
  if pa.isSentinel then
    s!"{head}\n      (sentinel — Layer 2 metadata marker; runtime verification not applicable)"
  else
    let methods :=
      methodLine "Lean" pa.leanVerdict ++ "\n" ++
      methodLine "Tool" pa.toolVerdict ++ "\n" ++
      methodLine "LLM " pa.llmVerdict
    let composite := match pa.composite with
      | .confirmed => "      ⇒ ✓ CONFIRMED"
      | .sentinel => "      ⇒ (sentinel)"
      | .falsified rc => s!"      ⇒ ✗ FALSIFIED — {rc}"
    s!"{head}\n{methods}\n{composite}"

def StepMoveAnalysis.render (a : StepMoveAnalysis) : String :=
  let header := s!"Step {a.stepId.val}  ({a.stepName})"
  let preLine := s!"  precondition at entry: {if a.precondHeld then "✓ held" else "✗ not held (or pending external)"}"
  let traceLine := s!"  trace: {a.traceSummary}"
  let realCount := (a.postcondVerdicts.filter (fun pa => !pa.isSentinel)).length
  let sentCount := (a.postcondVerdicts.filter (fun pa => pa.isSentinel)).length
  let predHead := s!"  Layer 2 postcondition contract: {a.postcondVerdicts.length} predicate(s) ({realCount} runtime + {sentCount} sentinel(s))"
  let predBlocks := (a.postcondVerdicts.zipIdx).map fun (pa, i) => PredicateMoveAnalysis.render (i + 1) pa
  let predBody := String.intercalate "\n\n" predBlocks
  let stepVerdict := match a.stepComposite with
    | .confirmed => "  ⇒ STEP COMPOSITE: ✓ CONFIRMED  (every postcond predicate verified)"
    | .unknown => "  ⇒ STEP COMPOSITE: ? UNKNOWN"
    | .falsified failedPreds reRoll =>
      s!"  ⇒ STEP COMPOSITE: ✗ FALSIFIED on predicate(s): {String.intercalate ", " failedPreds}\n  RE-ROLL: {reRoll}"
  s!"───────────────────────────────────────────────────────────────────────\n{header}\n{preLine}\n{traceLine}\n\n{predHead}\n\n{predBody}\n\n{stepVerdict}"

/-- Per-step summary line (steps / confirmed / falsified / failing predicates). -/
def renderPerStepSummary (analyses : List StepMoveAnalysis) : String :=
  let confirmed := analyses.filter (fun a => match a.stepComposite with | .confirmed => true | _ => false)
  let falsified := analyses.filter (fun a => match a.stepComposite with | .falsified _ _ => true | _ => false)
  let firstFails := falsified.flatMap fun a => match a.stepComposite with
    | .falsified preds _ => preds.map fun p => s!"step {a.stepId.val} '{a.stepName}' / {p}"
    | _ => []
  s!"  PER-STEP PER-PREDICATE LAYER 3 DISCHARGE\n"
    ++ s!"  steps total: {analyses.length}  |  ✓ confirmed: {confirmed.length}  |  ✗ falsified: {falsified.length}\n"
    ++ s!"  failed predicates (overall):  "
    ++ (if firstFails.isEmpty then "none" else String.intercalate "  •  " firstFails)

/-- Does the step that produces `varName` have its three-method composite FALSIFIED
    (Lean ∧ Tool ∧ LLM rejected, i.e. the evidence is structurally present but the
    Tool and/or LLM verdict says the work was not actually done)? -/
def moveFalsifiedForVar (analyses : List StepMoveAnalysis) (varName : String) : Bool :=
  analyses.any fun a =>
    a.postcondVerdicts.any fun p =>
      p.predicate.varName == varName &&
      (match p.composite with | .falsified _ => true | _ => false)

/-- Fold the per-step three-method composites into the unified report's coverage
    channel. A sub-goal whose producing step's move is falsified is marked
    `moveFalsified` (making it `!passed`), and `overallResult` is recomputed — so
    `coverageSound` / `allSound` and the banner reflect the failed moves instead of
    the structural-only "all pass". The variable / info / graph channels (which are
    structural) are unchanged. This is what reconciles the unified banner with the
    per-step diagnosis below it. -/
def reconcileUnifiedWithMoves
    (report : DynamicUnifiedVerificationReport)
    (analyses : List StepMoveAnalysis) : DynamicUnifiedVerificationReport :=
  let newSubs := report.coverage.subGoalVerifications.map fun v =>
    { v with moveFalsified := moveFalsifiedForVar analyses v.subGoal.variableName }
  let newCoverage := { report.coverage with
    subGoalVerifications := newSubs
    overallResult := computeDynamicGoalCoverageResult newSubs }
  { report with coverage := newCoverage }

/-- The full Layer-3 report: §5's unified report (now RECONCILED with the
    per-step three-method composites — see `reconcileUnifiedWithMoves`) as the
    header, then the per-step per-predicate bodies. The banner's Coverage / Moves
    lines and ISSUES therefore agree with the per-step FALSIFIED verdicts below. -/
def renderFullReport
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (analyses : List StepMoveAnalysis)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (label : String := "") : String :=
  let sep := "═══════════════════════════════════════════════════════════════════════"
  let report := reconcileUnifiedWithMoves
    (verifyDynamicWorkflow dynGraph trace goalSpec (stepIdMap := stepIdMap) (label := label)) analyses
  let unified := formatDynamicUnifiedReport report
  let summary := renderPerStepSummary analyses
  let bodies := analyses.map StepMoveAnalysis.render |> String.intercalate "\n\n"
  s!"{unified}\n\n{sep}\n{summary}\n{sep}\n\n{bodies}\n{sep}"

/-!
## §7.7 — SWE-bench glue (benchmark-specific; the ELAIP analogue is §9)

Ready-to-use `report.json` decoder + tool-attribution rules keyed on the canonical
SWE-bench step names and evidence variables. For another benchmark, write your own
analog and construct a `PerStepAnalysisRules`.
-/

namespace SWEBench

structure TestSetResult where
  success : List String := []
  failure : List String := []
  deriving Repr, Inhabited

structure TestStatus where
  failToPass : TestSetResult := {}
  passToPass : TestSetResult := {}
  failToFail : TestSetResult := {}
  passToFail : TestSetResult := {}
  deriving Repr, Inhabited

structure InstanceReport where
  instanceId               : String
  patchExists              : Bool := false
  patchSuccessfullyApplied : Bool := false
  resolved                 : Bool := false
  testsStatus              : TestStatus := {}
  deriving Repr, Inhabited

namespace InstanceReport

private def jsonStrList (j : Lean.Json) : List String :=
  match j.getArr? with
  | .ok arr => arr.toList.filterMap fun el => match el with | .str s => some s | _ => none
  | .error _ => []

private def jsonOptBool (j : Lean.Json) (key : String) : Bool :=
  match j.getObjVal? key with | .ok (.bool b) => b | _ => false

private def parseTestSetResult (j : Lean.Json) : TestSetResult :=
  let succ := match j.getObjVal? "success" with | .ok arr => jsonStrList arr | _ => []
  let fail := match j.getObjVal? "failure" with | .ok arr => jsonStrList arr | _ => []
  ⟨succ, fail⟩

private def parseTestStatus (j : Lean.Json) : TestStatus :=
  let g (k : String) : TestSetResult := match j.getObjVal? k with | .ok sub => parseTestSetResult sub | _ => {}
  ⟨g "FAIL_TO_PASS", g "PASS_TO_PASS", g "FAIL_TO_FAIL", g "PASS_TO_FAIL"⟩

/-- Parse a `report.json` whose top level is `{ "<instance_id>": { ... } }`. -/
def fromJson (j : Lean.Json) : Except String InstanceReport :=
  match j.getObj? with
  | .error e => .error e
  | .ok kvs =>
    match kvs.toArray.toList with
    | [] => .error "report.json has no instance entry"
    | ⟨instanceId, body⟩ :: _ =>
      let tests := match body.getObjVal? "tests_status" with | .ok t => parseTestStatus t | _ => {}
      .ok { instanceId := instanceId,
            patchExists := jsonOptBool body "patch_exists",
            patchSuccessfullyApplied := jsonOptBool body "patch_successfully_applied",
            resolved := jsonOptBool body "resolved",
            testsStatus := tests }

def loadFromFile (path : System.FilePath) : IO InstanceReport := do
  let raw ← IO.FS.readFile path
  match Lean.Json.parse raw with
  | .error e => throw (IO.userError s!"malformed report.json: {e}")
  | .ok j => match fromJson j with
    | .ok r => return r
    | .error e => throw (IO.userError s!"decode failed: {e}")

end InstanceReport

/-- Canonical SWE-bench tool-attribution rule. -/
def toolVerdictForPredicate
    (report : InstanceReport)
    (stepName : String)
    (req : VariablePredicateRequirement) : MethodVerdict :=
  if isSentinelPredicate req.requiredPredicate then
    { passed := true, applicable := false, detail := "sentinel — no test attribution" }
  else
    match stepName, req.varName with
    | "fix_issue", "fix_implementation_evidence" =>
      let f := report.testsStatus.failToPass.failure
      let p := report.testsStatus.passToPass.failure
      if f.isEmpty ∧ p.isEmpty then
        { passed := true, detail := "all FAIL_TO_PASS + PASS_TO_PASS green — fix evidence is genuine" }
      else
        let parts := (if f.isEmpty then [] else [s!"FAIL_TO_PASS still failing ({f.length})"]) ++
          (if p.isEmpty then [] else [s!"PASS_TO_PASS regressed ({p.length})"])
        { passed := false, detail := s!"this predicate claims fix is established but: {String.intercalate "; " parts}" }
    | "verify_fix", "fix_verification_evidence" =>
      let f := report.testsStatus.failToPass.failure
      let p := report.testsStatus.passToPass.failure
      if f.isEmpty ∧ p.isEmpty then
        { passed := true, detail := "tests confirm verify-step verdict for this predicate" }
      else
        { passed := false, detail := s!"this predicate claims verification is done but {f.length + p.length} test(s) ultimately failed" }
    | "create_patch", "patch_submission_evidence" =>
      if report.patchExists ∧ report.patchSuccessfullyApplied then
        { passed := true, detail := "patch_exists ∧ patch_successfully_applied ✓" }
      else if !report.patchExists then { passed := false, detail := "no patch produced" }
      else { passed := false, detail := "patch produced but failed to apply" }
    | _, _ =>
      { passed := true, applicable := false, detail := s!"no test attribution rule for ({stepName}, {req.varName}) — assumed N/A" }

/-- Canonical SWE-bench per-step re-roll suggestions. -/
def reRollForStep (stepName : String) (failedNames : List String) : String :=
  let preds := String.intercalate ", " failedNames
  match stepName with
  | "fix_issue" =>
    s!"[fix_issue] predicate(s) failed: {preds}. Modify the YAML instruction to: "
    ++ "(a) require minimal-scope edit on the touched file, "
    ++ "(b) demand running the precise FAIL_TO_PASS test path before declaring success, "
    ++ "(c) explicitly preserve the affected class's existing tests."
  | "verify_fix" =>
    s!"[verify_fix] predicate(s) failed: {preds}. Modify the YAML instruction to: "
    ++ "replace any keyword-filtered pytest with the explicit FAIL_TO_PASS test path; "
    ++ "require zero new failures across the affected test class; "
    ++ "do not dismiss collection errors as 'unrelated'."
  | "create_patch" =>
    s!"[create_patch] predicate(s) failed: {preds}. Validate diff format and applicability before returning."
  | "explore_repository" =>
    s!"[explore_repository] predicate(s) failed: {preds}. Require identifying the canonical handler/idiom (not first plausible)."
  | "reproduce_issue" =>
    s!"[reproduce_issue] predicate(s) failed: {preds}. Require capturing the precise failure signature."
  | _ =>
    s!"[{stepName}] predicate(s) failed: {preds}. Tighten this step's postcondition contract."

/-- Turn a SWE-bench `InstanceReport` into the `PerStepAnalysisRules`. -/
def rulesFromReport (report : InstanceReport) : PerStepAnalysisRules :=
  { externalToolVerdict := toolVerdictForPredicate report
    reRollSuggestion    := reRollForStep }

end SWEBench

end Dyn
end AgenticKernel
