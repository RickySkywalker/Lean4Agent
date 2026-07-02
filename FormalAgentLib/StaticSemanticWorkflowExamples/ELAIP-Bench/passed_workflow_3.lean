/- ELAIP-Bench Layer-2 verification (Solution-2 / NEW idiom), authored from the
   ELAIP `passed_workflow_3` Layer-2 IR (`elaipbench_layer2_v2_ir/passed_workflow_3_layer2_v2.ir.json`)
   per `LAYER2_NEW_FORMAT.md`. Graph contributions/verifications/retries and
   information flow live on the semantic nodes; the goal spec is embedded in the
   graph; one `verifyWorkflowReport` reports variables + info-flow + coverage.

   Modeling note: the ELAIP IR flattens a `for_each` keyword search, a `while`
   recheck loop, and a `switch` over question_type into a linear node list. This
   Layer-2 model keeps the semantic pipeline (skim → outline → keywords → classify
   → locate → consolidate → verify → judge → finalize): the `set_variable` /
   `increment` book-keeping nodes are dropped, the per-keyword `for_each` search is
   collapsed to one `locate_keyword_hits` node, the `while` recheck loop is carried
   as `graphImplicitRetries` on the judgement node, and the three question-type
   `finalize_*` branches collapse to one `answer_finalized` exit. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.passed_workflow_3_layer2_new

/- Typed sub-goal identities — declared ONCE, referenced in node fields + goalSpec
   so a typo is an "unknown identifier" compile error, not a silent NONE. -/
namespace passed_workflow_3_layer2_v2.SG
  def paper_comprehended : SubGoalName := ⟨"paper_comprehended"⟩
  def question_analyzed  : SubGoalName := ⟨"question_analyzed"⟩
  def evidence_grounded  : SubGoalName := ⟨"evidence_grounded"⟩
  def evidence_verified  : SubGoalName := ⟨"evidence_verified"⟩
  def options_judged     : SubGoalName := ⟨"options_judged"⟩
  def answer_finalized   : SubGoalName := ⟨"answer_finalized"⟩
end passed_workflow_3_layer2_v2.SG
open passed_workflow_3_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: elaipbench_agent (passed_workflow_3 / "best" plan) -- new
Goal: Answer an academic paper question based on the provided passage
Parameters: ['question', 'paper_content', 'question_type_instruction', 'question_type']
Nodes: 9 (semantic pipeline), Entry: 0, Exit: [8]

KEY CHARACTERISTICS (best plan):
  1. Evidence is GROUNDED: boundedEvidenceList (≤5 snippets) + verbatimSubstring
     (each snippet appears character-exact in paper_content).
  2. Evidence is VERIFIED: a dedicated evidence-quality node verifies the
     `evidence_grounded` sub-goal (graphVerifications).
  3. Question is typed: questionTypeEnum on `classify_question_type`.
  4. Option judgement carries verdictEnumValid and a recheck loop
     (graphImplicitRetries → unifiedLoopBack).
================================================================================
-/

/- ========================================================================
   STEP 1: WORKFLOW GRAPH
   ======================================================================== -/

def gp3_nodeId0 : NodeId := ⟨0⟩
def gp3_nodeId1 : NodeId := ⟨1⟩
def gp3_nodeId2 : NodeId := ⟨2⟩
def gp3_nodeId3 : NodeId := ⟨3⟩
def gp3_nodeId4 : NodeId := ⟨4⟩
def gp3_nodeId5 : NodeId := ⟨5⟩
def gp3_nodeId6 : NodeId := ⟨6⟩
def gp3_nodeId7 : NodeId := ⟨7⟩
def gp3_nodeId8 : NodeId := ⟨8⟩

def gp3_node0 : WorkflowNode := {
  id := gp3_nodeId0, name := some "skim_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Begin by skimming the paper at a high level to anchor later reasoning. Read the paper and produce a JSON overview (title, problem, contributions, methods)."
}
def gp3_semNode0 : SemanticWorkflowNode := {
  baseNode := gp3_node0
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "paper_overview", varIsValidJson "paper_overview"]
  infoRequires := [info "paper_text"]
  producesContextInfo := [info "paper_overview", info "paper_text"]
  graphContributions := [paper_comprehended]
  graphImplicitRetries := [paper_comprehended]
}

def gp3_node1 : WorkflowNode := {
  id := gp3_nodeId1, name := some "extract_section_headings"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Now extract the main section headings of the same paper as a JSON outline, to be used for evidence localisation."
}
def gp3_semNode1 : SemanticWorkflowNode := {
  baseNode := gp3_node1
  precondVariables := [varNameExists "paper_overview", varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "section_headings", varIsValidJson "section_headings"]
  infoRequires := [info "paper_overview", info "paper_text"]
  producesContextInfo := [info "section_headings"]
  graphContributions := [paper_comprehended]
}

def gp3_node2 : WorkflowNode := {
  id := gp3_nodeId2, name := some "extract_keywords"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "From the question stem, extract the salient keywords and search terms to be used for evidence localisation against the paper."
}
def gp3_semNode2 : SemanticWorkflowNode := {
  baseNode := gp3_node2
  precondVariables := [varIsNonEmptyString "question", varNameExists "paper_overview"]
  postcondVariables := [varIsNonEmptyString "question_keywords"]
  infoRequires := [info "question_text", info "paper_overview"]
  producesContextInfo := [info "question_keywords"]
  graphContributions := [question_analyzed]
}

def gp3_node3 : WorkflowNode := {
  id := gp3_nodeId3, name := some "classify_question_type"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Classify the question type (single-answer / multiple-answer / other) per the question_type_instruction. Emit a JSON classification used to dispatch downstream reasoning."
}
def gp3_semNode3 : SemanticWorkflowNode := {
  baseNode := gp3_node3
  precondVariables := [varIsNonEmptyString "question", varNameExists "question_keywords"]
  postcondVariables := [
    varIsNonEmptyString "question_classification",
    varExt "question_classification" (.makePredicateKey "user.elaip" "questionTypeEnum" [])
  ]
  infoRequires := [info "question_text", info "question_type_spec", info "question_keywords"]
  producesContextInfo := [info "question_classification"]
  graphContributions := [question_analyzed]
  graphImplicitRetries := [question_analyzed]
}

def gp3_node4 : WorkflowNode := {
  id := gp3_nodeId4, name := some "locate_keyword_hits"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "For each extracted keyword, search the paper and locate the passages that mention it (or close synonyms). Accumulate the per-keyword hits as JSON (one entry per keyword)."
}
def gp3_semNode4 : SemanticWorkflowNode := {
  baseNode := gp3_node4
  precondVariables := [varNameExists "question_keywords", varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "keyword_hits", varIsValidJson "keyword_hits"]
  infoRequires := [info "question_keywords", info "paper_text"]
  producesContextInfo := [info "keyword_hits"]
  graphContributions := [evidence_grounded]
}

def gp3_node5 : WorkflowNode := {
  id := gp3_nodeId5, name := some "consolidate_evidence"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Consolidate the per-keyword hits into a single ranked evidence set (≤5 snippets); every snippet's text must appear verbatim in paper_content."
}
def gp3_semNode5 : SemanticWorkflowNode := {
  baseNode := gp3_node5
  precondVariables := [varNameExists "keyword_hits", varNameExists "question_classification"]
  postcondVariables := [
    varIsNonEmptyString "evidence",
    varIsValidJson "evidence",
    varExt "evidence" (.makePredicateKey "user.elaip" "boundedEvidenceList" []),
    varExt "evidence" (.makePredicateKey "user.elaip" "verbatimSubstring" [])
  ]
  infoRequires := [info "keyword_hits", info "question_classification", info "paper_text"]
  producesContextInfo := [info "evidence"]
  graphContributions := [evidence_grounded]
  graphImplicitRetries := [evidence_grounded]
}

def gp3_node6 : WorkflowNode := {
  id := gp3_nodeId6, name := some "verify_evidence_quality"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Sanity-check the evidence set before option evaluation: confirm relevance, verbatim grounding, and that the ≤5 bound is respected. Emit a JSON quality note."
}
def gp3_semNode6 : SemanticWorkflowNode := {
  baseNode := gp3_node6
  precondVariables := [varNameExists "evidence"]
  postcondVariables := [varIsNonEmptyString "evidence_quality_note"]
  infoRequires := [info "question_classification", info "evidence", info "paper_text"]
  producesContextInfo := [info "evidence_quality_note"]
  graphContributions := [evidence_verified]
  graphVerifications := [evidence_grounded]
}

def gp3_node7 : WorkflowNode := {
  id := gp3_nodeId7, name := some "evaluate_options"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Evaluate each answer option (A,B,C,D) against the consolidated evidence as INDEPENDENT verdicts. Recheck for multiple-answer questions. Emit a JSON judgement keyed by option."
}
def gp3_semNode7 : SemanticWorkflowNode := {
  baseNode := gp3_node7
  precondVariables := [varNameExists "evidence", varNameExists "evidence_quality_note"]
  postcondVariables := [
    varIsNonEmptyString "option_judgment",
    varIsValidJson "option_judgment",
    varExt "option_judgment" (.makePredicateKey "user.elaip" "verdictEnumValid" [])
  ]
  infoRequires := [info "question_text", info "question_classification", info "evidence", info "evidence_quality_note"]
  producesContextInfo := [info "option_judgment"]
  graphContributions := [options_judged]
  graphImplicitRetries := [options_judged]
}

def gp3_node8 : WorkflowNode := {
  id := gp3_nodeId8, name := some "finalize_answer"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Produce the final answer, dispatched on question_type (single-answer / multiple-answer / default fallback) from the option evaluation."
}
def gp3_semNode8 : SemanticWorkflowNode := {
  baseNode := gp3_node8
  precondVariables := [varNameExists "option_judgment"]
  postcondVariables := [varIsNonEmptyString "final_response"]
  infoRequires := [info "question_text", info "option_judgment", info "question_type_spec"]
  producesContextInfo := [info "final_response"]
  graphContributions := [answer_finalized]
}

def gp3Graph : WorkflowGraph := {
  nodes := [gp3_node0, gp3_node1, gp3_node2, gp3_node3, gp3_node4, gp3_node5, gp3_node6, gp3_node7, gp3_node8]
  edges := [
    .seqEdge gp3_nodeId0 gp3_nodeId1,
    .seqEdge gp3_nodeId1 gp3_nodeId2,
    .seqEdge gp3_nodeId2 gp3_nodeId3,
    .seqEdge gp3_nodeId3 gp3_nodeId4,
    .seqEdge gp3_nodeId4 gp3_nodeId5,
    .seqEdge gp3_nodeId5 gp3_nodeId6,
    .seqEdge gp3_nodeId6 gp3_nodeId7,
    .seqEdge gp3_nodeId7 gp3_nodeId8
  ]
  entry := gp3_nodeId0
  exits := [gp3_nodeId8]
  parameters := [⟨"question", .TString⟩, ⟨"paper_content", .TString⟩, ⟨"question_type_instruction", .TString⟩, ⟨"question_type", .TString⟩]
}

/- ========================================================================
   STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
   ======================================================================== -/

#eval do
  let g := gp3Graph
  for node in g.nodes do
    let name := node.name.getD "(unnamed)"
    IO.println s!"\n--- Node {node.id}: \"{name}\" [{repr node.stepType}] ---"
    IO.println s!"  writesConsistent:   {node.writesConsistent}"
    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"
    for rv in node.reads do
      let fromParam := g.parameters.any (fun p => p.name == rv.name && p.type.compatible rv.type)
      let fromPred := g.nodes.any (fun o =>
        o.id != node.id && g.reachable o.id node.id &&
        o.writes.any (fun w => w.name == rv.name && w.type.compatible rv.type))
      let status := if fromParam || fromPred then "✓" else "✗ UNRESOLVED"
      IO.println s!"    read  \"{rv.name}\" ({repr rv.type}): {status}"

/- ========================================================================
   STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS
   ======================================================================== -/

#eval gp3Graph.allWritesConsistent
#eval gp3Graph.allReadResolvable
#eval gp3Graph.edgesValid
#eval gp3Graph.entryNodeValid
#eval gp3Graph.exitNodesValid
#eval gp3Graph.allExitsReachable
#eval gp3Graph.noOrphanNodes

/- ========================================================================
   STEP 4-5: THEOREMS (Layer 1 -- structural)
   ======================================================================== -/

theorem gp3_writesConsistent : gp3Graph.allWritesConsistent = true := by native_decide
theorem gp3_readsResolvable : gp3Graph.allReadResolvable = true := by native_decide
theorem gp3_edgesValid : gp3Graph.edgesValid = true := by native_decide
theorem gp3_entryValid : gp3Graph.entryNodeValid = true := by native_decide
theorem gp3_exitsValid : gp3Graph.exitNodesValid = true := by native_decide
theorem gp3_exitsReachable : gp3Graph.allExitsReachable = true := by native_decide
theorem gp3_noOrphans : gp3Graph.noOrphanNodes = true := by native_decide

/- ========================================================================
   STEP 6: PARAMETERS + GOAL SPEC + SEMANTIC GRAPH
   ======================================================================== -/

def gp3_paramNode : SemanticWorkflowNode := {
  baseNode := { id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varNameExists "question",
    varNameExists "paper_content",
    varNameExists "question_type_instruction",
    varNameExists "question_type",
    varIsNonEmptyString "question",
    varIsNonEmptyString "paper_content",
    varIsNonEmptyString "question_type_instruction",
    varIsNonEmptyString "question_type"
  ]
  producesVariableInfo := [
    varInfo "paper_content" ["paper_text"],
    varInfo "question" ["question_text"],
    varInfo "question_type_instruction" ["question_type_spec"]
  ]
}

def passed_workflow_3_goalSpec : GoalSpecification := {
  originalGoal := "Answer an academic paper question based on the provided passage"
  subGoals := [
    { name := paper_comprehended
      variableName := "paper_overview"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the paper was skimmed and structurally outlined (overview + section headings)."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := question_analyzed
      variableName := "question_classification"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the question stem was analysed (keywords) and typed (questionTypeEnum) before option reasoning."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := evidence_grounded
      variableName := "evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence set is bounded (≤5) and verbatim-grounded in paper_content; must be verified downstream."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.verificationCoverage] },
    { name := evidence_verified
      variableName := "evidence_quality_note"
      requiredPredicate := .isNonEmptyString
      description := "A dedicated evidence-quality node verifies the grounded evidence before judgement."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := options_judged
      variableName := "option_judgment"
      requiredPredicate := .isNonEmptyString
      description := "Per-option verdicts (verdictEnumValid) with a recheck loop (unifiedLoopBack) over the judgement node."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack] },
    { name := answer_finalized
      variableName := "final_response"
      requiredPredicate := .isNonEmptyString
      description := "A final response is produced, dispatched on question_type."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.failSafe] }
  ]
}

def passed_workflow_3_layer2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := gp3Graph
  paramNode := gp3_paramNode
  semanticNodes := [gp3_semNode0, gp3_semNode1, gp3_semNode2, gp3_semNode3, gp3_semNode4, gp3_semNode5, gp3_semNode6, gp3_semNode7, gp3_semNode8]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := passed_workflow_3_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (passed_workflow_3_layer2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_3"))

theorem passed_workflow_3_hoare_sound : (passed_workflow_3_layer2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_3_info_sound : (passed_workflow_3_layer2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

def gp3_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.passed_workflow_3_layer2_new
