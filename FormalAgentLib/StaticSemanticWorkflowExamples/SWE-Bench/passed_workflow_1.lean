/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original passed_workflow_1_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.passed_workflow_1_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace passed_workflow_1_layer2_v2.SG
  def repository_explored : SubGoalName := ⟨"repository_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def fix_verified : SubGoalName := ⟨"fix_verified"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end passed_workflow_1_layer2_v2.SG
open passed_workflow_1_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: swe_agent (passed_workflow_1 / claude_write_plan_2) -- v2
Goal: Given a GitHub issue, reproduce it and fix it by producing a minimal git patch
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 5, Entry: 0, Exits: [4]
Semantic layer: READY
Graph-level analysis: READY

KEY CHARACTERISTICS:
  1. ALL nodes are `task` type (conversation history shared between steps)
  2. NO `save_as` variables -- info flows via conversation history, not explicit variables
  3. NO retry loop -- if fix fails, no structural retry mechanism
  4. NO fail-safe -- no fallback submission after exhaustion
  5. Instructions are short and focused

v2 STRICT ANNOTATION RULES applied:
  - markImplicitRetry: YES for ALL nodes (all are task type, can self-correct)
  - markInfoContent: NONE needed (no save_as variables, info flows via conversation)
  - Preconditions: satisfiable via task chain conversation history

  Context continuity: PASS -- task chains propagate all prior context
  Semantic soundness: PASS -- task node preconditions satisfied by accumulated postconditions
  unifiedLoopBack: PASS -- markImplicitRetry on all task nodes
  failSafe: FAIL -- informational, no loop, no fail-safe path

  Node   0: task             [READY]  "explore_repository"
          reads:  problem_statement
          writes: (none)
  Node   1: task             [READY]  "reproduce_issue"
          reads:  (none)
          writes: (none)
  Node   2: task             [READY]  "fix_issue"
          reads:  (none)
          writes: (none)
  Node   3: task             [READY]  "verify_fix"
          reads:  regression_test_cmd
          writes: (none)
  Node   4: task             [READY]  "create_patch"
          reads:  (none)
          writes: (none)
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def passed_workflow_1_v2_nodeId0 : NodeId := ⟨0⟩
def passed_workflow_1_v2_nodeId1 : NodeId := ⟨1⟩
def passed_workflow_1_v2_nodeId2 : NodeId := ⟨2⟩
def passed_workflow_1_v2_nodeId3 : NodeId := ⟨3⟩
def passed_workflow_1_v2_nodeId4 : NodeId := ⟨4⟩

def passed_workflow_1_v2_node0 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId0, name := some "explore_repository"
  stepType := .step
  reads := [⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nYou're a software engineer interacting continuously with a computer by submitting commands.\nYou'll be helping implement necessary changes to meet requirements in the PR description.\nYour task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.\n<IMPORTANT>This is an interactive process where you will think and issue AT LEAST ONE command for every step, see the result, then think and issue your next command(s).</IMPORTANT>\nFor each response:\n1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n2. Provide one or more bash tool calls to execute\n\n<boundaries>\n- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)\n- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n</boundaries>\n\nNow begin. Start by exploring the repository structure at /testbed to understand the codebase, focusing on files and directories most relevant to the issue described in the PR description."
}

def passed_workflow_1_v2_semNode0 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node0
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "repository_understanding"]
  infoRequires := [info "issue_description"]
  producesContextInfo := [info "repository_understanding", info "relevant_files"]
  graphContributions := [repository_explored]
  graphImplicitRetries := [repository_explored]
}

def passed_workflow_1_v2_node1 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId1, name := some "reproduce_issue"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now that you've explored the repository, create a script to reproduce the issue described in the PR description.\n\nSteps:\n1. Based on the PR description and the code you've read, write a small reproduction script (e.g. /testbed/reproduce_issue.py or /testbed/reproduce_issue.sh) that demonstrates the bug or failure.\n2. Run the script and confirm the issue is reproducible. Show the error output.\n3. If the issue is not directly reproducible with a simple script (e.g., it's a behavioral or logic error), explain what you observe and how it differs from expected behavior.\n\nRemember:\n- Work in the /testbed directory\n- Use non-interactive commands only\n- Every response MUST include at least one bash tool call"
}

def passed_workflow_1_v2_semNode1 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node1
  precondVariables := [
    varIsValidTool "shell_run"

  ]
  postcondVariables := [varIsNonEmptyString "reproduction_evidence"]
  infoRequires := [info "repository_understanding"]
  producesContextInfo := [info "reproduction_evidence"]
  graphContributions := [issue_reproduced]
  graphImplicitRetries := [issue_reproduced]
}

def passed_workflow_1_v2_node2 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId2, name := some "fix_issue"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now that you've reproduced the issue, locate the relevant source code and implement a fix.\n\nSteps:\n1. Identify the exact source files and functions that need to be changed\n2. Understand the root cause of the issue by reading the relevant code carefully\n3. Implement a fix that:\n   - Addresses the root cause, not just the symptoms\n   - Is consistent with the existing codebase style and patterns\n   - Is general enough to handle edge cases\n   - Does NOT modify any test files or configuration files (pyproject.toml, setup.cfg, etc.)\n4. Use sed, python scripts, or heredocs to make the edits -- do NOT use interactive editors\n\nRemember:\n- Work in the /testbed directory\n- Every response MUST include at least one bash tool call\n- ONLY modify regular source code files"
}

def passed_workflow_1_v2_semNode2 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node2
  precondVariables := [
    varIsValidTool "shell_run"

  ]
  postcondVariables := [varIsNonEmptyString "fix_implementation_evidence"]
  infoRequires := [info "reproduction_evidence", info "repository_understanding"]
  producesContextInfo := [info "fix_implementation_evidence"]
  graphContributions := [fix_implemented]
  graphImplicitRetries := [fix_implemented]
}

def passed_workflow_1_v2_node3 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId3, name := some "verify_fix"
  stepType := .step
  reads := [⟨"regression_test_cmd", .TString⟩], writes := []
  llmInstruction := some "Now verify that your fix resolves the issue.\n\nSteps:\n1. Re-run the reproduction script you created earlier to confirm the issue is fixed\n2. If there is a regression test command available, run it: {{regression_test_cmd}}\n3. Test edge cases to ensure your fix is robust and doesn't break other functionality\n4. If anything fails, go back and refine your fix\n\nRemember:\n- Work in the /testbed directory\n- Every response MUST include at least one bash tool call"
}

def passed_workflow_1_v2_semNode3 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node3
  precondVariables := [
    varIsValidTool "shell_run",
    varNameExists "regression_test_cmd"

  ]
  postcondVariables := [varIsNonEmptyString "fix_verification_evidence"]
  infoRequires := [info "fix_implementation_evidence", info "reproduction_evidence"]
  producesContextInfo := [info "fix_verification_evidence"]
  graphContributions := [fix_verified]
  graphVerifications := [fix_implemented]
  graphImplicitRetries := [fix_verified]
}

def passed_workflow_1_v2_node4 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId4, name := some "create_patch"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Your fix is verified. Now create and submit the final patch.\n\nFollow these steps IN ORDER, with SEPARATE commands:\n\nStep 1: Create the patch file\nRun `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\nDo NOT commit your changes.\n<IMPORTANT>\nThe patch must only contain changes to the specific source files you modified to fix the issue.\nDo not submit file creations or changes to any of the following files:\n- test and reproduction files\n- helper scripts, tests, or tools that you created\n- installation, build, packaging, configuration, or setup scripts\n- binary or compiled files\n</IMPORTANT>\n\nStep 2: Verify your patch\nInspect patch.txt to confirm it only contains your intended changes.\n\nStep 3: Submit (EXACT command required)\nYou MUST use this EXACT command to submit:\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n```"
}

def passed_workflow_1_v2_semNode4 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node4
  precondVariables := [
    varIsValidTool "shell_run"

  ]
  postcondVariables := [varIsNonEmptyString "patch_submission_evidence"]
  infoRequires := [info "fix_implementation_evidence"]
  producesContextInfo := [info "patch_submission_evidence"]
  graphContributions := [patch_submitted]
  graphImplicitRetries := [patch_submitted]
}

def passed_workflow_1_v2Graph : WorkflowGraph := {
  nodes := [passed_workflow_1_v2_node0, passed_workflow_1_v2_node1, passed_workflow_1_v2_node2, passed_workflow_1_v2_node3, passed_workflow_1_v2_node4]
  edges := [
    .seqEdge passed_workflow_1_v2_nodeId0 passed_workflow_1_v2_nodeId1,
    .seqEdge passed_workflow_1_v2_nodeId1 passed_workflow_1_v2_nodeId2,
    .seqEdge passed_workflow_1_v2_nodeId2 passed_workflow_1_v2_nodeId3,
    .seqEdge passed_workflow_1_v2_nodeId3 passed_workflow_1_v2_nodeId4
  ]
  entry := passed_workflow_1_v2_nodeId0
  exits := [passed_workflow_1_v2_nodeId4]
  parameters := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := passed_workflow_1_v2Graph
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

#eval passed_workflow_1_v2Graph.allWritesConsistent
#eval passed_workflow_1_v2Graph.allReadResolvable
#eval passed_workflow_1_v2Graph.edgesValid
#eval passed_workflow_1_v2Graph.entryNodeValid
#eval passed_workflow_1_v2Graph.exitNodesValid
#eval passed_workflow_1_v2Graph.allExitsReachable
#eval passed_workflow_1_v2Graph.noOrphanNodes
#eval passed_workflow_1_v2Graph.returnType

/-
========================================================================
STEP 4-5: THEOREMS (Layer 1 -- structural)

All structural checks pass because the graph is well-formed:
reads are resolved by parameters, edges are valid, no orphan nodes.
========================================================================
-/

theorem passed_workflow_1_v2_writesConsistent : passed_workflow_1_v2Graph.allWritesConsistent = true := by native_decide
theorem passed_workflow_1_v2_readsResolvable : passed_workflow_1_v2Graph.allReadResolvable = true := by native_decide
theorem passed_workflow_1_v2_edgesValid : passed_workflow_1_v2Graph.edgesValid = true := by native_decide
theorem passed_workflow_1_v2_entryValid : passed_workflow_1_v2Graph.entryNodeValid = true := by native_decide
theorem passed_workflow_1_v2_exitsValid : passed_workflow_1_v2Graph.exitNodesValid = true := by native_decide
theorem passed_workflow_1_v2_exitsReachable : passed_workflow_1_v2Graph.allExitsReachable = true := by native_decide
theorem passed_workflow_1_v2_noOrphans : passed_workflow_1_v2Graph.noOrphanNodes = true := by native_decide

theorem passed_workflow_1_v2_seqPath_typeChecks :
    ∃ ctx, typeCheckSequence [passed_workflow_1_v2_node0, passed_workflow_1_v2_node1, passed_workflow_1_v2_node2, passed_workflow_1_v2_node3, passed_workflow_1_v2_node4] [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩] = .ok ctx := by exact ⟨_, rfl⟩

theorem passed_workflow_1_v2_specCount : passed_workflow_1_v2Graph.nodesNeedingSpecs.length = 5 := by native_decide

def passed_workflow_1_v2_paramNode : SemanticWorkflowNode := {
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

def passed_workflow_1_v2_goalSpec : GoalSpecification := {
  originalGoal := "Given a GitHub issue, reproduce it and fix it by producing a minimal git patch"
  subGoals := [
    { name := repository_explored
      variableName := "repository_understanding"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the repository structure was explored and relevant source files were identified based on the GitHub issue."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "reproduction_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a reproduction script was created and the bug was reproduced. Context continuity PASSES because task chain provides conversation history."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_implemented
      variableName := "fix_implementation_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that source code was modified to fix the issue. Context flows via task chain. unifiedLoopBack PASSES due to markImplicitRetry on task nodes."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage] },
    { name := fix_verified
      variableName := "fix_verification_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the fix was verified by rerunning reproduction and regression tests. Context continuity PASSES via task chain."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "patch_submission_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a git patch was created and submitted. Context flows via task chain but no fail-safe exists."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.failSafe] }
  ]
}

def passed_workflow_1_v2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := passed_workflow_1_v2Graph
  paramNode := passed_workflow_1_v2_paramNode
  semanticNodes := [passed_workflow_1_v2_semNode0, passed_workflow_1_v2_semNode1, passed_workflow_1_v2_semNode2, passed_workflow_1_v2_semNode3, passed_workflow_1_v2_semNode4]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := passed_workflow_1_v2_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (passed_workflow_1_v2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_1_v2"))

theorem passed_workflow_1_v2_hoare_sound : (passed_workflow_1_v2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_1_v2_info_sound : (passed_workflow_1_v2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

def passed_workflow_1_v2_paramNodeId : NodeId := ⟨20041122⟩

end AgenticKernel.passed_workflow_1_layer2_new
