/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original failed_workflow_1_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.failed_workflow_1_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace failed_workflow_1_layer2_v2.SG
  def repository_explored : SubGoalName := ⟨"repository_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def fix_verified : SubGoalName := ⟨"fix_verified"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end failed_workflow_1_layer2_v2.SG
open failed_workflow_1_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: swe_agent (failed_workflow_1 / claude_write_plan_1) — v2 STRICT
Goal: Given a GitHub issue, reproduce the bug and fix it by modifying source code, then submit a patch
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 5, Entry: 0, Exits: [4]
Semantic layer: READY
Graph-level analysis: READY

STRICT ANNOTATION RULES APPLIED:
  R1: markImplicitRetry → ONLY for task nodes. ALL nodes here are step → NONE used.
  R2: markInfoContent → ONLY for structured extractable fields. NO save_as → NONE in postconditions.
  R3: Preconditions honestly demand specific info aspects from predecessors.

KEY PROBLEMS:
  1. ALL nodes are `step` type (fresh context each time, no conversation history)
  2. NO `save_as` variables — nothing is passed between steps
  3. NO retry loop — if fix fails, no way to go back
  4. Each step must re-explore the codebase from scratch
  5. verify_fix has NO info about what implement_fix actually changed

  Node   0: step             [READY]  "setup_and_explore"
          reads:  code_path, problem_statement
          writes: (none)
  Node   1: step             [READY]  "reproduce_issue"
          reads:  problem_statement
          writes: (none)
  Node   2: step             [READY]  "implement_fix"
          reads:  problem_statement
          writes: (none)
  Node   3: step             [READY]  "verify_fix"
          reads:  problem_statement, regression_test_cmd
          writes: (none)
  Node   4: step             [READY]  "submit_patch"
          reads:  (none)
          writes: (none)
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def failed_workflow_1_nodeId0 : NodeId := ⟨0⟩
def failed_workflow_1_nodeId1 : NodeId := ⟨1⟩
def failed_workflow_1_nodeId2 : NodeId := ⟨2⟩
def failed_workflow_1_nodeId3 : NodeId := ⟨3⟩
def failed_workflow_1_nodeId4 : NodeId := ⟨4⟩

def failed_workflow_1_node0 : WorkflowNode := {
  id := failed_workflow_1_nodeId0, name := some "setup_and_explore"
  stepType := .task
  reads := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nYou're a software engineer interacting continuously with a computer by submitting commands.\nYou'll be helping implement necessary changes to meet requirements in the PR description.\nYour task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.\n<IMPORTANT>This is an interactive process where you will think and issue AT LEAST ONE command for every step, see the result, then think and issue your next command(s).</IMPORTANT>\n\nFor each response:\n1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n2. Provide one or more bash tool calls to execute\n\nIMPORTANT BOUNDARIES:\n- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)\n- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n\nBegin by exploring the repository structure to understand the codebase. Identify the relevant source files that may need to be changed based on the PR description.\n\nStart now. Explore the repository at {{code_path}} to understand the project structure, find relevant files, and understand the codebase organization."
}

def failed_workflow_1_semNode0 : SemanticWorkflowNode := {
  baseNode := failed_workflow_1_node0
  precondVariables := [varIsValidTool "shell_run", varIsValidFilePath "code_path", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "repository_exploration_evidence"]
  graphContributions := [repository_explored]
}

def failed_workflow_1_node1 : WorkflowNode := {
  id := failed_workflow_1_nodeId1, name := some "reproduce_issue"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nBased on your exploration of the codebase, now create a script to reproduce the issue described in the PR description. Write a small Python (or appropriate language) script that demonstrates the bug.\n\nSteps:\n1. Create a reproduction script at /testbed/reproduce_issue.py (or appropriate extension)\n2. Run the script to confirm the issue exists\n3. Analyze the error output to understand the root cause\n\nIMPORTANT:\n- The working directory for all commands is /testbed\n- Directory or environment variable changes are not persistent\n- Prefix commands with `cd /testbed && ...`\n- Your response MUST include AT LEAST ONE bash tool call"
}

def failed_workflow_1_semNode1 : SemanticWorkflowNode := {
  baseNode := failed_workflow_1_node1
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement"

  ]
  postcondVariables := [varIsNonEmptyString "issue_reproduction_evidence"]
  infoRequires := [info "relevant_files", info "project_structure"]
  graphContributions := [issue_reproduced]
}

def failed_workflow_1_node2 : WorkflowNode := {
  id := failed_workflow_1_nodeId2, name := some "implement_fix"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nNow that you've reproduced the issue and understand the root cause, implement a fix.\n\nFollow this workflow:\n1. Identify the exact source file(s) and location(s) that need to be modified\n2. Understand the surrounding code logic before making changes\n3. Implement the minimal, targeted fix that addresses the issue\n4. Make sure your fix is general and consistent with the existing codebase patterns\n\nIMPORTANT BOUNDARIES:\n- MODIFY: Regular source code files in /testbed\n- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n- Use `sed`, `python -c`, or heredoc to edit files (no interactive editors)\n- Your response MUST include AT LEAST ONE bash tool call"
}

def failed_workflow_1_semNode2 : SemanticWorkflowNode := {
  baseNode := failed_workflow_1_node2
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement",
    
    varIsNonEmptyString "issue_reproduction_evidence"

  ]
  postcondVariables := [varIsNonEmptyString "fix_implementation_evidence"]
  infoRequires := [info "relevant_files"]
  graphContributions := [fix_implemented]
}

def failed_workflow_1_node3 : WorkflowNode := {
  id := failed_workflow_1_nodeId3, name := some "verify_fix"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nVerify your fix works correctly:\n1. Run your reproduction script again to confirm the issue is resolved\n2. Test edge cases to ensure your fix is robust and doesn't introduce regressions\n3. If a regression test command is available ({{regression_test_cmd}}), run it\n4. If the fix doesn't work, iterate: analyze what went wrong, adjust, and re-test\n\nIMPORTANT:\n- The working directory for all commands is /testbed\n- Directory or environment variable changes are not persistent\n- Prefix commands with `cd /testbed && ...`\n- Your response MUST include AT LEAST ONE bash tool call"
}

def failed_workflow_1_semNode3 : SemanticWorkflowNode := {
  baseNode := failed_workflow_1_node3
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement",
    varNameExists "regression_test_cmd",
    
    varIsNonEmptyString "fix_implementation_evidence",
    
    varIsNonEmptyString "issue_reproduction_evidence"
  ]
  postcondVariables := [varIsNonEmptyString "fix_verification_evidence"]
  graphContributions := [fix_verified]
  graphVerifications := [fix_implemented]
}

def failed_workflow_1_node4 : WorkflowNode := {
  id := failed_workflow_1_nodeId4, name := some "submit_patch"
  stepType := .task
  reads := [], writes := []
  llmInstruction := some "Your fix has been verified. Now submit your changes as a git patch.\n\nFollow these steps IN ORDER, with SEPARATE commands:\n\nStep 1: Create the patch file\nRun `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\nDo NOT commit your changes.\n<IMPORTANT>\nThe patch must only contain changes to the specific source files you modified to fix the issue.\nDo not submit file creations or changes to any of the following files:\n- test and reproduction files (e.g., reproduce_issue.py)\n- helper scripts, tests, or tools that you created\n- installation, build, packaging, configuration, or setup scripts\n- binary or compiled files\n</IMPORTANT>\n\nStep 2: Verify your patch\nInspect patch.txt to confirm it only contains your intended changes.\n\nStep 3: Submit (EXACT command required)\nYou MUST use this EXACT command to submit:\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n```"
}

def failed_workflow_1_semNode4 : SemanticWorkflowNode := {
  baseNode := failed_workflow_1_node4
  precondVariables := [
    varIsValidTool "shell_run",
    
    varIsNonEmptyString "fix_implementation_evidence"
  ]
  postcondVariables := [varIsNonEmptyString "patch_submission_evidence"]
  graphContributions := [patch_submitted]
}

def failed_workflow_1Graph : WorkflowGraph := {
  nodes := [failed_workflow_1_node0, failed_workflow_1_node1, failed_workflow_1_node2, failed_workflow_1_node3, failed_workflow_1_node4]
  edges := [
    .seqEdge failed_workflow_1_nodeId0 failed_workflow_1_nodeId1,
    .seqEdge failed_workflow_1_nodeId1 failed_workflow_1_nodeId2,
    .seqEdge failed_workflow_1_nodeId2 failed_workflow_1_nodeId3,
    .seqEdge failed_workflow_1_nodeId3 failed_workflow_1_nodeId4
  ]
  entry := failed_workflow_1_nodeId0
  exits := [failed_workflow_1_nodeId4]
  parameters := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := failed_workflow_1Graph
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

#eval failed_workflow_1Graph.allWritesConsistent
#eval failed_workflow_1Graph.allReadResolvable
#eval failed_workflow_1Graph.edgesValid
#eval failed_workflow_1Graph.entryNodeValid
#eval failed_workflow_1Graph.exitNodesValid
#eval failed_workflow_1Graph.allExitsReachable
#eval failed_workflow_1Graph.noOrphanNodes
#eval failed_workflow_1Graph.returnType

/-
========================================================================
STEP 4-5: THEOREMS (Layer 1 — structural)

All structural checks pass because the graph is well-formed:
reads are resolved by parameters, edges are valid, no orphan nodes.
The PROBLEMS with this plan are semantic, not structural.
========================================================================
-/

theorem failed_workflow_1_writesConsistent : failed_workflow_1Graph.allWritesConsistent = true := by native_decide
theorem failed_workflow_1_readsResolvable : failed_workflow_1Graph.allReadResolvable = true := by native_decide
theorem failed_workflow_1_edgesValid : failed_workflow_1Graph.edgesValid = true := by native_decide
theorem failed_workflow_1_entryValid : failed_workflow_1Graph.entryNodeValid = true := by native_decide
theorem failed_workflow_1_exitsValid : failed_workflow_1Graph.exitNodesValid = true := by native_decide
theorem failed_workflow_1_exitsReachable : failed_workflow_1Graph.allExitsReachable = true := by native_decide
theorem failed_workflow_1_noOrphans : failed_workflow_1Graph.noOrphanNodes = true := by native_decide

theorem failed_workflow_1_seqPath_typeChecks :
    ∃ ctx, typeCheckSequence [failed_workflow_1_node0, failed_workflow_1_node1, failed_workflow_1_node2, failed_workflow_1_node3, failed_workflow_1_node4] [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩, ⟨"regression_test_cmd", .TString⟩] = .ok ctx := by exact ⟨_, rfl⟩

theorem failed_workflow_1_specCount : failed_workflow_1Graph.nodesNeedingSpecs.length = 5 := by native_decide

def failed_workflow_1_paramNode : SemanticWorkflowNode := {
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
}

def failed_workflow_1_goalSpec : GoalSpecification := {
  originalGoal := "Given a GitHub issue, reproduce the bug and fix it by modifying source code, then submit a patch"
  subGoals := [
    { name := repository_explored
      variableName := "repository_exploration_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the repository structure was explored and relevant source files were identified based on the GitHub issue."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "issue_reproduction_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a reproduction script was created and the bug was reproduced. reproduce_issue (a step node) needs relevant_files + project_structure from the prior exploration; as a step with no save_as and no context, those are MISSING ⇒ the new verifyInformationFlow FAILS for this node."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_implemented
      variableName := "fix_implementation_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that source code was modified to fix the issue. implement_fix (a step node) needs relevant_files, which is MISSING (no save_as, no context) ⇒ verifyInformationFlow FAILS. Also needs retry capability, which is MISSING."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage] },
    { name := fix_verified
      variableName := "fix_verification_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the fix was verified. Requires knowledge of what was fixed (step type, no save_as from implement_fix)."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "patch_submission_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a git patch was created and submitted. Requires knowledge of modified files (step type, no save_as)."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.failSafe] }
  ]
}

def failed_workflow_1SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := failed_workflow_1Graph
  paramNode := failed_workflow_1_paramNode
  semanticNodes := [failed_workflow_1_semNode0, failed_workflow_1_semNode1, failed_workflow_1_semNode2, failed_workflow_1_semNode3, failed_workflow_1_semNode4]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := failed_workflow_1_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (failed_workflow_1SemanticGraph.verifyWorkflowReport (label := "failed_workflow_1"))

theorem failed_workflow_1_hoare_sound : (failed_workflow_1SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem failed_workflow_1_info_sound : (failed_workflow_1SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

end AgenticKernel.failed_workflow_1_layer2_new
