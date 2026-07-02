import Lean
import Mathlib
import AgentVerifier.DynamicVerification.PerStepView

/-!
# Section 10 — JSON face of the unified report

Machine-readable serialization of the §5 `DynamicUnifiedVerificationReport` plus
the §7 per-step analyses, mirroring Layer-2's JSON face
(`VerificationJsonOutput.layer2ToJson` / `UnifiedVerificationReport.toJson`).

The top-level entry `layer3ToJson` is what a `lean_query --layer 3` driver
calls; the schema reports each of the three channels (variable / information /
graph) and coverage, plus the per-step three-method diagnosis.
-/

namespace AgenticKernel
namespace Dyn

open Lean (Json)

/-! ## §10.1 — Channel helpers -/

private def boolJ (b : Bool) : Json := Json.bool b

private def varVerdictStr : DynamicVerificationGraphVerifyResult → String
  | .allVerified => "allVerified"
  | .someNodesFailed _ => "someNodesFailed"
  | .hasPending _ => "hasPending"
  | .structuralMismatch _ => "structuralMismatch"

private def infoListJson (is : List InformationPredicate) : Json :=
  Json.arr ((is.map fun i => Json.str i.name)).toArray

private def infoNodeJson (r : DynamicNodeInfoFlowResult) : Json :=
  Json.mkObj [
    ("node_id",      Json.num r.nodeId.val),
    ("executed",     boolJ r.executed),
    ("passed",       boolJ r.passed),
    ("required",     infoListJson r.required),
    ("via_variable", infoListJson r.satisfiedViaVariable),
    ("via_context",  infoListJson r.satisfiedViaContext),
    ("starved",      infoListJson r.starved),
    ("absent",       infoListJson r.absent) ]

private def methodTag : VerificationMethod → String
  | .leanSymbolicVerification => "lean"
  | .externalToolVerification t => s!"py:{t}"
  | .llmJudgeVerification => "llm"

private def graphPredJson (r : DynamicGraphPredicateResult) : Json :=
  Json.mkObj [
    ("label",         Json.str r.shortLabel),
    ("method",        Json.str (methodTag r.method)),
    ("passed",        boolJ r.passed),
    ("required",      boolJ r.required),
    ("informational", boolJ r.informational),
    ("detail",        Json.str r.detail) ]

private def subGoalJson (v : DynamicSubGoalVerification) : Json :=
  Json.mkObj [
    ("name",            Json.str v.subGoal.name.val),
    ("variable_name",   Json.str v.subGoal.variableName),
    ("passed",          boolJ v.passed),
    ("variable_passed", boolJ v.variablePassed),
    ("move_falsified",  boolJ v.moveFalsified),
    ("pending",         boolJ v.isPending),
    ("graph_predicates", Json.arr (v.graphPredicateResults.map graphPredJson).toArray) ]

/-! ## §10.2 — Per-step helpers -/

private def floatStrJson : Option Float → Json
  | none => Json.null
  | some c => Json.str (toString c)

private def methodVerdictJson : Option MethodVerdict → Json
  | none => Json.null
  | some mv => Json.mkObj [
      ("passed",     boolJ mv.passed),
      ("detail",     Json.str mv.detail),
      ("confidence", floatStrJson mv.confidence) ]

private def predMoveVerdictStr : PredicateMoveVerdict → String
  | .confirmed => "confirmed"
  | .falsified _ => "falsified"
  | .sentinel => "sentinel"

private def predMoveRootCause : PredicateMoveVerdict → Json
  | .falsified rc => Json.str rc
  | _ => Json.null

private def predMoveJson (pa : PredicateMoveAnalysis) : Json :=
  Json.mkObj [
    ("var_name",     Json.str pa.predicate.varName),
    ("predicate",    Json.str s!"{repr pa.predicate.requiredPredicate}"),
    ("is_sentinel",  boolJ pa.isSentinel),
    ("lean_verdict", methodVerdictJson pa.leanVerdict),
    ("tool_verdict", methodVerdictJson pa.toolVerdict),
    ("llm_verdict",  methodVerdictJson pa.llmVerdict),
    ("composite",    Json.str (predMoveVerdictStr pa.composite)),
    ("root_cause",   predMoveRootCause pa.composite) ]

private def stepVerdictStr : StepMoveVerdict → String
  | .confirmed => "confirmed"
  | .falsified _ _ => "falsified"
  | .unknown => "unknown"

private def stepReRoll : StepMoveVerdict → Json
  | .falsified _ rr => Json.str rr
  | _ => Json.null

def StepMoveAnalysis.toJson (a : StepMoveAnalysis) : Json :=
  Json.mkObj [
    ("step_id",        Json.num a.stepId.val),
    ("step_name",      Json.str a.stepName),
    ("precond_held",   boolJ a.precondHeld),
    ("trace_summary",  Json.str a.traceSummary),
    ("composite",      Json.str (stepVerdictStr a.stepComposite)),
    ("reroll",         stepReRoll a.stepComposite),
    ("postconds",      Json.arr (a.postcondVerdicts.map predMoveJson).toArray) ]

/-! ## §10.3 — The unified report → JSON -/

def DynamicUnifiedVerificationReport.toJson (r : DynamicUnifiedVerificationReport) : Json :=
  Json.mkObj [
    ("label",     Json.str r.label),
    ("all_sound", boolJ r.allSound),
    ("channels", Json.mkObj [
      ("variable", Json.mkObj [
        ("sound",   boolJ r.hoareSound),
        ("verdict", Json.str (varVerdictStr r.variable_)) ]),
      ("information", Json.mkObj [
        ("sound",  boolJ r.infoSound),
        ("passed", boolJ r.info.passed),
        ("starved_node_count", Json.num r.info.starvedNodes.length),
        ("nodes",  Json.arr (r.info.nodeResults.map infoNodeJson).toArray) ]),
      ("graph", Json.mkObj [
        ("sound", boolJ r.graphSound) ]),
      ("coverage", Json.mkObj [
        ("sound",     boolJ r.coverageSound),
        ("verdict",   Json.str r.coverage.overallResult.describe),
        ("sub_goals", Json.arr (r.coverage.subGoalVerifications.map subGoalJson).toArray) ]) ]) ]

/-! ## §10.4 — Top-level layer-3 JSON entry -/

/-- The full Layer-3 JSON: the unified three-channel report + the per-step
    three-method diagnosis + the formatted text. This is the analogue of the
    old `layer3VerificationToJson`. -/
def layer3ToJson
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (analyses : List StepMoveAnalysis)
    (goalSpec : GoalSpecification := dynGraph.semanticWorkflowGraph.goalSpec)
    (unifiedReg : UnifiedDynamicPredicateRegistry := defaultUnifiedDynamicRegistry)
    (externalVerificationResults : List ExternalVerificationResult := [])
    (graphInjected : List GraphExternalVerificationResult := [])
    (semanticJudgments : List (String × LLMJudgementResult) := [])
    (infoInjections : List DynamicInfoFlowInjection := [])
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    (label : String := "") : Json :=
  -- Reconcile the unified report with the per-step three-method composites (§7) so
  -- `unified.all_sound` and the coverage channel reflect FALSIFIED moves, not just
  -- the structural channels.
  let report := reconcileUnifiedWithMoves
    (verifyDynamicWorkflow dynGraph trace goalSpec unifiedReg
      externalVerificationResults graphInjected semanticJudgments infoInjections stepIdMap label)
    analyses
  Json.mkObj [
    ("layer",          Json.num 3),
    ("version",        Json.str "v2"),
    ("unified",        report.toJson),
    ("per_step",       Json.arr (analyses.map StepMoveAnalysis.toJson).toArray),
    ("formatted_text", Json.str (formatDynamicUnifiedReport report)) ]

end Dyn
end AgenticKernel
