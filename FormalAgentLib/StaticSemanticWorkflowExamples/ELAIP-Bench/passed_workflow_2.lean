/- ELAIP-Bench Layer-2 verification (Solution-2 / NEW idiom), authored from the
   ELAIP `passed_workflow_2` Layer-2 IR (`elaipbench_layer2_v2_ir/passed_workflow_2_layer2_v2.ir.json`)
   per `LAYER2_NEW_FORMAT.md`. Graph contributions/verifications/retries and
   information flow live on the semantic nodes; the goal spec is embedded in the
   graph; one `verifyWorkflowReport` reports variables + info-flow + coverage.

   Modeling note: the ELAIP IR flattens an evidence-quality `while` re-broaden
   loop and a `while` option recheck loop into a linear node list. This Layer-2
   model keeps the semantic pipeline (skim → analyze → extract → refine → judge →
   finalize): the evidence re-broaden step is modeled as a second
   `evidence`-producing node that VERIFIES `evidence_grounded` and carries
   `graphImplicitRetries := [evidence_grounded]`; the option recheck `while` loop
   collapses to `graphImplicitRetries := [options_judged]` on the judgement node;
   the question-type `final_response` branches collapse to one `answer_finalized`
   exit. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.passed_workflow_2_layer2_new

/- Typed sub-goal identities — declared ONCE, referenced in node fields + goalSpec
   so a typo is an "unknown identifier" compile error, not a silent NONE. -/
namespace passed_workflow_2_layer2_v2.SG
  def paper_comprehended : SubGoalName := ⟨"paper_comprehended"⟩
  def question_analyzed  : SubGoalName := ⟨"question_analyzed"⟩
  def evidence_grounded  : SubGoalName := ⟨"evidence_grounded"⟩
  def evidence_verified  : SubGoalName := ⟨"evidence_verified"⟩
  def options_judged     : SubGoalName := ⟨"options_judged"⟩
  def answer_finalized   : SubGoalName := ⟨"answer_finalized"⟩
end passed_workflow_2_layer2_v2.SG
open passed_workflow_2_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: elaipbench_agent (passed_workflow_2 / "best" plan) -- new
Goal: Answer an academic paper question based on the provided passage
Parameters: ['question', 'paper_content', 'question_type_instruction', 'question_type']
Nodes: 6 (semantic pipeline), Entry: 0, Exit: [5]

KEY CHARACTERISTICS (best plan):
  1. Evidence is GROUNDED: boundedEvidenceList (≤5 snippets) + verbatimSubstring
     (each snippet appears character-exact in paper_content).
  2. Evidence is VERIFIED: a re-broaden node re-reads the evidence and re-grounds
     it, verifying the `evidence_grounded` sub-goal (graphVerifications) and
     carrying an implicit retry over the grounding.
  3. Question is typed: questionTypeEnum on `question_analysis`.
  4. Option judgement carries verdictEnumValid and a recheck loop
     (graphImplicitRetries → unifiedLoopBack).
================================================================================
-/

/- ========================================================================
   STEP 1: WORKFLOW GRAPH
   ======================================================================== -/

def gp2_nodeId0 : NodeId := ⟨0⟩
def gp2_nodeId1 : NodeId := ⟨1⟩
def gp2_nodeId2 : NodeId := ⟨2⟩
def gp2_nodeId3 : NodeId := ⟨3⟩
def gp2_nodeId4 : NodeId := ⟨4⟩
def gp2_nodeId5 : NodeId := ⟨5⟩

def gp2_node0 : WorkflowNode := {
  id := gp2_nodeId0, name := some "skim_paper"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Read the paper passage and produce a compact JSON overview (title, abstract summary, contributions) to reuse as a navigation map for the rest of the workflow."
}
def gp2_semNode0 : SemanticWorkflowNode := {
  baseNode := gp2_node0
  precondVariables := [varIsNonEmptyString "paper_content"]
  postcondVariables := [varIsNonEmptyString "paper_overview", varIsValidJson "paper_overview"]
  infoRequires := [info "paper_text"]
  producesContextInfo := [info "paper_overview", info "paper_text"]
  graphContributions := [paper_comprehended]
  graphImplicitRetries := [paper_comprehended]
}

def gp2_node1 : WorkflowNode := {
  id := gp2_nodeId1, name := some "analyze_question"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Analyze ONLY the question stem (no answer options yet) to determine what specific information must be found in the paper. Emit a JSON analysis including question type."
}
def gp2_semNode1 : SemanticWorkflowNode := {
  baseNode := gp2_node1
  precondVariables := [varIsNonEmptyString "question", varNameExists "paper_overview"]
  postcondVariables := [
    varIsNonEmptyString "question_analysis",
    varIsValidJson "question_analysis",
    varExt "question_analysis" (.makePredicateKey "user.elaip" "questionTypeEnum" [])
  ]
  infoRequires := [info "question_text", info "question_type_spec", info "paper_overview"]
  producesContextInfo := [info "question_analysis"]
  graphContributions := [question_analyzed]
  graphImplicitRetries := [question_analyzed]
}

def gp2_node2 : WorkflowNode := {
  id := gp2_nodeId2, name := some "extract_evidence"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Locate the most relevant evidence in the paper to address the core claim, using the keywords from the question analysis. Return ≤5 snippets as JSON; every snippet's text must appear verbatim in paper_content."
}
def gp2_semNode2 : SemanticWorkflowNode := {
  baseNode := gp2_node2
  precondVariables := [varNameExists "question_analysis", varIsNonEmptyString "paper_content"]
  postcondVariables := [
    varIsNonEmptyString "evidence",
    varIsValidJson "evidence",
    varExt "evidence" (.makePredicateKey "user.elaip" "boundedEvidenceList" []),
    varExt "evidence" (.makePredicateKey "user.elaip" "verbatimSubstring" [])
  ]
  infoRequires := [info "question_analysis", info "paper_text"]
  producesContextInfo := [info "evidence"]
  graphContributions := [evidence_grounded]
}

def gp2_node3 : WorkflowNode := {
  id := gp2_nodeId3, name := some "rebroaden_evidence"
  stepType := .step
  reads := [⟨"paper_content", .TString⟩], writes := []
  llmInstruction := some "Re-extract evidence with a broader search — include synonyms and related terminology and consider sections you may have missed — then re-verify grounding. Return ≤5 snippets as JSON; every snippet's text must appear verbatim in paper_content."
}
def gp2_semNode3 : SemanticWorkflowNode := {
  baseNode := gp2_node3
  precondVariables := [varNameExists "evidence", varIsNonEmptyString "paper_content"]
  postcondVariables := [
    varIsNonEmptyString "evidence",
    varIsValidJson "evidence",
    varExt "evidence" (.makePredicateKey "user.elaip" "boundedEvidenceList" []),
    varExt "evidence" (.makePredicateKey "user.elaip" "verbatimSubstring" [])
  ]
  infoRequires := [info "question_analysis", info "evidence", info "paper_text"]
  producesContextInfo := [info "evidence"]
  graphContributions := [evidence_verified]
  graphVerifications := [evidence_grounded]
  graphImplicitRetries := [evidence_grounded]
}

def gp2_node4 : WorkflowNode := {
  id := gp2_nodeId4, name := some "evaluate_options"
  stepType := .step
  reads := [⟨"question", .TString⟩], writes := []
  llmInstruction := some "Evaluate each answer option (A,B,C,D) against the consolidated evidence as INDEPENDENT verdicts. Recheck for multiple-answer questions. Emit a JSON judgement keyed by option."
}
def gp2_semNode4 : SemanticWorkflowNode := {
  baseNode := gp2_node4
  precondVariables := [varNameExists "evidence", varNameExists "question_analysis"]
  postcondVariables := [
    varIsNonEmptyString "option_judgment",
    varIsValidJson "option_judgment",
    varExt "option_judgment" (.makePredicateKey "user.elaip" "verdictEnumValid" [])
  ]
  infoRequires := [info "question_text", info "question_analysis", info "evidence"]
  producesContextInfo := [info "option_judgment"]
  graphContributions := [options_judged]
  graphImplicitRetries := [options_judged]
}

def gp2_node5 : WorkflowNode := {
  id := gp2_nodeId5, name := some "finalize_response"
  stepType := .step
  reads := [⟨"question", .TString⟩, ⟨"question_type_instruction", .TString⟩], writes := []
  llmInstruction := some "Produce the final answer, dispatched on question_type (single-answer / multiple-answer / default fallback) from the option evaluation."
}
def gp2_semNode5 : SemanticWorkflowNode := {
  baseNode := gp2_node5
  precondVariables := [varNameExists "option_judgment"]
  postcondVariables := [varIsNonEmptyString "final_response"]
  infoRequires := [info "question_text", info "option_judgment", info "question_type_spec"]
  producesContextInfo := [info "final_response"]
  graphContributions := [answer_finalized]
}

def gp2Graph : WorkflowGraph := {
  nodes := [gp2_node0, gp2_node1, gp2_node2, gp2_node3, gp2_node4, gp2_node5]
  edges := [
    .seqEdge gp2_nodeId0 gp2_nodeId1,
    .seqEdge gp2_nodeId1 gp2_nodeId2,
    .seqEdge gp2_nodeId2 gp2_nodeId3,
    .seqEdge gp2_nodeId3 gp2_nodeId4,
    .seqEdge gp2_nodeId4 gp2_nodeId5
  ]
  entry := gp2_nodeId0
  exits := [gp2_nodeId5]
  parameters := [⟨"question", .TString⟩, ⟨"paper_content", .TString⟩, ⟨"question_type_instruction", .TString⟩, ⟨"question_type", .TString⟩]
}

/- ========================================================================
   STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
   ======================================================================== -/

#eval do
  let g := gp2Graph
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

#eval gp2Graph.allWritesConsistent
#eval gp2Graph.allReadResolvable
#eval gp2Graph.edgesValid
#eval gp2Graph.entryNodeValid
#eval gp2Graph.exitNodesValid
#eval gp2Graph.allExitsReachable
#eval gp2Graph.noOrphanNodes

/- ========================================================================
   STEP 4-5: THEOREMS (Layer 1 -- structural)
   ======================================================================== -/

theorem gp2_writesConsistent : gp2Graph.allWritesConsistent = true := by native_decide
theorem gp2_readsResolvable : gp2Graph.allReadResolvable = true := by native_decide
theorem gp2_edgesValid : gp2Graph.edgesValid = true := by native_decide
theorem gp2_entryValid : gp2Graph.entryNodeValid = true := by native_decide
theorem gp2_exitsValid : gp2Graph.exitNodesValid = true := by native_decide
theorem gp2_exitsReachable : gp2Graph.allExitsReachable = true := by native_decide
theorem gp2_noOrphans : gp2Graph.noOrphanNodes = true := by native_decide

/- ========================================================================
   STEP 6: PARAMETERS + GOAL SPEC + SEMANTIC GRAPH
   ======================================================================== -/

def gp2_paramNode : SemanticWorkflowNode := {
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

def passed_workflow_2_goalSpec : GoalSpecification := {
  originalGoal := "Answer an academic paper question based on the provided passage"
  subGoals := [
    { name := paper_comprehended
      variableName := "paper_overview"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the paper was skimmed into a compact navigation overview."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := question_analyzed
      variableName := "question_analysis"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the question stem was analysed and typed (questionTypeEnum) before option reasoning."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := evidence_grounded
      variableName := "evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence set is bounded (≤5) and verbatim-grounded in paper_content; must be verified downstream."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.verificationCoverage] },
    { name := evidence_verified
      variableName := "evidence"
      requiredPredicate := .isNonEmptyString
      description := "A re-broaden node re-grounds the evidence, verifying it before judgement."
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

def passed_workflow_2_layer2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := gp2Graph
  paramNode := gp2_paramNode
  semanticNodes := [gp2_semNode0, gp2_semNode1, gp2_semNode2, gp2_semNode3, gp2_semNode4, gp2_semNode5]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := passed_workflow_2_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (passed_workflow_2_layer2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_2"))

theorem passed_workflow_2_hoare_sound : (passed_workflow_2_layer2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_2_info_sound : (passed_workflow_2_layer2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

def gp2_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.passed_workflow_2_layer2_new
