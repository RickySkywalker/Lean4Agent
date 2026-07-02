/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original passed_workflow_3_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.passed_workflow_3_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace passed_workflow_3_layer2_v2.SG
  def codebase_explored : SubGoalName := ⟨"codebase_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def root_cause_identified : SubGoalName := ⟨"root_cause_identified"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def fix_verified : SubGoalName := ⟨"fix_verified"⟩
  def patch_created : SubGoalName := ⟨"patch_created"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end passed_workflow_3_layer2_v2.SG
open passed_workflow_3_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: passed_workflow_3 (decomposed_SWE_bench.yaml) — v2
Goal: Given a GitHub issue, reproduce the bug, locate the root cause, implement
      a fix, verify it, and submit a patch.
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd',
             'fix_attempt', 'max_fix_attempts']
Nodes: 11, Entry: 0, Exits: [9, 10]
Semantic layer: READY
Graph-level analysis: READY

STRICT ANNOTATION RULES (v2):
  - markImplicitRetry: ALL nodes are `step` → NO markImplicitRetry on ANY node.
    Step nodes have no conversation history and cannot self-correct.
  - markInfoContent: STRICT rules applied. Only for truly structured,
    machine-extractable fields. Free-form descriptions are NOT marked.
    Specifically:
      codebase_analysis: project_description YES, issue_summary YES,
        relevant_files YES, root_cause_hypothesis YES (structured)
      reproduction_result: reproduction_status YES (enum), reproduction_script YES (path),
        observed_error NO (free-form), expected_behavior NO (free-form)
      root_cause_analysis: root_cause NO (free-form), files_to_modify YES (list),
        specific_locations YES (extractable), planned_fix NO (free-form)
      fix_description: modified_files YES (list), changes_made NO (free-form)
      verification_result: verification_status YES (enum), issues_found NO (free-form)
  - unifiedLoopBack: No markImplicitRetry, but nodes 4-6 are inside an explicit
    while loop → isNodeInsideLoop returns true → PASSES via explicit loop path.

  Node   0: step             [READY]  "explore_codebase"
          reads:  problem_statement
          writes: codebase_analysis
  Node   1: step             [READY]  "reproduce_issue"
          reads:  codebase_analysis
          writes: reproduction_result
  Node   2: step             [READY]  "localize_root_cause"
          reads:  codebase_analysis, reproduction_result
          writes: root_cause_analysis
  Node   3: whileLoop        [DET]    "fix_loop"
          reads:  fix_attempt, max_fix_attempts
          writes: (none)
  Node   4: step             [READY]  "implement_fix"
          reads:  root_cause_analysis, retry_notes, codebase_analysis, reproduction_result
          writes: fix_description
  Node   5: step             [READY]  "verify_fix"
          reads:  fix_description
          writes: verification_result
  Node   6: step             [READY]  "check_verification"
          reads:  verification_result
          writes: fix_verified
  Node   7: conditional      [DET]    "check_result"
          reads:  fix_verified
          writes: (none)
  Node   8: step             [READY]  "create_patch"
          reads:  fix_description
          writes: patch_status
  Node   9: step             [READY]  "submit_patch"
          reads:  (none)
          writes: submission_result
  Node  10: step             [READY]  "submit_best_effort"
          reads:  (none)
          writes: submission_result
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def passed_workflow_3_v2_nodeId0 : NodeId := ⟨0⟩
def passed_workflow_3_v2_nodeId1 : NodeId := ⟨1⟩
def passed_workflow_3_v2_nodeId2 : NodeId := ⟨2⟩
def passed_workflow_3_v2_nodeId3 : NodeId := ⟨3⟩
def passed_workflow_3_v2_nodeId4 : NodeId := ⟨4⟩
def passed_workflow_3_v2_nodeId5 : NodeId := ⟨5⟩
def passed_workflow_3_v2_nodeId6 : NodeId := ⟨6⟩
def passed_workflow_3_v2_nodeId7 : NodeId := ⟨7⟩
def passed_workflow_3_v2_nodeId8 : NodeId := ⟨8⟩
def passed_workflow_3_v2_nodeId9 : NodeId := ⟨9⟩
def passed_workflow_3_v2_nodeId10 : NodeId := ⟨10⟩

def passed_workflow_3_v2_node0 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId0, name := some "explore_codebase"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩], writes := [⟨"codebase_analysis", .TString⟩]
  llmInstruction := some "Explore the repository and understand the issue described in the problem statement.\n\n{{problem_statement}}\n\nExplore the repo structure, read relevant source files, identify the area of code related to the issue, and form a hypothesis about the root cause.\n\nReturn a STRUCTURED summary:\n```\nPROJECT: <project name and description>\nISSUE SUMMARY: <concise summary of the reported issue>\nKEY SYMPTOMS: <observable symptoms of the bug>\nRELEVANT FILES: <list of relevant source files>\nROOT CAUSE HYPOTHESIS: <your initial hypothesis>\n```\n"
}

def passed_workflow_3_v2_semNode0 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node0
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "codebase_analysis"]
  producesVariableInfo := [varInfo "codebase_analysis"
        ["project_description", "issue_summary", "relevant_files", "root_cause_hypothesis"]]
  graphContributions := [codebase_explored]
}

def passed_workflow_3_v2_node1 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId1, name := some "reproduce_issue"
  stepType := .task
  reads := [⟨"codebase_analysis", .TString⟩], writes := [⟨"reproduction_result", .TString⟩]
  llmInstruction := some "Based on the codebase analysis, create a reproduction script that demonstrates the bug.\n\n{{codebase_analysis}}\n\nCreate a minimal script that triggers the reported issue. Run it and confirm the bug is present.\n\nReturn a STRUCTURED summary:\n```\nREPRODUCTION STATUS: <REPRODUCED|FAILED_TO_REPRODUCE>\nREPRODUCTION SCRIPT: <path to script>\nOBSERVED ERROR: <error message or incorrect output>\nEXPECTED BEHAVIOR: <what should happen instead>\n```\n"
}

def passed_workflow_3_v2_semNode1 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node1
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "codebase_analysis"
    
  ]
  postcondVariables := [varIsNonEmptyString "reproduction_result"]
  infoRequires := [info "relevant_files"]
  producesVariableInfo := [varInfo "reproduction_result"
        ["reproduction_status", "reproduction_script"]]
  graphContributions := [issue_reproduced]
}

def passed_workflow_3_v2_node2 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId2, name := some "localize_root_cause"
  stepType := .task
  reads := [⟨"codebase_analysis", .TString⟩, ⟨"reproduction_result", .TString⟩], writes := [⟨"root_cause_analysis", .TString⟩]
  llmInstruction := some "Pinpoint the exact source files and code causing the bug.\n\nCodebase analysis:\n{{codebase_analysis}}\n\nReproduction result:\n{{reproduction_result}}\n\nTrace through the code to identify the precise location and mechanism of the bug.\n\nReturn a STRUCTURED analysis:\n```\nROOT CAUSE: <precise description of the bug mechanism>\nFILES TO MODIFY: <list of files that need changes>\nSPECIFIC LOCATIONS: <function names, line ranges>\nPLANNED FIX: <description of the fix strategy>\n```\n"
}

def passed_workflow_3_v2_semNode2 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node2
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "codebase_analysis",
    varIsNonEmptyString "reproduction_result"
    
  ]
  postcondVariables := [varIsNonEmptyString "root_cause_analysis"]
  infoRequires := [info "relevant_files", info "reproduction_status"]
  producesVariableInfo := [varInfo "root_cause_analysis"
        ["files_to_modify", "specific_locations"]]
  graphContributions := [root_cause_identified]
}

def passed_workflow_3_v2_node3 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId3, name := some "fix_loop"
  stepType := .whileLoop
  reads := [⟨"fix_attempt", .TInt⟩, ⟨"max_fix_attempts", .TInt⟩], writes := []
  llmInstruction := none
}

def passed_workflow_3_v2_loopNode3 : SemanticLoopNode := {
  baseNode := passed_workflow_3_v2_node3
  precondVariables := [varIsInt "fix_attempt", varIsInt "max_fix_attempts"]
  postcondVariables := []
  loopInvariant := [
    varIsInt "fix_attempt",
    varIsInt "max_fix_attempts",
    varIsNonEmptyString "root_cause_analysis",
    varIsNonEmptyString "codebase_analysis",
    varIsNonEmptyString "reproduction_result",
    varIsNonEmptyString "retry_notes",
    varNameExists "fix_verified"
    
  ]
  terminationSpec := .finiteCondition ["fix_attempt", "max_fix_attempts"]
  exitPostconditions := [
    
    varIsNonEmptyString "fix_description",
    varIsNonEmptyString "verification_result",
    varIsNonEmptyString "fix_verified",
    varContainsSentinel "fix_verified" "true"

  ]
  
  executesAtLeastOnce := true
}
def passed_workflow_3_v2_semNode3 : SemanticWorkflowNode := passed_workflow_3_v2_loopNode3.toSemanticWorkflowNode

def passed_workflow_3_v2_node4 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId4
  name := some "implement_fix"
  stepType := .task
  reads := [⟨"root_cause_analysis", .TString⟩, ⟨"retry_notes", .TString⟩, ⟨"codebase_analysis", .TString⟩, ⟨"reproduction_result", .TString⟩]
  writes := [⟨"fix_description", .TString⟩]
  llmInstruction := some "Edit source code to fix the bug based on the root cause analysis.\n\nRoot cause analysis:\n{{root_cause_analysis}}\n\nCodebase analysis:\n{{codebase_analysis}}\n\nReproduction result:\n{{reproduction_result}}\n\nRetry notes (from previous attempts):\n{{retry_notes}}\n\nMake the minimal, targeted changes to fix the issue. If this is a retry, use the retry notes to avoid repeating previous mistakes.\n\nReturn:\n```\nMODIFIED FILES: <list of modified files>\nCHANGES MADE: <description of changes>\n```\n"
}

def passed_workflow_3_v2_semNode4 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node4
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "root_cause_analysis",
    varNameExists "retry_notes",
    varIsNonEmptyString "codebase_analysis",
    varIsNonEmptyString "reproduction_result"
    
  ]
  postcondVariables := [varIsNonEmptyString "fix_description"]
  infoRequires := [info "files_to_modify", info "specific_locations"]
  producesVariableInfo := [varInfo "fix_description" ["modified_files"]]
  graphContributions := [fix_implemented]
}

def passed_workflow_3_v2_node5 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId5, name := some "verify_fix"
  stepType := .task
  reads := [⟨"fix_description", .TString⟩], writes := [⟨"verification_result", .TString⟩]
  llmInstruction := some "Verify the fix by re-running the reproduction script and running targeted tests.\n\nFix description:\n{{fix_description}}\n\nRun the reproduction script to check if the bug is fixed. Then run targeted tests for the modified module.\n\nReturn:\n```\nVERIFICATION STATUS: <PASS|FAIL>\nREPRODUCTION RESULT: <result of re-running the reproduction script>\nTARGETED TESTS: <result of running targeted tests>\nISSUES FOUND: <any remaining issues, or 'none'>\n```\n"
}

def passed_workflow_3_v2_semNode5 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node5
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_description"
    
  ]
  postcondVariables := [varIsNonEmptyString "verification_result"]
  infoRequires := [info "modified_files"]
  producesVariableInfo := [varInfo "verification_result" ["verification_status"]]
  graphContributions := [fix_verified]
  graphVerifications := [fix_implemented]
}

def passed_workflow_3_v2_node6 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId6, name := some "check_verification"
  stepType := .task
  reads := [⟨"verification_result", .TString⟩], writes := [⟨"fix_verified", .TString⟩]
  llmInstruction := some "Analyze the verification result and determine if the fix is verified.\n\n{{verification_result}}\n\nReturn exactly one of:\n- FIX_VERIFIED=true  (if all checks pass)\n- FIX_VERIFIED=false (if any check fails)\n"
}

def passed_workflow_3_v2_semNode6 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node6
  precondVariables := [
    varIsNonEmptyString "verification_result"
    
  ]
  postcondVariables := [varIsNonEmptyString "fix_verified"]
  infoRequires := [info "verification_status"]
}

def passed_workflow_3_v2_node7 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId7, name := some "check_result"
  stepType := .conditional
  reads := [⟨"fix_verified", .TString⟩], writes := []
  llmInstruction := none
}

def passed_workflow_3_v2_condNode7 : SemanticConditionalNode := {
  baseNode := passed_workflow_3_v2_node7
  precondVariables := [varNameExists "fix_verified"]
  postcondVariables := [varIsNonEmptyString "fix_description"]
  thenTargetId := passed_workflow_3_v2_nodeId8
  elseTargetId := passed_workflow_3_v2_nodeId10
  thenPostcondVariables := [varIsNonEmptyString "fix_verified", varContainsSentinel "fix_verified" "true"]
  elsePostcondVariables := [varIsNonEmptyString "fix_verified"]
}
def passed_workflow_3_v2_semNode7 : SemanticWorkflowNode := passed_workflow_3_v2_condNode7.toSemanticWorkflowNode

def passed_workflow_3_v2_node8 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId8
  name := some "create_patch"
  stepType := .task
  reads := [⟨"fix_description", .TString⟩]
  writes := [⟨"patch_status", .TString⟩]
  llmInstruction := some "Create the final patch from your verified fix.\n\nFix description:\n{{fix_description}}\n\nCreate a clean git diff patch containing only the source file changes for the fix. Do not include test files, reproduction scripts, or configuration changes.\n\nReturn:\n```\nPATCH FILE: <path to patch>\nPATCH VALID: <true|false>\n```\n"
}

def passed_workflow_3_v2_semNode8 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node8
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_description"
  ]
  postcondVariables := [varIsNonEmptyString "patch_status"]
  graphContributions := [patch_created]
}

def passed_workflow_3_v2_node9 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId9, name := some "submit_patch"
  stepType := .task
  reads := [], writes := [⟨"submission_result", .TString⟩]
  llmInstruction := some "Submit your verified patch using this EXACT command:\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt\n```\n\nCRITICAL: You CANNOT continue working after submission.\n"
}

def passed_workflow_3_v2_semNode9 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node9
  precondVariables := [varIsValidTool "shell_run"]
  postcondVariables := [varIsNonEmptyString "submission_result", varContainsSentinel "submission_result" "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
  graphContributions := [patch_submitted]
}

def passed_workflow_3_v2_node10 : WorkflowNode := {
  id := passed_workflow_3_v2_nodeId10, name := some "submit_best_effort"
  stepType := .task
  reads := [], writes := [⟨"submission_result", .TString⟩]
  llmInstruction := some "The fix could not be fully verified within the retry budget. Submit the best available patch as a best-effort attempt.\n\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt\n```\n\nCRITICAL: You CANNOT continue working after submission.\n"
}

def passed_workflow_3_v2_semNode10 : SemanticWorkflowNode := {
  baseNode := passed_workflow_3_v2_node10
  precondVariables := [varIsValidTool "shell_run"]
  postcondVariables := [varIsNonEmptyString "submission_result", varContainsSentinel "submission_result" "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
  graphContributions := [patch_created, patch_submitted]
}

def passed_workflow_3_v2Graph : WorkflowGraph := {
  nodes := [passed_workflow_3_v2_node0, passed_workflow_3_v2_node1, passed_workflow_3_v2_node2, passed_workflow_3_v2_node3, passed_workflow_3_v2_node4, passed_workflow_3_v2_node5, passed_workflow_3_v2_node6, passed_workflow_3_v2_node7, passed_workflow_3_v2_node8, passed_workflow_3_v2_node9, passed_workflow_3_v2_node10]
  edges := [
    
    .seqEdge passed_workflow_3_v2_nodeId0 passed_workflow_3_v2_nodeId1,
    .seqEdge passed_workflow_3_v2_nodeId1 passed_workflow_3_v2_nodeId2,
    .seqEdge passed_workflow_3_v2_nodeId2 passed_workflow_3_v2_nodeId3,
    
    .loopEdge passed_workflow_3_v2_nodeId3 passed_workflow_3_v2_nodeId4 passed_workflow_3_v2_nodeId7,
    
    .seqEdge passed_workflow_3_v2_nodeId4 passed_workflow_3_v2_nodeId5,
    .seqEdge passed_workflow_3_v2_nodeId5 passed_workflow_3_v2_nodeId6,
    
    .loopBackEdge passed_workflow_3_v2_nodeId6 passed_workflow_3_v2_nodeId3,
    
    .branchEdge passed_workflow_3_v2_nodeId7 passed_workflow_3_v2_nodeId8 passed_workflow_3_v2_nodeId10,
    
    .seqEdge passed_workflow_3_v2_nodeId8 passed_workflow_3_v2_nodeId9
  ]
  entry := passed_workflow_3_v2_nodeId0
  exits := [passed_workflow_3_v2_nodeId9, passed_workflow_3_v2_nodeId10]
  parameters := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩, ⟨"fix_attempt", .TInt⟩, ⟨"max_fix_attempts", .TInt⟩, ⟨"retry_notes", .TString⟩, ⟨"fix_verified", .TString⟩]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := passed_workflow_3_v2Graph
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

#eval passed_workflow_3_v2Graph.allWritesConsistent
#eval passed_workflow_3_v2Graph.allReadResolvable
#eval passed_workflow_3_v2Graph.edgesValid
#eval passed_workflow_3_v2Graph.entryNodeValid
#eval passed_workflow_3_v2Graph.exitNodesValid
#eval passed_workflow_3_v2Graph.allExitsReachable
#eval passed_workflow_3_v2Graph.noOrphanNodes
#eval passed_workflow_3_v2Graph.returnType

/-
========================================================================
STEP 4-5: THEOREMS
========================================================================
-/

theorem passed_workflow_3_v2_writesConsistent : passed_workflow_3_v2Graph.allWritesConsistent = true := by native_decide
theorem passed_workflow_3_v2_readsResolvable : passed_workflow_3_v2Graph.allReadResolvable = true := by native_decide
theorem passed_workflow_3_v2_edgesValid : passed_workflow_3_v2Graph.edgesValid = true := by native_decide
theorem passed_workflow_3_v2_entryValid : passed_workflow_3_v2Graph.entryNodeValid = true := by native_decide
theorem passed_workflow_3_v2_exitsValid : passed_workflow_3_v2Graph.exitNodesValid = true := by native_decide
theorem passed_workflow_3_v2_exitsReachable : passed_workflow_3_v2Graph.allExitsReachable = true := by native_decide
theorem passed_workflow_3_v2_noOrphans : passed_workflow_3_v2Graph.noOrphanNodes = true := by native_decide

theorem passed_workflow_3_v2_seqPath_typeChecks :
    ∃ ctx, typeCheckSequence [passed_workflow_3_v2_node0, passed_workflow_3_v2_node1, passed_workflow_3_v2_node2, passed_workflow_3_v2_node3, passed_workflow_3_v2_node4, passed_workflow_3_v2_node5, passed_workflow_3_v2_node6, passed_workflow_3_v2_node7, passed_workflow_3_v2_node8, passed_workflow_3_v2_node9, passed_workflow_3_v2_node10] [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩, ⟨"fix_attempt", .TInt⟩, ⟨"max_fix_attempts", .TInt⟩, ⟨"retry_notes", .TString⟩, ⟨"fix_verified", .TString⟩] = .ok ctx := by exact ⟨_, rfl⟩

theorem passed_workflow_3_v2_specCount : passed_workflow_3_v2Graph.nodesNeedingSpecs.length = 9 := by native_decide

def passed_workflow_3_v2_paramNode : SemanticWorkflowNode := {
  baseNode := { id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varNameExists "code_path",
    varNameExists "problem_statement",
    varNameExists "regression_test_cmd",
    varNameExists "fix_attempt",
    varNameExists "max_fix_attempts",
    varIsValidFilePath "code_path",
    varIsNonEmptyString "problem_statement",
    varIsNonEmptyString "regression_test_cmd",
    varIsInt "fix_attempt",
    varIsInt "max_fix_attempts",
    
    varIsValidTool "shell_run",
    
    varIsNonEmptyString "retry_notes",
    varNameExists "fix_verified"
  ]
}

def passed_workflow_3_v2_goalSpec : GoalSpecification := {
  originalGoal := "Given a GitHub issue, reproduce the bug, locate the root cause, implement a fix, verify it, and submit a patch"
  subGoals := [
    { name := codebase_explored
      variableName := "codebase_analysis"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the repository structure and issue-relevant source areas have been explored and understood."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "reproduction_result"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the reported bug has been reproduced with a concrete script or procedure."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := root_cause_identified
      variableName := "root_cause_analysis"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the root cause of the bug has been pinpointed to specific files and code locations."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_implemented
      variableName := "fix_description"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a source-code fix addressing the root cause has been implemented."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage, GraphLevelPredicateKeys.failSafe] },
    { name := fix_verified
      variableName := "verification_result"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the implemented fix was verified by re-running reproduction and targeted tests."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack] },
    { name := patch_created
      variableName := "patch_status"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a clean git patch containing only the fix changes was created."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "submission_result"
      requiredPredicate := .containsSubstring "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
      description := "Evidence that the final patch was submitted as the workflow output."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] }
  ]
}

def passed_workflow_3_v2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := passed_workflow_3_v2Graph
  paramNode := passed_workflow_3_v2_paramNode
  semanticNodes := [passed_workflow_3_v2_semNode0, passed_workflow_3_v2_semNode1, passed_workflow_3_v2_semNode2, passed_workflow_3_v2_semNode3, passed_workflow_3_v2_semNode4, passed_workflow_3_v2_semNode5, passed_workflow_3_v2_semNode6, passed_workflow_3_v2_semNode7, passed_workflow_3_v2_semNode8, passed_workflow_3_v2_semNode9, passed_workflow_3_v2_semNode10]
  loopNodes := [passed_workflow_3_v2_loopNode3]
  conditionalNodes := [passed_workflow_3_v2_condNode7]
  specInvariant := by decide
  goalSpec := passed_workflow_3_v2_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (passed_workflow_3_v2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_3_v2"))

theorem passed_workflow_3_v2_hoare_sound : (passed_workflow_3_v2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_3_v2_info_sound : (passed_workflow_3_v2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

end AgenticKernel.passed_workflow_3_layer2_new
