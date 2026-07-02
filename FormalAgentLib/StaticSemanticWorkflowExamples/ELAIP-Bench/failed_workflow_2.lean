/- ELAIP-Bench Layer-2 verification (Solution-2 / NEW idiom), authored from the
   ELAIP `failed_workflow_2` Layer-2 IR (`elaipbench_layer2_v2_ir/failed_workflow_2_layer2_v2.ir.json`)
   per `LAYER2_NEW_FORMAT.md`. A "worst" plan.

   This plan actually grounds and verifies its evidence (it has a consolidated
   `evidence` node with `boundedEvidenceList` + `verbatimSubstring`, plus an
   evidence-quality node), so its COVERAGE is full — but its keyword search step
   `search_keyword_in_paper` is BROKEN: in the IR it has `save_as = None` (writes
   nothing) and reads a `{{keyword}}` for-each loop variable that is never bound
   by a producing node. Modelled faithfully, that node's `keyword` information
   atom is produced by NO semantic node ⇒ the node is blocked ⇒ `infoSound = false`.
   The failure here is a dangling/disconnected step, not missing evidence. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.failed_workflow_2_layer2_new

namespace failed_workflow_2_layer2_v2.SG
  def paper_comprehended : SubGoalName := ⟨"paper_comprehended"⟩
  def question_analyzed  : SubGoalName := ⟨"question_analyzed"⟩
  def evidence_grounded  : SubGoalName := ⟨"evidence_grounded"⟩
  def evidence_verified  : SubGoalName := ⟨"evidence_verified"⟩
  def options_judged     : SubGoalName := ⟨"options_judged"⟩
  def answer_finalized   : SubGoalName := ⟨"answer_finalized"⟩
end failed_workflow_2_layer2_v2.SG
open failed_workflow_2_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: elaipbench_agent (failed_workflow_2 / "worst" plan) -- new
Goal: Answer an academic paper question based on the provided passage
Nodes: 9 (semantic pipeline), Entry: 0, Exit: [8]

KEY CHARACTERISTIC (worst plan): a BROKEN keyword-search step
(`search_keyword_in_paper`, IR save_as=None) consumes an unbound `{{keyword}}`
loop variable and writes nothing ⇒ infoSound = FALSE. Evidence grounding/
verification is otherwise present, so coverage stays full.
================================================================================
-/

/- ===== STEP 1: WORKFLOW GRAPH ===== -/

def bp2_nodeId0 : NodeId := ⟨0⟩
def bp2_nodeId1 : NodeId := ⟨1⟩
def bp2_nodeId2 : NodeId := ⟨2⟩
def bp2_nodeId3 : NodeId := ⟨3⟩
def bp2_nodeId4 : NodeId := ⟨4⟩
def bp2_nodeId5 : NodeId := ⟨5⟩
def bp2_nodeId6 : NodeId := ⟨6⟩
def bp2_nodeId7 : NodeId := ⟨7⟩
def bp2_nodeId8 : NodeId := ⟨8⟩

def bp2_node0 : WorkflowNode := {
  id := bp2_nodeId0, name := some "skim_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Skim the paper and produce a free-text outline."
}
def bp2_semNode0 : SemanticWorkflowNode := {
  baseNode := bp2_node0
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "paper_outline"]
  infoRequires := [info "paper_text"]
  producesContextInfo := [info "paper_outline", info "paper_text"]
  graphContributions := [paper_comprehended]
  graphImplicitRetries := [paper_comprehended]
}

def bp2_node1 : WorkflowNode := {
  id := bp2_nodeId1, name := some "section_headings"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Extract the main section headings as a JSON outline."
}
def bp2_semNode1 : SemanticWorkflowNode := {
  baseNode := bp2_node1
  precondVariables := [varNameExists "paper_outline"]
  postcondVariables := [varIsNonEmptyString "section_headings", varIsValidJson "section_headings"]
  infoRequires := [info "paper_outline"]
  producesContextInfo := [info "section_headings"]
  graphContributions := [paper_comprehended]
}

def bp2_node2 : WorkflowNode := {
  id := bp2_nodeId2, name := some "extract_keywords"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Analyze the question and emit a JSON analysis with the typed question category."
}
def bp2_semNode2 : SemanticWorkflowNode := {
  baseNode := bp2_node2
  precondVariables := [varIsNonEmptyString "question"]
  postcondVariables := [
    varIsNonEmptyString "question_analysis",
    varIsValidJson "question_analysis",
    varExt "question_analysis" (.makePredicateKey "user.elaip" "questionTypeEnum" [])
  ]
  infoRequires := [info "question_text", info "question_type_spec", info "section_headings"]
  producesContextInfo := [info "question_analysis"]
  graphContributions := [question_analyzed]
  graphImplicitRetries := [question_analyzed]
}

def bp2_node3 : WorkflowNode := {
  id := bp2_nodeId3, name := some "classify_question_type"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Classify the question type from the analysis."
}
def bp2_semNode3 : SemanticWorkflowNode := {
  baseNode := bp2_node3
  precondVariables := [varNameExists "question_analysis"]
  postcondVariables := [varIsNonEmptyString "type_classification"]
  infoRequires := [info "question_analysis"]
  producesContextInfo := [info "type_classification"]
  graphContributions := [question_analyzed]
}

-- BROKEN step: IR save_as=None (writes nothing), reads an unbound {{keyword}} loop var.
def bp2_node4 : WorkflowNode := {
  id := bp2_nodeId4, name := some "search_keyword_in_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Search the paper for the keyword \"{{keyword}}\" — but {{keyword}} is an unbound for-each loop variable and the step saves nothing."
}
def bp2_semNode4 : SemanticWorkflowNode := {
  baseNode := bp2_node4
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := []                              -- writes nothing (save_as=None)
  infoRequires := [info "keyword", info "paper_text"]  -- `keyword` produced by NO node ⇒ blocked
  producesContextInfo := []
  graphContributions := []
}

def bp2_node5 : WorkflowNode := {
  id := bp2_nodeId5, name := some "consolidate_evidence"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Consolidate a bounded (≤5) ranked evidence set, each snippet verbatim from the paper. Emit JSON."
}
def bp2_semNode5 : SemanticWorkflowNode := {
  baseNode := bp2_node5
  precondVariables := [varNameExists "question_analysis"]
  postcondVariables := [
    varIsNonEmptyString "evidence",
    varIsValidJson "evidence",
    varExt "evidence" (.makePredicateKey "user.elaip" "boundedEvidenceList" []),
    varExt "evidence" (.makePredicateKey "user.elaip" "verbatimSubstring" [])
  ]
  infoRequires := [info "question_analysis", info "paper_text"]
  producesContextInfo := [info "evidence"]
  graphContributions := [evidence_grounded]
  graphImplicitRetries := [evidence_grounded]
}

def bp2_node6 : WorkflowNode := {
  id := bp2_nodeId6, name := some "verify_evidence_quality"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Sanity-check the evidence set before judgement. Emit a quality note."
}
def bp2_semNode6 : SemanticWorkflowNode := {
  baseNode := bp2_node6
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "evidence_quality"]
  infoRequires := [info "evidence"]
  producesContextInfo := [info "evidence_quality"]
  graphContributions := [evidence_verified]
  graphVerifications := [evidence_grounded]
}

def bp2_node7 : WorkflowNode := {
  id := bp2_nodeId7, name := some "evaluate_options"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Evaluate options A-D against the consolidated evidence with a recheck pass. Emit a JSON verdict."
}
def bp2_semNode7 : SemanticWorkflowNode := {
  baseNode := bp2_node7
  precondVariables := [varNameExists "evidence", varNameExists "evidence_quality"]
  postcondVariables := [
    varIsNonEmptyString "option_judgment",
    varIsValidJson "option_judgment",
    varExt "option_judgment" (.makePredicateKey "user.elaip" "verdictEnumValid" [])
  ]
  infoRequires := [info "question_text", info "question_analysis", info "evidence", info "evidence_quality"]
  producesContextInfo := [info "option_judgment"]
  graphContributions := [options_judged]
  graphImplicitRetries := [options_judged]
}

def bp2_node8 : WorkflowNode := {
  id := bp2_nodeId8, name := some "finalize_answer"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Produce the final answer (multi/single-answer branch) from the verdict."
}
def bp2_semNode8 : SemanticWorkflowNode := {
  baseNode := bp2_node8
  precondVariables := [varNameExists "option_judgment"]
  postcondVariables := [varIsNonEmptyString "final_response"]
  infoRequires := [info "option_judgment"]
  producesContextInfo := [info "final_response"]
  graphContributions := [answer_finalized]
}

def bp2Graph : WorkflowGraph := {
  nodes := [bp2_node0, bp2_node1, bp2_node2, bp2_node3, bp2_node4, bp2_node5, bp2_node6, bp2_node7, bp2_node8]
  edges := [
    .seqEdge bp2_nodeId0 bp2_nodeId1,
    .seqEdge bp2_nodeId1 bp2_nodeId2,
    .seqEdge bp2_nodeId2 bp2_nodeId3,
    .seqEdge bp2_nodeId3 bp2_nodeId4,
    .seqEdge bp2_nodeId4 bp2_nodeId5,
    .seqEdge bp2_nodeId5 bp2_nodeId6,
    .seqEdge bp2_nodeId6 bp2_nodeId7,
    .seqEdge bp2_nodeId7 bp2_nodeId8
  ]
  entry := bp2_nodeId0
  exits := [bp2_nodeId8]
  parameters := [⟨"question", .TString⟩, ⟨"paper_content", .TString⟩, ⟨"question_type_instruction", .TString⟩, ⟨"question_type", .TString⟩]
}

/- ===== STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS ===== -/

#eval do
  let g := bp2Graph
  for node in g.nodes do
    let name := node.name.getD "(unnamed)"
    IO.println s!"\n--- Node {node.id}: \"{name}\" [{repr node.stepType}] ---"
    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"

/- ===== STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS ===== -/

#eval bp2Graph.allWritesConsistent
#eval bp2Graph.allReadResolvable
#eval bp2Graph.edgesValid
#eval bp2Graph.entryNodeValid
#eval bp2Graph.exitNodesValid
#eval bp2Graph.allExitsReachable
#eval bp2Graph.noOrphanNodes

/- ===== STEP 4-5: THEOREMS (Layer 1 -- structural; all PASS) ===== -/

theorem bp2_writesConsistent : bp2Graph.allWritesConsistent = true := by native_decide
theorem bp2_readsResolvable : bp2Graph.allReadResolvable = true := by native_decide
theorem bp2_edgesValid : bp2Graph.edgesValid = true := by native_decide
theorem bp2_entryValid : bp2Graph.entryNodeValid = true := by native_decide
theorem bp2_exitsValid : bp2Graph.exitNodesValid = true := by native_decide
theorem bp2_exitsReachable : bp2Graph.allExitsReachable = true := by native_decide
theorem bp2_noOrphans : bp2Graph.noOrphanNodes = true := by native_decide

/- ===== STEP 6: PARAMETERS + GOAL SPEC + SEMANTIC GRAPH ===== -/

def bp2_paramNode : SemanticWorkflowNode := {
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

def failed_workflow_2_goalSpec : GoalSpecification := {
  originalGoal := "Answer an academic paper question based on the provided passage"
  subGoals := [
    { name := paper_comprehended
      variableName := "paper_outline"
      requiredPredicate := .isNonEmptyString
      description := "Paper outlined and section headings extracted."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := question_analyzed
      variableName := "question_analysis"
      requiredPredicate := .isNonEmptyString
      description := "Question analysed and typed (questionTypeEnum)."
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
      description := "Per-option verdicts (verdictEnumValid) with a recheck loop."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack] },
    { name := answer_finalized
      variableName := "final_response"
      requiredPredicate := .isNonEmptyString
      description := "A final response is produced."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] }
  ]
}

def failed_workflow_2_layer2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := bp2Graph
  paramNode := bp2_paramNode
  semanticNodes := [bp2_semNode0, bp2_semNode1, bp2_semNode2, bp2_semNode3, bp2_semNode4, bp2_semNode5, bp2_semNode6, bp2_semNode7, bp2_semNode8]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := failed_workflow_2_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report. This "worst" plan is variable-sound and well-covered but
   INFO-UNSOUND: the dangling keyword-search step blocks on an unbound `keyword`. -/
#eval IO.println (failed_workflow_2_layer2SemanticGraph.verifyWorkflowReport (label := "failed_workflow_2"))

theorem failed_workflow_2_hoare_sound : (failed_workflow_2_layer2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem failed_workflow_2_info_unsound : (failed_workflow_2_layer2SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

def bp2_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.failed_workflow_2_layer2_new
