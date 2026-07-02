import Lean
import Mathlib
import AgentVerifier.DynamicVerification.PerStepView
import AgentVerifier.DynamicVerification.ElaipBench.PredicateChecks

/-!
# Section 9 — ELAIP-Bench Layer-3 Glue

The ELAIP analogue of §7's `SWEBench` namespace, for the paper-comprehension
benchmark where there is **no `report.json`**: the only Layer-3 evidence is the
agent's recorded execution state (variable assignments in `agent_events.log`)
plus optional LLM judgements injected as `PerPredicateLLMInjection`.

The plug-in surface is exactly §7's `PerStepAnalysisRules`: a benchmark-specific
`externalToolVerdict` (the §8 JSON-aware decidable checks) + a benchmark-specific
`reRollSuggestion` (canonical templates keyed on ELAIP step names). No new axioms.

**rewiring**: `runElaipAnalysis` now renders §7's `renderFullReport`, which
embeds §5's **three-channel unified report** — so an ELAIP run now reports the
variable, dynamic **information-flow**, and graph channels (the information
channel was entirely absent in the old Layer-3), not just the old per-step text.
-/

namespace AgenticKernel.Dyn.ElaipBench

open AgenticKernel.Dyn.ElaipBench.PredicateChecks

/-! ## §9.1 — Predicate identification -/

/-- Family used by every ELAIP variable-level `.ext` predicate. -/
def elaipFamily : String := "user.elaip"

inductive ElaipPredicateTag where
  | verdictEnum
  | questionTypeEnum
  | boundedEvidenceList
  | verbatimSubstring
  | other
  deriving Repr, BEq, Inhabited

/-- Classify the predicate carried by a `VariablePredicateRequirement`, keyed off
    the `.ext` family + name strings declared in the Layer-2 ELAIP plans. -/
def classifyElaipPredicate (req : VariablePredicateRequirement) : ElaipPredicateTag :=
  match req.requiredPredicate with
  | .ext key =>
    if key.family != elaipFamily then .other
    else
      let n := key.name
      if n == "verdictEnumValid" then .verdictEnum
      else if n == "questionTypeEnum" then .questionTypeEnum
      else if n == "boundedEvidenceList" then .boundedEvidenceList
      else if n == "verbatimSubstring" then .verbatimSubstring
      else .other
  | _ => .other

/-! ## §9.2 — Tool-verdict computation (external-Python-verification slot) -/

def paperContentVar : String := "paper_content"

private def lookupRaw (state : NodeExecutionState) (var : String) : String :=
  state.getRawString var |>.getD ""

/-- Build a Tool-verdict for one (step, predicate) pair against the post-execution
    state. The four ELAIP predicates each map onto a decidable JSON check;
    everything else returns a benign PASS so the Layer-3 composite isn't poisoned
    for unrelated postconditions. -/
def toolVerdictForPredicate
    (postState : NodeExecutionState)
    (stepName : String)
    (req : VariablePredicateRequirement) : MethodVerdict :=
  if isSentinelPredicate req.requiredPredicate then
    { passed := true, applicable := false, detail := "sentinel — no JSON attribution" }
  else
    let _stepName := stepName  -- reserved: future per-step refinement
    let varName := req.varName
    let tag := classifyElaipPredicate req
    let raw := lookupRaw postState varName
    match tag with
    | .other =>
      { passed := true, applicable := false, detail := s!"no ELAIP runtime rule for ({varName}, {repr req.requiredPredicate}) — assumed N/A" }
    | .verdictEnum =>
      if raw.isEmpty then { passed := true, applicable := false, detail := s!"variable '{varName}' not bound at this step (treated as N/A)" }
      else if decideVerdictEnum raw then
        { passed := true, detail := "verdictEnumValid: every option's verdict ∈ [supported, contradicted, not_established]" }
      else { passed := false, detail := s!"verdictEnumValid violated on '{varName}' (parse failure or out-of-set verdict on at least one of A/B/C/D)" }
    | .questionTypeEnum =>
      if raw.isEmpty then { passed := true, applicable := false, detail := s!"variable '{varName}' not bound at this step (treated as N/A)" }
      else if decideQuestionTypeEnum raw then
        { passed := true, detail := "questionTypeEnum: question_type ∈ [MA-MCQ, SA-MCQ, Single-answer, Multiple-answer]" }
      else { passed := false, detail := s!"questionTypeEnum violated on '{varName}' (parse failure or out-of-set question_type)" }
    | .boundedEvidenceList =>
      if raw.isEmpty then { passed := true, applicable := false, detail := s!"variable '{varName}' not bound at this step (treated as N/A)" }
      else if decideBoundedEvidenceList raw then
        { passed := true, detail := s!"boundedEvidenceList: evidence_snippets length ≤ {maxEvidenceSnippets}" }
      else { passed := false, detail := s!"boundedEvidenceList violated on '{varName}' (parse failure, missing evidence_snippets, or length > {maxEvidenceSnippets})" }
    | .verbatimSubstring =>
      if raw.isEmpty then { passed := true, applicable := false, detail := s!"variable '{varName}' not bound at this step (treated as N/A)" }
      else
        let paper := lookupRaw postState paperContentVar
        if paper.isEmpty then
          { passed := true, applicable := false, detail := s!"verbatimSubstring: paper_content not bound — cannot run verbatim check (treated as N/A)" }
        else if decideVerbatimSubstring raw paper then
          { passed := true, detail := s!"verbatimSubstring: every evidence_snippets[i].text appears verbatim in paper_content" }
        else { passed := false, detail := s!"verbatimSubstring violated on '{varName}' (at least one snippet's text is not a substring of paper_content)" }

/-! ## §9.3 — Re-roll suggestions -/

def reRollForElaipStep (stepName : String) (failedNames : List String) : String :=
  let preds := String.intercalate ", " failedNames
  match stepName with
  | "skim_paper_overview" =>
    s!"[skim_paper_overview] predicate(s) failed: {preds}. Tighten the JSON contract: " ++
    "require explicit `title`, `abstract_summary`, `section_headings` keys; validate the saved structure parses before reply."
  | "skim_paper_structure" =>
    s!"[skim_paper_structure] predicate(s) failed: {preds}. Require all three keys " ++
    "(`title`, `abstract_summary`, `section_headings`); the section_headings list must be non-empty and reflect the order in the paper."
  | "extract_section_headings" =>
    s!"[extract_section_headings] predicate(s) failed: {preds}. Require a non-empty list of headings copied verbatim from the paper; do not paraphrase."
  | "analyze_question_stem" | "analyze_question" =>
    s!"[{stepName}] predicate(s) failed: {preds}. Require an explicit `question_type ∈ " ++
    "{Single-answer, Multiple-answer}` decision; for stems containing NOT/incorrect/wrong/false/except, set `has_negation: true` and force the evaluator to invert verdict polarity."
  | "search_keywords" | "locate_keyword_passages" =>
    s!"[{stepName}] predicate(s) failed: {preds}. Require evidence to come from passages that contain the question's keywords verbatim; reject paraphrased neighbourhoods."
  | "consolidate_evidence_snippets" | "extract_evidence" =>
    s!"[{stepName}] predicate(s) failed: {preds}. Strict 5-snippet cap; each snippet's `text` MUST be a " ++
    "verbatim substring of `paper_content` (no paraphrasing); validate each snippet's text appears in the paper before saving."
  | "verify_evidence_quality" =>
    s!"[verify_evidence_quality] predicate(s) failed: {preds}. Require structural verbatim re-check — " ++
    "compute substring presence in `paper_content` for every snippet and reject the evidence list if any fails."
  | "evaluate_options" =>
    s!"[evaluate_options] predicate(s) failed: {preds}. Pin verdict vocabulary to " ++
    "{supported, contradicted, not_established} (default to `not_established` when uncertain); evaluate each option as an INDEPENDENT judgment; recompute `selected_count` from `selected_options`."
  | "recheck_options" =>
    s!"[recheck_options] predicate(s) failed: {preds}. Tighten loop body: each iteration must keep verdicts " ++
    "in the canonical enum, only widen `selected_options` to options whose evidence is genuinely supportive, and increment `recheck_count` regardless."
  | "finalize_single_answer" =>
    s!"[finalize_single_answer] predicate(s) failed: {preds}. Output exactly one option letter from [A,B,C,D]; no prose, no parenthesised forms, no multi-letter responses."
  | "finalize_multi_answer" =>
    s!"[finalize_multi_answer] predicate(s) failed: {preds}. Output the sorted concatenation of selected option letters (e.g. \"ABC\"); reject responses that don't conform."
  | "finalize_default_answer" =>
    s!"[finalize_default_answer] predicate(s) failed: {preds}. Match the format demanded by `question_type_instruction`; produce a parseable answer string."
  | _ =>
    s!"[{stepName}] predicate(s) failed: {preds}. Tighten this step's postcondition contract: validate JSON shape, ensure required keys, default values to canonical enums."

/-! ## §9.4 — Dynamic-graph construction by name lookup -/

def findSemNodeByName (graph : SemanticWorkflowGraph) (name : String) : Option SemanticWorkflowNode :=
  graph.semanticNodes.find? fun n => n.name == some name

def mkSpecByName (graph : SemanticWorkflowGraph) (state : NodeExecutionState)
    (stepName : String) (stepId : String) : Option DynamicNodeSpec :=
  (findSemNodeByName graph stepName).map fun sem =>
    { semanticNode := sem, preExecutionState := state, postExecutionState := state,
      trajectoryStepId := stepId, trajectoryStepName := stepName, executionStatus := .completed }

/-- Build a `DynamicVerificationGraph` from `(step_name, trajectory_step_id)`
    entries. Names that don't resolve in the graph are silently dropped. -/
def buildDynamicGraphByName (graph : SemanticWorkflowGraph) (state : NodeExecutionState)
    (entries : List (String × String)) : DynamicVerificationGraph :=
  let specs : List DynamicNodeSpec := entries.filterMap (fun (name, sid) => mkSpecByName graph state name sid)
  { semanticWorkflowGraph := graph, dynamicNodeSpecs := specs,
    conditionalNodeSpecs := [], loopNodeSpecs := [], initialExecutionState := state }

/-- Build a `StepIdMap` from the same entries. -/
def buildStepIdMapByName (graph : SemanticWorkflowGraph) (entries : List (String × String)) : StepIdMap :=
  StepIdMap.ofList (entries.filterMap fun (name, sid) =>
    (findSemNodeByName graph name).map fun sem => (sid, sem.id))

/-! ## §9.5 — Public bundling + convenience runner -/

/-- Build `PerStepAnalysisRules` from a single post-execution state snapshot. -/
def rulesFromState (postState : NodeExecutionState) : PerStepAnalysisRules :=
  { externalToolVerdict := toolVerdictForPredicate postState
    reRollSuggestion    := reRollForElaipStep }

/-- One-line per-instance runner. Renders §7's `renderFullReport`, which now embeds
    §5's three-channel unified report (variable · information · graph). The
    semantic graph and goal spec are derived from `dynGraph` (the goal spec is
    embedded in the graph). -/
def runElaipAnalysis
    (dynGraph : DynamicVerificationGraph)
    (stepIdMap : StepIdMap)
    (eventLogPath : System.FilePath)
    (postState : NodeExecutionState)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (llmInjections : List PerPredicateLLMInjection := [])
    (banner : String := "PER-STEP MOVE ANALYSIS — ELAIP-Bench") : IO Unit := do
  IO.println "╔══════════════════════════════════════════════════════════════════════╗"
  IO.println s!"║  {banner}"
  IO.println "╚══════════════════════════════════════════════════════════════════════╝"
  let trace ← ExecutionTrace.loadEventLog eventLogPath
  IO.println s!"event log: {eventLogPath} — {trace.length} typed event(s)"
  IO.println ""
  let rules    := rulesFromState postState
  let analyses := analyzeAllSteps dynGraph trace stepIdMap rules llmInjections
  IO.println (renderFullReport dynGraph trace analyses goalSpec stepIdMap banner)

end AgenticKernel.Dyn.ElaipBench
