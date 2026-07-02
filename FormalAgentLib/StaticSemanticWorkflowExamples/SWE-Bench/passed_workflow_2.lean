/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original passed_workflow_2_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.passed_workflow_2_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace passed_workflow_2_layer2_v2.SG
  def repository_explored : SubGoalName := ⟨"repository_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def root_cause_identified : SubGoalName := ⟨"root_cause_identified"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def fix_verified : SubGoalName := ⟨"fix_verified"⟩
  def edge_cases_tested : SubGoalName := ⟨"edge_cases_tested"⟩
  def patch_created : SubGoalName := ⟨"patch_created"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end passed_workflow_2_layer2_v2.SG
open passed_workflow_2_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: swe_agent (passed_workflow_2 / claude_write_plan_3) — v2
Goal: Given a GitHub issue, reproduce the bug and fix it by producing a minimal source-code patch
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 9, Entry: 0, Exits: [8]
Semantic layer: READY
Graph-level analysis: READY

KEY CHARACTERISTICS:
  1. Node 0 is `step` type — starts with fresh context, reads parameters
  2. Nodes 1-8 are `task` type — share conversation history as a chain
  3. Node 0 (step) writes NOTHING (no save_as) — its results are lost
     to the task chain. However, problem_statement is a parameter.
  4. The task chain starts at node 1 (explore_codebase). Node 0's
     conversation is NOT visible to node 1.
  5. NO retry loop — if the fix fails, no structural retry mechanism.
     However, task nodes have implicit LLM retry via conversation history.
  6. Within the task chain (nodes 1-8), all info flows via conversation
     history — good context continuity.

STRICT ANNOTATION RULES (v2):
  - markImplicitRetry: ONLY on task nodes (nodes 1-8). Node 0 is step → NO.
  - markInfoContent: NOT used. No save_as variables → all info flows via
    conversation history, not structured extractable fields.
  - Preconditions: honest about specific info needs.

  Node   0: step             [READY]  "present_problem"
          reads:  code_path, problem_statement
          writes: (none)
  Node   1: task             [READY]  "explore_codebase"
          reads:  (none)
          writes: (none)
  Node   2: task             [READY]  "reproduce_issue"
          reads:  (none)
          writes: (none)
  Node   3: task             [READY]  "identify_root_cause"
          reads:  (none)
          writes: (none)
  Node   4: task             [READY]  "implement_fix"
          reads:  (none)
          writes: (none)
  Node   5: task             [READY]  "verify_fix"
          reads:  (none)
          writes: (none)
  Node   6: task             [READY]  "test_edge_cases"
          reads:  regression_test_cmd
          writes: (none)
  Node   7: task             [READY]  "create_patch"
          reads:  (none)
          writes: (none)
  Node   8: task             [READY]  "submit_patch"
          reads:  (none)
          writes: (none)
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def passed_workflow_2_v2_nodeId0 : NodeId := ⟨0⟩
def passed_workflow_2_v2_nodeId1 : NodeId := ⟨1⟩
def passed_workflow_2_v2_nodeId2 : NodeId := ⟨2⟩
def passed_workflow_2_v2_nodeId3 : NodeId := ⟨3⟩
def passed_workflow_2_v2_nodeId4 : NodeId := ⟨4⟩
def passed_workflow_2_v2_nodeId5 : NodeId := ⟨5⟩
def passed_workflow_2_v2_nodeId6 : NodeId := ⟨6⟩
def passed_workflow_2_v2_nodeId7 : NodeId := ⟨7⟩
def passed_workflow_2_v2_nodeId8 : NodeId := ⟨8⟩

def passed_workflow_2_v2_node0 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId0, name := some "present_problem"
  stepType := .task
  reads := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nYou're a software engineer interacting continuously with a computer by submitting commands.\nYou'll be helping implement necessary changes to meet requirements in the PR description.\nYour task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.\n<IMPORTANT>This is an interactive process where you will think and issue AT LEAST ONE command for every step, see the result, then think and issue your next command(s).</IMPORTANT>\n\nFor each response:\n1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n2. Provide one or more bash tool calls to execute\n\nStart by exploring the repository structure to understand the codebase. List the top-level directory structure of /testbed and identify key files related to the issue."
}

def passed_workflow_2_v2_semNode0 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node0
  precondVariables := [varIsValidTool "shell_run", varIsValidFilePath "code_path", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "initial_exploration_evidence"]
  infoRequires := [info "issue_description"]
  producesContextInfo := [info "repository_understanding"]
  graphContributions := [repository_explored]
}

def passed_workflow_2_v2_node1 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId1, name := some "explore_codebase"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Continue exploring the codebase. Based on the PR description, identify and read the most relevant source files.\nUse grep, find, and cat to locate the code areas that need changes.\nFocus on understanding the current behavior that causes the issue."
}

def passed_workflow_2_v2_semNode1 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node1
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement"
  ]
  postcondVariables := [varIsNonEmptyString "codebase_exploration_evidence"]
  producesContextInfo := [info "repository_understanding", info "relevant_files"]
  graphContributions := [repository_explored]
  graphImplicitRetries := [repository_explored]
}

def passed_workflow_2_v2_node2 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId2, name := some "reproduce_issue"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now create a script to reproduce the issue described in the PR description.\nSave the script to /testbed/reproduce_issue.py (or a similarly named script).\nRun the script and confirm that the issue is reproduced.\nShow the error output or incorrect behavior."
}

def passed_workflow_2_v2_semNode2 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node2
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement"
    
  ]
  postcondVariables := [varIsNonEmptyString "issue_reproduction_evidence"]
  infoRequires := [info "repository_understanding"]
  producesContextInfo := [info "reproduction_evidence"]
  graphContributions := [issue_reproduced]
  graphImplicitRetries := [issue_reproduced]
}

def passed_workflow_2_v2_node3 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId3, name := some "identify_root_cause"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Based on the reproduction and your codebase exploration, identify the root cause of the issue.\nRead the specific source files and functions responsible for the bug.\nExplain your analysis and pinpoint the exact lines/functions that need to be modified."
}

def passed_workflow_2_v2_semNode3 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node3
  precondVariables := [
    varIsValidTool "shell_run"
    
  ]
  postcondVariables := [varIsNonEmptyString "root_cause_analysis_evidence"]
  infoRequires := [info "repository_understanding", info "reproduction_evidence"]
  producesContextInfo := [info "root_cause"]
  graphContributions := [root_cause_identified]
  graphImplicitRetries := [root_cause_identified]
}

def passed_workflow_2_v2_node4 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId4, name := some "implement_fix"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Implement the fix for the issue. Edit the source code files to resolve the bug.\nRemember:\n- ONLY modify regular source code files in /testbed\n- DO NOT modify test files, configuration files (pyproject.toml, setup.cfg, etc.)\n- Make targeted, minimal changes that fix the issue without breaking other functionality\n- Ensure your fix is general and consistent with the codebase style"
}

def passed_workflow_2_v2_semNode4 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node4
  precondVariables := [
    varIsValidTool "shell_run"
    
  ]
  postcondVariables := [varIsNonEmptyString "fix_implementation_evidence"]
  infoRequires := [info "root_cause", info "reproduction_evidence"]
  producesContextInfo := [info "fix_implementation_evidence"]
  graphContributions := [fix_implemented]
  graphImplicitRetries := [fix_implemented]
}

def passed_workflow_2_v2_node5 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId5, name := some "verify_fix"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Run the reproduction script again to verify that the fix resolves the issue.\nThe script should now produce the expected/correct behavior instead of the error.\nIf the fix does not work, iterate on your changes."
}

def passed_workflow_2_v2_semNode5 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node5
  precondVariables := [
    varIsValidTool "shell_run"
    
  ]
  postcondVariables := [varIsNonEmptyString "fix_verification_evidence"]
  infoRequires := [info "fix_implementation_evidence", info "reproduction_evidence"]
  producesContextInfo := [info "fix_verification_evidence"]
  graphContributions := [fix_verified]
  graphVerifications := [fix_implemented]
  graphImplicitRetries := [fix_verified]
}

def passed_workflow_2_v2_node6 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId6, name := some "test_edge_cases"
  stepType := .step
  reads := [⟨"regression_test_cmd", .TString⟩], writes := []
  llmInstruction := some "Test edge cases to ensure the fix is robust:\n1. Create additional test scenarios in your reproduction script to cover edge cases\n2. Run the existing test suite if applicable: {{regression_test_cmd}}\n3. Verify that you haven't introduced any regressions\n\nIf any edge case fails, go back and refine your fix."
}

def passed_workflow_2_v2_semNode6 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node6
  precondVariables := [
    varIsValidTool "shell_run",
    varNameExists "regression_test_cmd"
    
  ]
  postcondVariables := [varIsNonEmptyString "edge_case_test_evidence"]
  infoRequires := [info "fix_verification_evidence"]
  producesContextInfo := [info "edge_case_test_evidence"]
  graphContributions := [edge_cases_tested]
  graphVerifications := [fix_verified]
  graphImplicitRetries := [edge_cases_tested]
}

def passed_workflow_2_v2_node7 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId7, name := some "create_patch"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now create the final patch. Follow these steps IN ORDER, with SEPARATE commands:\n\nStep 1: Create the patch file\nRun `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\nDo NOT commit your changes.\n\nStep 2: Verify your patch\nInspect patch.txt to confirm it only contains your intended changes and headers show `--- a/` and `+++ b/` paths."
}

def passed_workflow_2_v2_semNode7 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node7
  precondVariables := [
    varIsValidTool "shell_run"
    
  ]
  postcondVariables := [varIsNonEmptyString "patch_creation_evidence"]
  infoRequires := [info "fix_implementation_evidence"]
  producesContextInfo := [info "patch_creation_evidence"]
  graphContributions := [patch_created]
  graphImplicitRetries := [patch_created]
}

def passed_workflow_2_v2_node8 : WorkflowNode := {
  id := passed_workflow_2_v2_nodeId8, name := some "submit_patch"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Submit your patch using this EXACT command:\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n```\nIf the command fails (nonzero exit status), it will not submit."
}

def passed_workflow_2_v2_semNode8 : SemanticWorkflowNode := {
  baseNode := passed_workflow_2_v2_node8
  precondVariables := [
    varIsValidTool "shell_run"
    
  ]
  postcondVariables := [varIsNonEmptyString "patch_submission_evidence"]
  infoRequires := [info "patch_creation_evidence"]
  producesContextInfo := [info "patch_submission_evidence"]
  graphContributions := [patch_submitted]
  graphImplicitRetries := [patch_submitted]
}

def passed_workflow_2_v2Graph : WorkflowGraph := {
  nodes := [passed_workflow_2_v2_node0, passed_workflow_2_v2_node1, passed_workflow_2_v2_node2, passed_workflow_2_v2_node3, passed_workflow_2_v2_node4, passed_workflow_2_v2_node5, passed_workflow_2_v2_node6, passed_workflow_2_v2_node7, passed_workflow_2_v2_node8]
  edges := [
    .seqEdge passed_workflow_2_v2_nodeId0 passed_workflow_2_v2_nodeId1,
    .seqEdge passed_workflow_2_v2_nodeId1 passed_workflow_2_v2_nodeId2,
    .seqEdge passed_workflow_2_v2_nodeId2 passed_workflow_2_v2_nodeId3,
    .seqEdge passed_workflow_2_v2_nodeId3 passed_workflow_2_v2_nodeId4,
    .seqEdge passed_workflow_2_v2_nodeId4 passed_workflow_2_v2_nodeId5,
    .seqEdge passed_workflow_2_v2_nodeId5 passed_workflow_2_v2_nodeId6,
    .seqEdge passed_workflow_2_v2_nodeId6 passed_workflow_2_v2_nodeId7,
    .seqEdge passed_workflow_2_v2_nodeId7 passed_workflow_2_v2_nodeId8
  ]
  entry := passed_workflow_2_v2_nodeId0
  exits := [passed_workflow_2_v2_nodeId8]
  parameters := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := passed_workflow_2_v2Graph
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

#eval passed_workflow_2_v2Graph.allWritesConsistent
#eval passed_workflow_2_v2Graph.allReadResolvable
#eval passed_workflow_2_v2Graph.edgesValid
#eval passed_workflow_2_v2Graph.entryNodeValid
#eval passed_workflow_2_v2Graph.exitNodesValid
#eval passed_workflow_2_v2Graph.allExitsReachable
#eval passed_workflow_2_v2Graph.noOrphanNodes
#eval passed_workflow_2_v2Graph.returnType

/-
========================================================================
STEP 4-5: THEOREMS (Layer 1 — structural)

All structural checks pass. Reads are resolved by parameters, edges
are valid, no orphan nodes. The graph is well-formed.
========================================================================
-/

theorem passed_workflow_2_v2_writesConsistent : passed_workflow_2_v2Graph.allWritesConsistent = true := by native_decide
theorem passed_workflow_2_v2_readsResolvable : passed_workflow_2_v2Graph.allReadResolvable = true := by native_decide
theorem passed_workflow_2_v2_edgesValid : passed_workflow_2_v2Graph.edgesValid = true := by native_decide
theorem passed_workflow_2_v2_entryValid : passed_workflow_2_v2Graph.entryNodeValid = true := by native_decide
theorem passed_workflow_2_v2_exitsValid : passed_workflow_2_v2Graph.exitNodesValid = true := by native_decide
theorem passed_workflow_2_v2_exitsReachable : passed_workflow_2_v2Graph.allExitsReachable = true := by native_decide
theorem passed_workflow_2_v2_noOrphans : passed_workflow_2_v2Graph.noOrphanNodes = true := by native_decide

theorem passed_workflow_2_v2_seqPath_typeChecks :
    ∃ ctx, typeCheckSequence [passed_workflow_2_v2_node0, passed_workflow_2_v2_node1, passed_workflow_2_v2_node2, passed_workflow_2_v2_node3, passed_workflow_2_v2_node4, passed_workflow_2_v2_node5, passed_workflow_2_v2_node6, passed_workflow_2_v2_node7, passed_workflow_2_v2_node8] [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩] = .ok ctx := by exact ⟨_, rfl⟩

theorem passed_workflow_2_v2_specCount : passed_workflow_2_v2Graph.nodesNeedingSpecs.length = 9 := by native_decide

def passed_workflow_2_v2_paramNode : SemanticWorkflowNode := {
  baseNode := { id := ⟨20041122⟩, name := some "parameters", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varNameExists "code_path",
    varNameExists "problem_statement",
    varNameExists "regression_test_cmd",
    varIsValidFilePath "code_path",
    varIsNonEmptyString "problem_statement",
    varIsValidTool "shell_run"
  ]
  producesVariableInfo := [varInfo "problem_statement" ["issue_description"]]
}

def passed_workflow_2_v2_goalSpec : GoalSpecification := {
  originalGoal := "Given a GitHub issue, reproduce the bug and fix it by producing a minimal source-code patch"
  subGoals := [
    { name := repository_explored
      variableName := "codebase_exploration_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the repository structure was explored and relevant source files were identified. Node 0 (step) does initial exploration but its results are lost. Node 1 (task) re-explores."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "issue_reproduction_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a reproduction script was created and the bug was confirmed. Task chain provides context continuity from exploration (now judged by verifyInformationFlow)."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := root_cause_identified
      variableName := "root_cause_analysis_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the root cause was identified via analysis of reproduction results and codebase exploration."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_implemented
      variableName := "fix_implementation_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that source code was modified to fix the issue. Task chain carries root cause analysis and reproduction context."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage] },
    { name := fix_verified
      variableName := "fix_verification_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the fix was verified by re-running the reproduction script. Task chain carries full implementation context."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := edge_cases_tested
      variableName := "edge_case_test_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that edge cases were tested and regression tests were run."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_created
      variableName := "patch_creation_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a git patch was created containing only the source file changes."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "patch_submission_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the patch was submitted via COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.failSafe] }
  ]
}

def passed_workflow_2_v2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := passed_workflow_2_v2Graph
  paramNode := passed_workflow_2_v2_paramNode
  semanticNodes := [passed_workflow_2_v2_semNode0, passed_workflow_2_v2_semNode1, passed_workflow_2_v2_semNode2, passed_workflow_2_v2_semNode3, passed_workflow_2_v2_semNode4, passed_workflow_2_v2_semNode5, passed_workflow_2_v2_semNode6, passed_workflow_2_v2_semNode7, passed_workflow_2_v2_semNode8]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := passed_workflow_2_v2_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (passed_workflow_2_v2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_2_v2"))

theorem passed_workflow_2_v2_hoare_sound : (passed_workflow_2_v2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_2_v2_info_sound : (passed_workflow_2_v2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

def passed_workflow_2_v2_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.passed_workflow_2_layer2_new
