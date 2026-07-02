/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original seed_001_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.seed_001_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace seed_001_layer2_v2.SG
  def repository_explored : SubGoalName := ⟨"repository_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def root_cause_identified : SubGoalName := ⟨"root_cause_identified"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def edge_cases_discovered : SubGoalName := ⟨"edge_cases_discovered"⟩
  def edge_cases_checked : SubGoalName := ⟨"edge_cases_checked"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end seed_001_layer2_v2.SG
open seed_001_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: swe_agent_structured (seed_001) — v2 STRICT
Source: seed_001.yaml
Goal: Reproduce the issue described by the PR and produce a git patch that fixes it.
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 11 (simplified), Entry: 0, Exits: [10]
Semantic layer: READY
Graph-level analysis: READY

STRICT ANNOTATION RULES APPLIED:
  R1: markImplicitRetry → ONLY for task nodes. ALL nodes here are step → NONE used.
  R2: markInfoContent on titled structured output fields. Instructions with
      OUTPUT_FORMAT templates ("BUG_LOCATION:", "ROOT_CAUSE:", ...) are
      addressable and marked. Free-form "summarize findings" prose is not.
  R3: Preconditions honestly demand specific info aspects from predecessors.

KEY PROBLEMS (predicted FAIL, medium confidence):
  1. The terminal `create_and_submit_patch` step reads NOTHING upstream — no
     template references to {{fix_result}} or {{diagnosis}}. Its precondition
     should demand what_to_submit/modified_files knowledge, but no info is
     injected. → FAIL.
  2. The `for_each` probe_edge_case body has NO save_as — per-edge-case
     findings evaporate. The loop's exitPostconditions can't carry evidence
     that edge cases were actually checked. → Loss of information flow.
  3. `reproduction_retry` overwrites repro_report in the then-branch but
     else-branch's reproduction_confirmed writes nothing — inconsistent post
     state across the conditional, though both branches leave repro_report
     non-empty (from predecessor or injection).

  Node   0: step             [READY]  "orient_and_survey_repo"
          reads:  problem_statement
          writes: orientation_report
  Node   1: step             [READY]  "build_reproduction"
          reads:  orientation_report
          writes: repro_report
  Node   2: conditional      [DET]    "repro_check" (repro_report contains could_not_reproduce)
          reads:  repro_report
          writes: (none)
  Node   3: step             [READY]  "reproduction_retry"   (then-branch)
          reads:  repro_report
          writes: repro_report
  Node   4: step             [READY]  "reproduction_confirmed" (else-branch)
          reads:  repro_report
          writes: (none)
  Node   5: step             [READY]  "diagnose_root_cause"
          reads:  orientation_report, repro_report
          writes: diagnosis
  Node   6: step             [READY]  "apply_fix"
          reads:  diagnosis
          writes: fix_result
  Node   7: step             [READY]  "discover_edge_case_list"
          reads:  diagnosis
          writes: edge_case_list
  Node   8: whileLoop        [DET]    "for_each_edge_cases"
          reads:  edge_case_list
          writes: (none)
  Node   9: step             [READY]  "probe_edge_case"  (loop body, NO save_as)
          reads:  fix_result, edge_case
          writes: (none)
  Node  10: step             [READY]  "create_and_submit_patch"
          reads:  (none)   ← BAD: no {{fix_result}}, no {{diagnosis}}
          writes: submission_result
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def seed_001_nodeId0 : NodeId := ⟨0⟩
def seed_001_nodeId1 : NodeId := ⟨1⟩
def seed_001_nodeId2 : NodeId := ⟨2⟩
def seed_001_nodeId3 : NodeId := ⟨3⟩
def seed_001_nodeId4 : NodeId := ⟨4⟩
def seed_001_nodeId5 : NodeId := ⟨5⟩
def seed_001_nodeId6 : NodeId := ⟨6⟩
def seed_001_nodeId7 : NodeId := ⟨7⟩
def seed_001_nodeId8 : NodeId := ⟨8⟩
def seed_001_nodeId9 : NodeId := ⟨9⟩
def seed_001_nodeId10 : NodeId := ⟨10⟩

def seed_001_node0 : WorkflowNode := {
  id := seed_001_nodeId0, name := some "orient_and_survey_repo"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩], writes := [⟨"orientation_report", .TString⟩]
  llmInstruction := some "Orient agent and survey /testbed. OUTPUT_FORMAT:\nPROJECT: ...\nISSUE_SUMMARY: ...\nCANDIDATE_FILES: ...\nNOTES: ..."
}

def seed_001_semNode0 : SemanticWorkflowNode := {
  baseNode := seed_001_node0
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "orientation_report", varContainsSentinel "orientation_report" "CANDIDATE_FILES:"]
  producesVariableInfo := [varInfo "orientation_report"
        ["project", "issue_summary", "candidate_files", "notes"]]
  graphContributions := [repository_explored]
}

def seed_001_node1 : WorkflowNode := {
  id := seed_001_nodeId1, name := some "build_reproduction"
  stepType := .task
  reads := [⟨"orientation_report", .TString⟩], writes := [⟨"repro_report", .TString⟩]
  llmInstruction := some "Context from previous step: {{orientation_report}}. Build a reproduction script. OUTPUT_FORMAT:\nREPRO_STATUS: ...\nREPRO_SCRIPT: <absolute path>\nOBSERVED_OUTPUT: ...\nEXPECTED_OUTPUT: ..."
}

def seed_001_semNode1 : SemanticWorkflowNode := {
  baseNode := seed_001_node1
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "orientation_report"

  ]
  postcondVariables := [varIsNonEmptyString "repro_report", varContainsSentinel "repro_report" "REPRO_STATUS:"]
  infoRequires := [info "candidate_files", info "issue_summary"]
  producesVariableInfo := [varInfo "repro_report"
        ["repro_status", "repro_script", "observed_output", "expected_output"]]
  graphContributions := [issue_reproduced]
}

def seed_001_node2 : WorkflowNode := {
  id := seed_001_nodeId2, name := some "repro_check"
  stepType := .conditional
  reads := [⟨"repro_report", .TString⟩], writes := []
  llmInstruction := none
}

def seed_001_condNode2 : SemanticConditionalNode := {
  baseNode := seed_001_node2
  precondVariables := [varIsNonEmptyString "repro_report"]
  postcondVariables := []
  thenTargetId := seed_001_nodeId3
  elseTargetId := seed_001_nodeId4
  thenPostcondVariables := [varIsNonEmptyString "repro_report", varContainsSentinel "repro_report" "could_not_reproduce"]
  elsePostcondVariables := [varIsNonEmptyString "repro_report"]
}
def seed_001_semNode2 : SemanticWorkflowNode := seed_001_condNode2.toSemanticWorkflowNode

def seed_001_node3 : WorkflowNode := {
  id := seed_001_nodeId3
  name := some "reproduction_retry"
  stepType := .task
  reads := [⟨"repro_report", .TString⟩]
  writes := [⟨"repro_report", .TString⟩]
  llmInstruction := some "First reproduction didn't trigger the bug: {{repro_report}}. Try once more. Same OUTPUT_FORMAT:\nREPRO_STATUS: ...\nREPRO_SCRIPT: ...\nOBSERVED_OUTPUT: ...\nEXPECTED_OUTPUT: ..."
}

def seed_001_semNode3 : SemanticWorkflowNode := {
  baseNode := seed_001_node3
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "repro_report"
  ]
  postcondVariables := [varIsNonEmptyString "repro_report"]
  producesVariableInfo := [varInfo "repro_report"
        ["repro_status", "repro_script", "observed_output", "expected_output"]]
  graphContributions := [issue_reproduced]
}

def seed_001_node4 : WorkflowNode := {
  id := seed_001_nodeId4, name := some "reproduction_confirmed"
  stepType := .task
  reads := [⟨"repro_report", .TString⟩], writes := []
  llmInstruction := some "Reproduction already succeeded: {{repro_report}}. Acknowledge briefly with a one-line confirmation."
}

def seed_001_semNode4 : SemanticWorkflowNode := {
  baseNode := seed_001_node4
  precondVariables := [
    varIsNonEmptyString "repro_report"
  ]
  postcondVariables := []
  graphContributions := [issue_reproduced]
}

def seed_001_node5 : WorkflowNode := {
  id := seed_001_nodeId5, name := some "diagnose_root_cause"
  stepType := .task
  reads := [⟨"orientation_report", .TString⟩, ⟨"repro_report", .TString⟩], writes := [⟨"diagnosis", .TString⟩]
  llmInstruction := some "Using orientation: {{orientation_report}} and reproduction: {{repro_report}}. OUTPUT_FORMAT:\nBUG_LOCATION: <file:line>\nROOT_CAUSE: <explanation>\nFILES_TO_MODIFY: <comma list>\nFIX_STRATEGY: <description>\nEDGE_CASES_TO_CHECK: <list>"
}

def seed_001_semNode5 : SemanticWorkflowNode := {
  baseNode := seed_001_node5
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "orientation_report",
    varIsNonEmptyString "repro_report"

  ]
  postcondVariables := [varIsNonEmptyString "diagnosis", varContainsSentinel "diagnosis" "BUG_LOCATION:"]
  infoRequires := [info "repro_script", info "observed_output", info "candidate_files"]
  producesVariableInfo := [varInfo "diagnosis"
        ["bug_location", "root_cause", "files_to_modify", "fix_strategy", "edge_cases_to_check"]]
  graphContributions := [root_cause_identified]
}

def seed_001_node6 : WorkflowNode := {
  id := seed_001_nodeId6, name := some "apply_fix"
  stepType := .task
  reads := [⟨"diagnosis", .TString⟩], writes := [⟨"fix_result", .TString⟩]
  llmInstruction := some "Apply the fix described in diagnosis: {{diagnosis}}. OUTPUT_FORMAT:\nMODIFIED_FILES: <one per line>\nEDIT_SUMMARY: ...\nPOST_FIX_REPRO: <short quote>"
}

def seed_001_semNode6 : SemanticWorkflowNode := {
  baseNode := seed_001_node6
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "diagnosis"

  ]
  postcondVariables := [varIsNonEmptyString "fix_result", varContainsSentinel "fix_result" "MODIFIED_FILES:"]
  infoRequires := [info "bug_location", info "files_to_modify", info "fix_strategy"]
  producesVariableInfo := [varInfo "fix_result"
        ["modified_files", "edit_summary", "post_fix_repro"]]
  graphContributions := [fix_implemented]
}

def seed_001_node7 : WorkflowNode := {
  id := seed_001_nodeId7, name := some "discover_edge_case_list"
  stepType := .task
  reads := [⟨"diagnosis", .TString⟩], writes := [⟨"edge_case_list", .TString⟩]
  llmInstruction := some "Extract EDGE_CASES_TO_CHECK from diagnosis: {{diagnosis}} as a JSON array of short strings. If missing, return []."
}

def seed_001_semNode7 : SemanticWorkflowNode := {
  baseNode := seed_001_node7
  precondVariables := [
    varIsNonEmptyString "diagnosis"

  ]
  postcondVariables := [varIsNonEmptyString "edge_case_list"]
  infoRequires := [info "edge_cases_to_check"]
  graphContributions := [edge_cases_discovered]
}

def seed_001_node8 : WorkflowNode := {
  id := seed_001_nodeId8, name := some "for_each_edge_cases"
  stepType := .whileLoop
  reads := [⟨"edge_case_list", .TString⟩], writes := []
  llmInstruction := none
}

def seed_001_loopNode8 : SemanticLoopNode := {
  baseNode := seed_001_node8
  precondVariables := [varIsNonEmptyString "edge_case_list"]
  postcondVariables := []
  loopInvariant := [
    varIsNonEmptyString "edge_case_list",
    varIsNonEmptyString "fix_result"
    
  ]
  terminationSpec := .finiteCondition ["{edge_case_list}"]
  
  exitPostconditions := [
    varIsNonEmptyString "fix_result"
  ]
  
  executesAtLeastOnce := false
}
def seed_001_semNode8 : SemanticWorkflowNode := seed_001_loopNode8.toSemanticWorkflowNode

def seed_001_node9 : WorkflowNode := {
  id := seed_001_nodeId9
  name := some "probe_edge_case"
  stepType := .task
  reads := [⟨"fix_result", .TString⟩, ⟨"edge_case", .TString⟩]
  writes := []
  llmInstruction := some "Fix applied so far: {{fix_result}}. EDGE CASE: {{edge_case}}. Probe it. Report EDGE_CASE/STATUS/NOTES — but these are never saved."
}

def seed_001_semNode9 : SemanticWorkflowNode := {
  baseNode := seed_001_node9
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_result",
    varNameExists "edge_case"

  ]
  postcondVariables := []
  infoRequires := [info "modified_files"]
  graphContributions := [edge_cases_checked]
}

def seed_001_node10 : WorkflowNode := {
  id := seed_001_nodeId10, name := some "create_and_submit_patch"
  stepType := .task
  reads := [], writes := [⟨"submission_result", .TString⟩]
  llmInstruction := some "Create git diff patch and submit. Run `git diff -- path/to/file1 ... > patch.txt`. Then submit with `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt`."
}

def seed_001_semNode10 : SemanticWorkflowNode := {
  baseNode := seed_001_node10
  precondVariables := [
    varIsValidTool "shell_run",
    
    varIsNonEmptyString "fix_result"

  ]
  postcondVariables := [varIsNonEmptyString "submission_result", varContainsSentinel "submission_result" "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
  infoRequires := [info "modified_files"]
  graphContributions := [patch_submitted]
}

def seed_001Graph : WorkflowGraph := {
  nodes := [seed_001_node0, seed_001_node1, seed_001_node2, seed_001_node3, seed_001_node4, seed_001_node5, seed_001_node6, seed_001_node7, seed_001_node8, seed_001_node9, seed_001_node10]
  edges := [
    .seqEdge seed_001_nodeId0 seed_001_nodeId1,
    .seqEdge seed_001_nodeId1 seed_001_nodeId2,
    
    .branchEdge seed_001_nodeId2 seed_001_nodeId3 seed_001_nodeId4,
    
    .seqEdge seed_001_nodeId3 seed_001_nodeId5,
    .seqEdge seed_001_nodeId4 seed_001_nodeId5,
    .seqEdge seed_001_nodeId5 seed_001_nodeId6,
    .seqEdge seed_001_nodeId6 seed_001_nodeId7,
    .seqEdge seed_001_nodeId7 seed_001_nodeId8,
    
    .loopEdge seed_001_nodeId8 seed_001_nodeId9 seed_001_nodeId10,
    
    .loopBackEdge seed_001_nodeId9 seed_001_nodeId8
  ]
  entry := seed_001_nodeId0
  exits := [seed_001_nodeId10]
  parameters := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩, ⟨"edge_case", .TString⟩]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := seed_001Graph
  for node in g.nodes do
    let name := node.name.getD "(unnamed)"
    IO.println s!"\n--- Node {node.id}: \"{name}\" [{repr node.stepType}] ---"
    IO.println s!"  writesConsistent:   {node.writesConsistent}"
    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"
    for rv in node.reads do
      let fromParam := g.parameters.any (fun p =>
        p.name == rv.name && p.type.compatible rv.type)
      let fromPred := g.nodes.any (fun o =>
        o.id != node.id && g.reachable o.id node.id &&
        o.writes.any (fun w => w.name == rv.name && w.type.compatible rv.type))
      let status := if fromParam || fromPred then "✓" else "✗ UNRESOLVED"
      IO.println s!"    read  \"{rv.name}\" ({repr rv.type}): {status}"
    for wv in node.writes do
      IO.println s!"    write \"{wv.name}\" ({repr wv.type})"

/-
========================================================================
STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS
========================================================================
-/

#eval seed_001Graph.allWritesConsistent
#eval seed_001Graph.allReadResolvable
#eval seed_001Graph.edgesValid
#eval seed_001Graph.entryNodeValid
#eval seed_001Graph.exitNodesValid
#eval seed_001Graph.allExitsReachable
#eval seed_001Graph.noOrphanNodes
#eval seed_001Graph.returnType

/-
========================================================================
STEP 4-5: THEOREMS (Layer 1 — structural)
========================================================================
-/

theorem seed_001_writesConsistent : seed_001Graph.allWritesConsistent = true := by native_decide
theorem seed_001_readsResolvable : seed_001Graph.allReadResolvable = true := by native_decide
theorem seed_001_edgesValid : seed_001Graph.edgesValid = true := by native_decide
theorem seed_001_entryValid : seed_001Graph.entryNodeValid = true := by native_decide
theorem seed_001_exitsValid : seed_001Graph.exitNodesValid = true := by native_decide
theorem seed_001_exitsReachable : seed_001Graph.allExitsReachable = true := by native_decide
theorem seed_001_noOrphans : seed_001Graph.noOrphanNodes = true := by native_decide

def seed_001_paramNode : SemanticWorkflowNode := {
  baseNode := { id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varNameExists "code_path",
    varNameExists "problem_statement",
    varNameExists "regression_test_cmd",
    varNameExists "edge_case",
    varIsValidFilePath "code_path",
    varIsNonEmptyString "problem_statement",
    varIsValidTool "shell_run"
  ]
}

def seed_001_goalSpec : GoalSpecification := {
  originalGoal := "Reproduce the issue described by the PR and produce a git patch that fixes it."
  subGoals := [
    { name := repository_explored
      variableName := "orientation_report"
      requiredPredicate := .isNonEmptyString
      description := "Repo was surveyed, project/candidate files identified."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "repro_report"
      requiredPredicate := .isNonEmptyString
      description := "A reproduction script was built; conditional retry path exists."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := root_cause_identified
      variableName := "diagnosis"
      requiredPredicate := .isNonEmptyString
      description := "Root cause diagnosed with titled BUG_LOCATION/ROOT_CAUSE/FILES_TO_MODIFY/FIX_STRATEGY."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_implemented
      variableName := "fix_result"
      requiredPredicate := .isNonEmptyString
      description := "Fix applied; MODIFIED_FILES titled field published."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := edge_cases_checked
      variableName := "edge_case_list"
      requiredPredicate := .isNonEmptyString
      description := "for_each iterates over discovered edge cases, but the body has NO save_as — per-edge-case findings are lost."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "submission_result"
      requiredPredicate := .containsSubstring "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
      description := "Terminal step submits patch. BAD: reads nothing upstream — needs modified_files but no {{fix_result}} is injected ⇒ the new verifyInformationFlow FAILS for node 10."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] }
  ]
}

def seed_001SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := seed_001Graph
  paramNode := seed_001_paramNode
  semanticNodes := [seed_001_semNode0, seed_001_semNode1, seed_001_semNode2, seed_001_semNode3, seed_001_semNode4, seed_001_semNode5, seed_001_semNode6, seed_001_semNode7, seed_001_semNode8, seed_001_semNode9, seed_001_semNode10]
  loopNodes := [seed_001_loopNode8]
  conditionalNodes := [seed_001_condNode2]
  specInvariant := by decide
  goalSpec := seed_001_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (seed_001SemanticGraph.verifyWorkflowReport (label := "seed_001"))

theorem seed_001_hoare_sound : (seed_001SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem seed_001_info_sound : (seed_001SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

end AgenticKernel.seed_001_layer2_new
