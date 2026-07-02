/- ELAIP-Bench Layer-2 verification (Solution-2 / NEW idiom), authored from the
   ELAIP `failed_workflow_1` Layer-2 IR (`elaipbench_layer2_v2_ir/failed_workflow_1_layer2_v2.ir.json`)
   per `LAYER2_NEW_FORMAT.md`. This is a "worst" plan: it is structurally and
   Hoare-sound but FAILS the information-flow channel.

   Failure mode (faithful to the IR): evidence is gathered by a keyword search
   (`keyword_hits`) that is appended into an `evidence_snippets` buffer via plain
   `set_variable` scaffolding — never consolidated by a grounded LLM evidence node
   (no `boundedEvidenceList` / `verbatimSubstring` ext) and never verified. The
   four fragmented per-option judgements (`evaluate_A..D`) then consume that
   `evidence_snippets` buffer, whose information atom is produced by NO semantic
   node ⇒ `infoSound = false`. The `evidence_grounded` sub-goal additionally lacks
   `verificationCoverage` (no evidence-quality node). Cf. the SWE analogue
   `failed_workflow_1.lean`, which likewise asserts `infoSound = false`. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.failed_workflow_1_layer2_new

namespace failed_workflow_1_layer2_v2.SG
  def paper_comprehended : SubGoalName := ⟨"paper_comprehended"⟩
  def question_analyzed  : SubGoalName := ⟨"question_analyzed"⟩
  def evidence_grounded  : SubGoalName := ⟨"evidence_grounded"⟩
  def evidence_verified  : SubGoalName := ⟨"evidence_verified"⟩
  def options_judged     : SubGoalName := ⟨"options_judged"⟩
  def answer_finalized   : SubGoalName := ⟨"answer_finalized"⟩
end failed_workflow_1_layer2_v2.SG
open failed_workflow_1_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: elaipbench_agent (failed_workflow_1 / "worst" plan) -- new
Goal: Answer an academic paper question based on the provided passage
Nodes: 11 (semantic pipeline), Entry: 0, Exit: [10]

KEY CHARACTERISTICS (worst plan):
  1. Evidence is NOT grounded: keyword_hits → opaque evidence_snippets buffer; no
     boundedEvidenceList / verbatimSubstring; no evidence-quality verification.
  2. Fragmented judgement: four independent evaluate_A..D over evidence_snippets.
  3. RESULT: infoSound = FALSE (evaluate_A..D require `evidence_snippets`, which no
     semantic node produces); evidence_grounded sub-goal lacks verificationCoverage.
================================================================================
-/

/- ===== STEP 1: WORKFLOW GRAPH ===== -/

def bp1_nodeId0 : NodeId := ⟨0⟩
def bp1_nodeId1 : NodeId := ⟨1⟩
def bp1_nodeId2 : NodeId := ⟨2⟩
def bp1_nodeId3 : NodeId := ⟨3⟩
def bp1_nodeId4 : NodeId := ⟨4⟩
def bp1_nodeId5 : NodeId := ⟨5⟩
def bp1_nodeId6 : NodeId := ⟨6⟩
def bp1_nodeId7 : NodeId := ⟨7⟩
def bp1_nodeId8 : NodeId := ⟨8⟩
def bp1_nodeId9 : NodeId := ⟨9⟩
def bp1_nodeId10 : NodeId := ⟨10⟩

def bp1_node0 : WorkflowNode := {
  id := bp1_nodeId0, name := some "skim_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Skim the paper and produce a JSON overview."
}
def bp1_semNode0 : SemanticWorkflowNode := {
  baseNode := bp1_node0
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "paper_overview", varIsValidJson "paper_overview"]
  infoRequires := [info "paper_text"]
  producesContextInfo := [info "paper_overview", info "paper_text"]
  graphContributions := [paper_comprehended]
  graphImplicitRetries := [paper_comprehended]
}

def bp1_node1 : WorkflowNode := {
  id := bp1_nodeId1, name := some "extract_section_headings"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Extract the main section headings as a JSON outline."
}
def bp1_semNode1 : SemanticWorkflowNode := {
  baseNode := bp1_node1
  precondVariables := [varNameExists "paper_overview"]
  postcondVariables := [varIsNonEmptyString "section_headings", varIsValidJson "section_headings"]
  infoRequires := [info "paper_overview"]
  producesContextInfo := [info "section_headings"]
  graphContributions := [paper_comprehended]
}

def bp1_node2 : WorkflowNode := {
  id := bp1_nodeId2, name := some "analyze_question"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Analyze the question stem and classify its type. Emit JSON."
}
def bp1_semNode2 : SemanticWorkflowNode := {
  baseNode := bp1_node2
  precondVariables := [varIsNonEmptyString "question"]
  postcondVariables := [
    varIsNonEmptyString "question_analysis",
    varIsValidJson "question_analysis",
    varExt "question_analysis" (.makePredicateKey "user.elaip" "questionTypeEnum" [])
  ]
  infoRequires := [info "question_text", info "question_type_spec"]
  producesContextInfo := [info "question_analysis"]
  graphContributions := [question_analyzed]
  graphImplicitRetries := [question_analyzed]
}

def bp1_node3 : WorkflowNode := {
  id := bp1_nodeId3, name := some "keywords"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Derive a flat list of search keywords from the question analysis."
}
def bp1_semNode3 : SemanticWorkflowNode := {
  baseNode := bp1_node3
  precondVariables := [varNameExists "question_analysis"]
  postcondVariables := [varIsNonEmptyString "keywords"]
  infoRequires := [info "question_analysis"]
  producesContextInfo := [info "keywords"]
  graphContributions := [question_analyzed]
}

def bp1_node4 : WorkflowNode := {
  id := bp1_nodeId4, name := some "search_keyword_in_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "For each keyword, return raw matching passages (appended into an evidence_snippets buffer)."
}
def bp1_semNode4 : SemanticWorkflowNode := {
  baseNode := bp1_node4
  precondVariables := [varNameExists "keywords", varIsNonEmptyString "paper_content"]
  -- ungrounded: no boundedEvidenceList / verbatimSubstring ext
  postcondVariables := [varIsNonEmptyString "keyword_hits"]
  infoRequires := [info "keywords", info "paper_text"]
  producesContextInfo := [info "keyword_hits"]
  graphContributions := [evidence_grounded]   -- contributed but NEVER verified
}

def bp1_node5 : WorkflowNode := {
  id := bp1_nodeId5, name := some "evaluate_A"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Independently judge option A against the evidence_snippets buffer."
}
def bp1_semNode5 : SemanticWorkflowNode := {
  baseNode := bp1_node5
  precondVariables := [varNameExists "keyword_hits"]
  postcondVariables := [varIsNonEmptyString "judgment_A"]
  -- requires the consolidated evidence buffer, which NO semantic node produces:
  infoRequires := [info "question_text", info "evidence_snippets"]
  producesContextInfo := [info "judgment_A"]
}

def bp1_node6 : WorkflowNode := {
  id := bp1_nodeId6, name := some "evaluate_B"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Independently judge option B against the evidence_snippets buffer."
}
def bp1_semNode6 : SemanticWorkflowNode := {
  baseNode := bp1_node6
  precondVariables := [varNameExists "keyword_hits"]
  postcondVariables := [varIsNonEmptyString "judgment_B"]
  infoRequires := [info "evidence_snippets"]
  producesContextInfo := [info "judgment_B"]
}

def bp1_node7 : WorkflowNode := {
  id := bp1_nodeId7, name := some "evaluate_C"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Independently judge option C against the evidence_snippets buffer."
}
def bp1_semNode7 : SemanticWorkflowNode := {
  baseNode := bp1_node7
  precondVariables := [varNameExists "keyword_hits"]
  postcondVariables := [varIsNonEmptyString "judgment_C"]
  infoRequires := [info "evidence_snippets"]
  producesContextInfo := [info "judgment_C"]
}

def bp1_node8 : WorkflowNode := {
  id := bp1_nodeId8, name := some "evaluate_D"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Independently judge option D against the evidence_snippets buffer."
}
def bp1_semNode8 : SemanticWorkflowNode := {
  baseNode := bp1_node8
  precondVariables := [varNameExists "keyword_hits"]
  postcondVariables := [varIsNonEmptyString "judgment_D"]
  infoRequires := [info "evidence_snippets"]
  producesContextInfo := [info "judgment_D"]
}

def bp1_node9 : WorkflowNode := {
  id := bp1_nodeId9, name := some "aggregate_and_recheck"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Aggregate the four per-option judgements into a JSON verdict, with a recheck pass."
}
def bp1_semNode9 : SemanticWorkflowNode := {
  baseNode := bp1_node9
  precondVariables := [varNameExists "judgment_A", varNameExists "judgment_B", varNameExists "judgment_C", varNameExists "judgment_D"]
  postcondVariables := [
    varIsNonEmptyString "option_judgment",
    varIsValidJson "option_judgment",
    varExt "option_judgment" (.makePredicateKey "user.elaip" "verdictEnumValid" [])
  ]
  infoRequires := [info "judgment_A", info "judgment_B", info "judgment_C", info "judgment_D"]
  producesContextInfo := [info "option_judgment"]
  graphContributions := [options_judged]
  graphImplicitRetries := [options_judged]
}

def bp1_node10 : WorkflowNode := {
  id := bp1_nodeId10, name := some "finalize_answer"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Produce the final answer (multi/single-answer branch) from the aggregated judgement."
}
def bp1_semNode10 : SemanticWorkflowNode := {
  baseNode := bp1_node10
  precondVariables := [varNameExists "option_judgment"]
  postcondVariables := [varIsNonEmptyString "final_response"]
  infoRequires := [info "option_judgment"]
  producesContextInfo := [info "final_response"]
  graphContributions := [answer_finalized]
}

def bp1Graph : WorkflowGraph := {
  nodes := [bp1_node0, bp1_node1, bp1_node2, bp1_node3, bp1_node4, bp1_node5, bp1_node6, bp1_node7, bp1_node8, bp1_node9, bp1_node10]
  edges := [
    .seqEdge bp1_nodeId0 bp1_nodeId1,
    .seqEdge bp1_nodeId1 bp1_nodeId2,
    .seqEdge bp1_nodeId2 bp1_nodeId3,
    .seqEdge bp1_nodeId3 bp1_nodeId4,
    .seqEdge bp1_nodeId4 bp1_nodeId5,
    .seqEdge bp1_nodeId5 bp1_nodeId6,
    .seqEdge bp1_nodeId6 bp1_nodeId7,
    .seqEdge bp1_nodeId7 bp1_nodeId8,
    .seqEdge bp1_nodeId8 bp1_nodeId9,
    .seqEdge bp1_nodeId9 bp1_nodeId10
  ]
  entry := bp1_nodeId0
  exits := [bp1_nodeId10]
  parameters := [⟨"question", .TString⟩, ⟨"paper_content", .TString⟩, ⟨"question_type_instruction", .TString⟩, ⟨"question_type", .TString⟩]
}

/- ===== STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS ===== -/

#eval do
  let g := bp1Graph
  for node in g.nodes do
    let name := node.name.getD "(unnamed)"
    IO.println s!"\n--- Node {node.id}: \"{name}\" [{repr node.stepType}] ---"
    IO.println s!"  writesConsistent:   {node.writesConsistent}"
    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"

/- ===== STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS ===== -/

#eval bp1Graph.allWritesConsistent
#eval bp1Graph.allReadResolvable
#eval bp1Graph.edgesValid
#eval bp1Graph.entryNodeValid
#eval bp1Graph.exitNodesValid
#eval bp1Graph.allExitsReachable
#eval bp1Graph.noOrphanNodes

/- ===== STEP 4-5: THEOREMS (Layer 1 -- structural; all PASS) ===== -/

theorem bp1_writesConsistent : bp1Graph.allWritesConsistent = true := by native_decide
theorem bp1_readsResolvable : bp1Graph.allReadResolvable = true := by native_decide
theorem bp1_edgesValid : bp1Graph.edgesValid = true := by native_decide
theorem bp1_entryValid : bp1Graph.entryNodeValid = true := by native_decide
theorem bp1_exitsValid : bp1Graph.exitNodesValid = true := by native_decide
theorem bp1_exitsReachable : bp1Graph.allExitsReachable = true := by native_decide
theorem bp1_noOrphans : bp1Graph.noOrphanNodes = true := by native_decide

/- ===== STEP 6: PARAMETERS + GOAL SPEC + SEMANTIC GRAPH ===== -/

def bp1_paramNode : SemanticWorkflowNode := {
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

def failed_workflow_1_goalSpec : GoalSpecification := {
  originalGoal := "Answer an academic paper question based on the provided passage"
  subGoals := [
    { name := paper_comprehended
      variableName := "paper_overview"
      requiredPredicate := .isNonEmptyString
      description := "Paper skimmed and section headings extracted."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := question_analyzed
      variableName := "question_analysis"
      requiredPredicate := .isNonEmptyString
      description := "Question stem analysed and typed (questionTypeEnum)."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := evidence_grounded
      variableName := "keyword_hits"
      requiredPredicate := .isNonEmptyString
      description := "Evidence should be bounded + verbatim-grounded AND verified — here it is neither (ungrounded keyword_hits, no quality node), so verificationCoverage FAILS."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.verificationCoverage] },
    { name := evidence_verified
      variableName := "evidence_quality_check"
      requiredPredicate := .isNonEmptyString
      description := "No evidence-quality verification node exists in this plan — sub-goal uncovered."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := options_judged
      variableName := "option_judgment"
      requiredPredicate := .isNonEmptyString
      description := "Verdicts aggregated from four fragmented per-option judgements (verdictEnumValid), with a recheck loop."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack] },
    { name := answer_finalized
      variableName := "final_response"
      requiredPredicate := .isNonEmptyString
      description := "A final response is produced."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] }
  ]
}

def failed_workflow_1_layer2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := bp1Graph
  paramNode := bp1_paramNode
  semanticNodes := [bp1_semNode0, bp1_semNode1, bp1_semNode2, bp1_semNode3, bp1_semNode4, bp1_semNode5, bp1_semNode6, bp1_semNode7, bp1_semNode8, bp1_semNode9, bp1_semNode10]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := failed_workflow_1_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage.
   This "worst" plan is variable-sound but INFO-UNSOUND (see infoSound theorem). -/
#eval IO.println (failed_workflow_1_layer2SemanticGraph.verifyWorkflowReport (label := "failed_workflow_1"))

theorem failed_workflow_1_hoare_sound : (failed_workflow_1_layer2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem failed_workflow_1_info_unsound : (failed_workflow_1_layer2SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

def bp1_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.failed_workflow_1_layer2_new
