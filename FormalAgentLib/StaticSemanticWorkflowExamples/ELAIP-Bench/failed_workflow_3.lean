/- ELAIP-Bench Layer-2 verification (Solution-2 / NEW idiom), authored from the
   ELAIP `failed_workflow_3` Layer-2 IR (`elaipbench_layer2_v2_ir/failed_workflow_3_layer2_v2.ir.json`)
   per `LAYER2_NEW_FORMAT.md`. A "worst" plan.

   This plan grounds evidence (boundedEvidenceList + verbatimSubstring) and has an
   evidence-quality node, but it then judges options as FOUR fragmented per-option
   nodes (`evaluate_A..D`) and a `recheck_summary` — it NEVER forms a single
   consolidated, verdict-validated `option_judgment` (no `verdictEnumValid` node).
   So the `options_judged` sub-goal has no contributor (coverage gap), and the
   final answer step, which requires a consolidated verdict, blocks on the missing
   `option_judgment` information atom ⇒ `infoSound = false`. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.failed_workflow_3_layer2_new

namespace failed_workflow_3_layer2_v2.SG
  def paper_comprehended : SubGoalName := ⟨"paper_comprehended"⟩
  def question_analyzed  : SubGoalName := ⟨"question_analyzed"⟩
  def evidence_grounded  : SubGoalName := ⟨"evidence_grounded"⟩
  def evidence_verified  : SubGoalName := ⟨"evidence_verified"⟩
  def options_judged     : SubGoalName := ⟨"options_judged"⟩
  def answer_finalized   : SubGoalName := ⟨"answer_finalized"⟩
end failed_workflow_3_layer2_v2.SG
open failed_workflow_3_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: elaipbench_agent (failed_workflow_3 / "worst" plan) -- new
Goal: Answer an academic paper question based on the provided passage
Nodes: 13 (semantic pipeline), Entry: 0, Exit: [12]

KEY CHARACTERISTIC (worst plan): NO consolidated verdict-validated judgement.
Four fragmented evaluate_A..D + a recheck_summary, but no `verdictEnumValid`
`option_judgment` ⇒ `options_judged` uncovered (coverage gap) AND the finalize
step blocks on the missing `option_judgment` atom ⇒ infoSound = FALSE.
================================================================================
-/

/- ===== STEP 1: WORKFLOW GRAPH ===== -/

def bp3_nodeId0  : NodeId := ⟨0⟩
def bp3_nodeId1  : NodeId := ⟨1⟩
def bp3_nodeId2  : NodeId := ⟨2⟩
def bp3_nodeId3  : NodeId := ⟨3⟩
def bp3_nodeId4  : NodeId := ⟨4⟩
def bp3_nodeId5  : NodeId := ⟨5⟩
def bp3_nodeId6  : NodeId := ⟨6⟩
def bp3_nodeId7  : NodeId := ⟨7⟩
def bp3_nodeId8  : NodeId := ⟨8⟩
def bp3_nodeId9  : NodeId := ⟨9⟩
def bp3_nodeId10 : NodeId := ⟨10⟩
def bp3_nodeId11 : NodeId := ⟨11⟩
def bp3_nodeId12 : NodeId := ⟨12⟩

def bp3_node0 : WorkflowNode := {
  id := bp3_nodeId0, name := some "skim_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Skim the paper and produce a JSON overview."
}
def bp3_semNode0 : SemanticWorkflowNode := {
  baseNode := bp3_node0
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "paper_overview", varIsValidJson "paper_overview"]
  infoRequires := [info "paper_text"]
  producesContextInfo := [info "paper_overview", info "paper_text"]
  graphContributions := [paper_comprehended]
  graphImplicitRetries := [paper_comprehended]
}

def bp3_node1 : WorkflowNode := {
  id := bp3_nodeId1, name := some "extract_section_headings"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Extract the main section headings as a JSON outline."
}
def bp3_semNode1 : SemanticWorkflowNode := {
  baseNode := bp3_node1
  precondVariables := [varNameExists "paper_overview"]
  postcondVariables := [varIsNonEmptyString "section_headings", varIsValidJson "section_headings"]
  infoRequires := [info "paper_overview"]
  producesContextInfo := [info "section_headings"]
  graphContributions := [paper_comprehended]
}

def bp3_node2 : WorkflowNode := {
  id := bp3_nodeId2, name := some "extract_keywords"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Extract search keywords from the question."
}
def bp3_semNode2 : SemanticWorkflowNode := {
  baseNode := bp3_node2
  precondVariables := [varIsNonEmptyString "question"]
  postcondVariables := [varIsNonEmptyString "question_keywords"]
  infoRequires := [info "question_text"]
  producesContextInfo := [info "question_keywords"]
  graphContributions := [question_analyzed]
  graphImplicitRetries := [question_analyzed]
}

def bp3_node3 : WorkflowNode := {
  id := bp3_nodeId3, name := some "classify_question_type"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type", .TString⟩], writes := []
  llmInstruction := some "Classify the question type."
}
def bp3_semNode3 : SemanticWorkflowNode := {
  baseNode := bp3_node3
  precondVariables := [varIsNonEmptyString "question"]
  postcondVariables := [varIsNonEmptyString "question_class"]
  infoRequires := [info "question_text"]
  producesContextInfo := [info "question_class"]
  graphContributions := [question_analyzed]
}

def bp3_node4 : WorkflowNode := {
  id := bp3_nodeId4, name := some "note_negation"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Flag whether the question stem contains a negation."
}
def bp3_semNode4 : SemanticWorkflowNode := {
  baseNode := bp3_node4
  precondVariables := [varIsNonEmptyString "question"]
  postcondVariables := [varIsNonEmptyString "negation_flag"]
  infoRequires := [info "question_text"]
  producesContextInfo := [info "negation_flag"]
  graphContributions := [question_analyzed]
}

def bp3_node5 : WorkflowNode := {
  id := bp3_nodeId5, name := some "gather_evidence"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Gather a bounded (≤5) ranked evidence set, each snippet verbatim from the paper. Emit JSON."
}
def bp3_semNode5 : SemanticWorkflowNode := {
  baseNode := bp3_node5
  precondVariables := [varNameExists "question_keywords", varIsNonEmptyString "paper_content"]
  postcondVariables := [
    varIsNonEmptyString "evidence",
    varIsValidJson "evidence",
    varExt "evidence" (.makePredicateKey "user.elaip" "boundedEvidenceList" []),
    varExt "evidence" (.makePredicateKey "user.elaip" "verbatimSubstring" [])
  ]
  infoRequires := [info "question_keywords", info "paper_text"]
  producesContextInfo := [info "evidence"]
  graphContributions := [evidence_grounded]
  graphImplicitRetries := [evidence_grounded]
}

def bp3_node6 : WorkflowNode := {
  id := bp3_nodeId6, name := some "verify_evidence_quality"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Sanity-check the evidence set. Emit a quality note."
}
def bp3_semNode6 : SemanticWorkflowNode := {
  baseNode := bp3_node6
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "evidence_quality"]
  infoRequires := [info "evidence"]
  producesContextInfo := [info "evidence_quality"]
  graphContributions := [evidence_verified]
  graphVerifications := [evidence_grounded]
}

def bp3_node7 : WorkflowNode := {
  id := bp3_nodeId7, name := some "evaluate_A"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Judge option A in isolation against the evidence and negation flag."
}
def bp3_semNode7 : SemanticWorkflowNode := {
  baseNode := bp3_node7
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "judgment_A"]
  infoRequires := [info "question_text", info "evidence", info "negation_flag"]
  producesContextInfo := [info "judgment_A"]
}

def bp3_node8 : WorkflowNode := {
  id := bp3_nodeId8, name := some "evaluate_B"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Judge option B in isolation against the evidence."
}
def bp3_semNode8 : SemanticWorkflowNode := {
  baseNode := bp3_node8
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "judgment_B"]
  infoRequires := [info "evidence"]
  producesContextInfo := [info "judgment_B"]
}

def bp3_node9 : WorkflowNode := {
  id := bp3_nodeId9, name := some "evaluate_C"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Judge option C in isolation against the evidence."
}
def bp3_semNode9 : SemanticWorkflowNode := {
  baseNode := bp3_node9
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "judgment_C"]
  infoRequires := [info "evidence"]
  producesContextInfo := [info "judgment_C"]
}

def bp3_node10 : WorkflowNode := {
  id := bp3_nodeId10, name := some "evaluate_D"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Judge option D in isolation against the evidence."
}
def bp3_semNode10 : SemanticWorkflowNode := {
  baseNode := bp3_node10
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "judgment_D"]
  infoRequires := [info "evidence"]
  producesContextInfo := [info "judgment_D"]
}

-- recheck without ever forming a consolidated verdict-validated option_judgment.
def bp3_node11 : WorkflowNode := {
  id := bp3_nodeId11, name := some "recheck_options"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Summarise the four per-option judgements (free text); no consolidated verdict object is produced."
}
def bp3_semNode11 : SemanticWorkflowNode := {
  baseNode := bp3_node11
  precondVariables := [varNameExists "judgment_A", varNameExists "judgment_B", varNameExists "judgment_C", varNameExists "judgment_D"]
  postcondVariables := [varIsNonEmptyString "recheck_summary"]
  infoRequires := [info "judgment_A", info "judgment_B", info "judgment_C", info "judgment_D"]
  producesContextInfo := [info "recheck_summary"]
  -- NOTE: no graphContributions := [options_judged]; no verdictEnumValid ext.
}

def bp3_node12 : WorkflowNode := {
  id := bp3_nodeId12, name := some "finalize_answer"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Produce the final answer. A sound finalisation needs a consolidated verdict (option_judgment), which this plan never formed."
}
def bp3_semNode12 : SemanticWorkflowNode := {
  baseNode := bp3_node12
  precondVariables := [varNameExists "recheck_summary"]
  postcondVariables := [varIsNonEmptyString "final_response"]
  -- requires a consolidated verdict that NO node produces ⇒ blocked:
  infoRequires := [info "option_judgment", info "recheck_summary"]
  producesContextInfo := [info "final_response"]
  graphContributions := [answer_finalized]
}

def bp3Graph : WorkflowGraph := {
  nodes := [bp3_node0, bp3_node1, bp3_node2, bp3_node3, bp3_node4, bp3_node5, bp3_node6, bp3_node7, bp3_node8, bp3_node9, bp3_node10, bp3_node11, bp3_node12]
  edges := [
    .seqEdge bp3_nodeId0 bp3_nodeId1,
    .seqEdge bp3_nodeId1 bp3_nodeId2,
    .seqEdge bp3_nodeId2 bp3_nodeId3,
    .seqEdge bp3_nodeId3 bp3_nodeId4,
    .seqEdge bp3_nodeId4 bp3_nodeId5,
    .seqEdge bp3_nodeId5 bp3_nodeId6,
    .seqEdge bp3_nodeId6 bp3_nodeId7,
    .seqEdge bp3_nodeId7 bp3_nodeId8,
    .seqEdge bp3_nodeId8 bp3_nodeId9,
    .seqEdge bp3_nodeId9 bp3_nodeId10,
    .seqEdge bp3_nodeId10 bp3_nodeId11,
    .seqEdge bp3_nodeId11 bp3_nodeId12
  ]
  entry := bp3_nodeId0
  exits := [bp3_nodeId12]
  parameters := [⟨"question", .TString⟩, ⟨"paper_content", .TString⟩, ⟨"question_type_instruction", .TString⟩, ⟨"question_type", .TString⟩]
}

/- ===== STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS ===== -/

#eval do
  let g := bp3Graph
  for node in g.nodes do
    let name := node.name.getD "(unnamed)"
    IO.println s!"\n--- Node {node.id}: \"{name}\" [{repr node.stepType}] ---"
    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"

/- ===== STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS ===== -/

#eval bp3Graph.allWritesConsistent
#eval bp3Graph.allReadResolvable
#eval bp3Graph.edgesValid
#eval bp3Graph.entryNodeValid
#eval bp3Graph.exitNodesValid
#eval bp3Graph.allExitsReachable
#eval bp3Graph.noOrphanNodes

/- ===== STEP 4-5: THEOREMS (Layer 1 -- structural; all PASS) ===== -/

theorem bp3_writesConsistent : bp3Graph.allWritesConsistent = true := by native_decide
theorem bp3_readsResolvable : bp3Graph.allReadResolvable = true := by native_decide
theorem bp3_edgesValid : bp3Graph.edgesValid = true := by native_decide
theorem bp3_entryValid : bp3Graph.entryNodeValid = true := by native_decide
theorem bp3_exitsValid : bp3Graph.exitNodesValid = true := by native_decide
theorem bp3_exitsReachable : bp3Graph.allExitsReachable = true := by native_decide
theorem bp3_noOrphans : bp3Graph.noOrphanNodes = true := by native_decide

/- ===== STEP 6: PARAMETERS + GOAL SPEC + SEMANTIC GRAPH ===== -/

def bp3_paramNode : SemanticWorkflowNode := {
  baseNode := { id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varNameExists "question", varNameExists "paper_content",
    varNameExists "question_type_instruction", varNameExists "question_type",
    varIsNonEmptyString "question", varIsNonEmptyString "paper_content",
    varIsNonEmptyString "question_type_instruction", varIsNonEmptyString "question_type"
  ]
  producesVariableInfo := [
    varInfo "paper_content" ["paper_text"],
    varInfo "question" ["question_text"],
    varInfo "question_type_instruction" ["question_type_spec"]
  ]
}

def failed_workflow_3_goalSpec : GoalSpecification := {
  originalGoal := "Answer an academic paper question based on the provided passage"
  subGoals := [
    { name := paper_comprehended
      variableName := "paper_overview"
      requiredPredicate := .isNonEmptyString
      description := "Paper skimmed and section headings extracted."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := question_analyzed
      variableName := "question_keywords"
      requiredPredicate := .isNonEmptyString
      description := "Keywords, type and negation extracted from the question."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := evidence_grounded
      variableName := "evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence is bounded + verbatim-grounded and verified downstream."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.verificationCoverage] },
    { name := evidence_verified
      variableName := "evidence_quality"
      requiredPredicate := .isNonEmptyString
      description := "An evidence-quality node verifies the grounded evidence."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := options_judged
      variableName := "option_judgment"
      requiredPredicate := .isNonEmptyString
      description := "Should be a single verdict-validated (verdictEnumValid) consolidated judgement — but this plan only produces fragmented per-option judgements and a free-text recheck_summary, so NO node contributes options_judged (coverage gap)."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack] },
    { name := answer_finalized
      variableName := "final_response"
      requiredPredicate := .isNonEmptyString
      description := "A final response is produced (but it rests on no consolidated verdict)."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] }
  ]
}

def failed_workflow_3_layer2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := bp3Graph
  paramNode := bp3_paramNode
  semanticNodes := [bp3_semNode0, bp3_semNode1, bp3_semNode2, bp3_semNode3, bp3_semNode4, bp3_semNode5, bp3_semNode6, bp3_semNode7, bp3_semNode8, bp3_semNode9, bp3_semNode10, bp3_semNode11, bp3_semNode12]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := failed_workflow_3_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report. This "worst" plan grounds + verifies evidence but never forms a
   consolidated verdict ⇒ options_judged uncovered (coverage gap) AND the finalize
   step blocks on the missing `option_judgment` atom ⇒ infoSound = FALSE. -/
#eval IO.println (failed_workflow_3_layer2SemanticGraph.verifyWorkflowReport (label := "failed_workflow_3"))

theorem failed_workflow_3_hoare_sound : (failed_workflow_3_layer2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem failed_workflow_3_info_unsound : (failed_workflow_3_layer2SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

def bp3_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.failed_workflow_3_layer2_new
