import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates
import AgentVerifier.DynamicVerification.DynamicVerification

namespace AgenticKernel

/- FIX #3: typed sub-goal identities — declared once, referenced (not re-typed)
   in the node graph-fields and the GoalSpecification. -/
namespace passed_workflow_1_v2.SG
  def repository_explored : SubGoalName := ⟨"repository_explored"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def fix_implemented : SubGoalName := ⟨"fix_implemented"⟩
  def fix_verified : SubGoalName := ⟨"fix_verified"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end passed_workflow_1_v2.SG
open passed_workflow_1_v2.SG


/-
================================================================================
STATIC VERIFICATION: passed_workflow_1_v2
Goal: Given a GitHub issue, reproduce it and fix it by producing a minimal git patch
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 5, Entry: 0, Exits: [4]
Semantic layer: READY

  Node   0: step             [READY]  "explore_repository"
          reads:  problem_statement
          writes: (none)
  Node   1: step             [READY]  "reproduce_issue"
          reads:  (none)
          writes: (none)
  Node   2: step             [READY]  "fix_issue"
          reads:  (none)
          writes: (none)
  Node   3: step             [READY]  "verify_fix"
          reads:  regression_test_cmd
          writes: (none)
  Node   4: step             [READY]  "create_patch"
          reads:  (none)
          writes: (none)
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

-- Node IDs
def passed_workflow_1_v2_nodeId0 : NodeId := ⟨0⟩
def passed_workflow_1_v2_nodeId1 : NodeId := ⟨1⟩
def passed_workflow_1_v2_nodeId2 : NodeId := ⟨2⟩
def passed_workflow_1_v2_nodeId3 : NodeId := ⟨3⟩
def passed_workflow_1_v2_nodeId4 : NodeId := ⟨4⟩

-- Node 0: step "explore_repository"
def passed_workflow_1_v2_node0 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId0, name := some "explore_repository"
  stepType := .step
  reads := [⟨"problem_statement", .TString⟩], writes := []
  llmInstruction := some "<pr_description>\nConsider the following PR description:\n{{problem_statement}}\n</pr_description>\n\nYou're a software engineer interacting continuously with a computer by submitting commands.\nYou'll be helping implement necessary changes to meet requirements in the PR description.\nYour task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.\n<IMPORTANT>This is an interactive process where you will think and issue AT LEAST ONE command for every step, see the result, then think and issue your next command(s).</IMPORTANT>\nFor each response:\n1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n2. Provide one or more bash tool calls to execute\n\n<boundaries>\n- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)\n- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n</boundaries>\n\nNow begin. Start by exploring the repository structure at /testbed to understand the codebase, focusing on files and directories most relevant to the issue described in the PR description."
}

-- Semantic Node 0: step "explore_repository"
def passed_workflow_1_v2_semNode0 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node0
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "problem_statement"]
  postcondVariables := [varIsNonEmptyString "repository_understanding"]
  graphContributions := [repository_explored]
  graphImplicitRetries := [repository_explored]
}

-- Node 1: step "reproduce_issue"
def passed_workflow_1_v2_node1 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId1, name := some "reproduce_issue"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now that you've explored the repository, create a script to reproduce the issue described in the PR description.\n\nSteps:\n1. Based on the PR description and the code you've read, write a small reproduction script (e.g. /testbed/reproduce_issue.py or /testbed/reproduce_issue.sh) that demonstrates the bug or failure.\n2. Run the script and confirm the issue is reproducible. Show the error output.\n3. If the issue is not directly reproducible with a simple script (e.g., it's a behavioral or logic error), explain what you observe and how it differs from expected behavior.\n\nRemember:\n- Work in the /testbed directory\n- Use non-interactive commands only\n- Every response MUST include at least one bash tool call"
}

-- Semantic Node 1: step "reproduce_issue"
def passed_workflow_1_v2_semNode1 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node1
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "repository_understanding"]
  postcondVariables := [varIsNonEmptyString "reproduction_evidence"]
  graphContributions := [issue_reproduced]
  graphImplicitRetries := [issue_reproduced]
}

-- Node 2: step "fix_issue"
def passed_workflow_1_v2_node2 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId2, name := some "fix_issue"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Now that you've reproduced the issue, locate the relevant source code and implement a fix.\n\nSteps:\n1. Identify the exact source files and functions that need to be changed\n2. Understand the root cause of the issue by reading the relevant code carefully\n3. Implement a fix that:\n   - Addresses the root cause, not just the symptoms\n   - Is consistent with the existing codebase style and patterns\n   - Is general enough to handle edge cases\n   - Does NOT modify any test files or configuration files (pyproject.toml, setup.cfg, etc.)\n4. Use sed, python scripts, or heredocs to make the edits -- do NOT use interactive editors\n\nRemember:\n- Work in the /testbed directory\n- Every response MUST include at least one bash tool call\n- ONLY modify regular source code files"
}

-- Semantic Node 2: step "fix_issue"
def passed_workflow_1_v2_semNode2 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node2
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "reproduction_evidence", varIsNonEmptyString "repository_understanding"]
  postcondVariables := [varIsNonEmptyString "fix_implementation_evidence"]
  graphContributions := [fix_implemented]
  graphImplicitRetries := [fix_implemented]
}

-- Node 3: step "verify_fix"
def passed_workflow_1_v2_node3 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId3, name := some "verify_fix"
  stepType := .step
  reads := [⟨"regression_test_cmd", .TString⟩], writes := []
  llmInstruction := some "Now verify that your fix resolves the issue.\n\nSteps:\n1. Re-run the reproduction script you created earlier to confirm the issue is fixed\n2. If there is a regression test command available, run it: {{regression_test_cmd}}\n3. Test edge cases to ensure your fix is robust and doesn't break other functionality\n4. If anything fails, go back and refine your fix\n\nRemember:\n- Work in the /testbed directory\n- Every response MUST include at least one bash tool call"
}

-- Semantic Node 3: step "verify_fix"
def passed_workflow_1_v2_semNode3 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node3
  precondVariables := [varIsValidTool "shell_run", varNameExists "regression_test_cmd", varIsNonEmptyString "fix_implementation_evidence", varIsNonEmptyString "reproduction_evidence"]
  postcondVariables := [varIsNonEmptyString "fix_verification_evidence"]
  graphContributions := [fix_verified]
  graphVerifications := [fix_implemented]
  graphImplicitRetries := [fix_verified]
}

-- Node 4: step "create_patch"
def passed_workflow_1_v2_node4 : WorkflowNode := {
  id := passed_workflow_1_v2_nodeId4, name := some "create_patch"
  stepType := .step
  reads := [], writes := []
  llmInstruction := some "Your fix is verified. Now create and submit the final patch.\n\nFollow these steps IN ORDER, with SEPARATE commands:\n\nStep 1: Create the patch file\nRun `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\nDo NOT commit your changes.\n<IMPORTANT>\nThe patch must only contain changes to the specific source files you modified to fix the issue.\nDo not submit file creations or changes to any of the following files:\n- test and reproduction files\n- helper scripts, tests, or tools that you created\n- installation, build, packaging, configuration, or setup scripts\n- binary or compiled files\n</IMPORTANT>\n\nStep 2: Verify your patch\nInspect patch.txt to confirm it only contains your intended changes.\n\nStep 3: Submit (EXACT command required)\nYou MUST use this EXACT command to submit:\n```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n```"
}

-- Semantic Node 4: step "create_patch"
def passed_workflow_1_v2_semNode4 : SemanticWorkflowNode := {
  baseNode := passed_workflow_1_v2_node4
  precondVariables := [varIsValidTool "shell_run", varIsNonEmptyString "fix_implementation_evidence"]
  postcondVariables := [varIsNonEmptyString "patch_submission_evidence"]
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
        (!g.isParallelScopedNode o.id || g.isParallelScopedNode node.id) &&
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
STEP 4-5: THEOREMS
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


/-
========================================================================
STEP 6: SEMANTIC VERIFICATION
========================================================================
-/

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
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.contextContinuity] },
    { name := fix_implemented
      variableName := "fix_implementation_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that source code was modified to fix the issue. Context flows via task chain. unifiedLoopBack PASSES due to markImplicitRetry on task nodes."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.contextContinuity, GraphLevelPredicateKeys.informationSufficiency, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage] },
    { name := fix_verified
      variableName := "fix_verification_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that the fix was verified by rerunning reproduction and regression tests. Context continuity PASSES via task chain."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.contextContinuity] },
    { name := patch_submitted
      variableName := "patch_submission_evidence"
      requiredPredicate := .isNonEmptyString
      description := "Evidence that a git patch was created and submitted. Context flows via task chain but no fail-safe exists."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.contextContinuity, GraphLevelPredicateKeys.failSafe] }
  ]
}

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
}

def passed_workflow_1_v2SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := passed_workflow_1_v2Graph
  paramNode := passed_workflow_1_v2_paramNode
  semanticNodes := [passed_workflow_1_v2_semNode0, passed_workflow_1_v2_semNode1, passed_workflow_1_v2_semNode2, passed_workflow_1_v2_semNode3, passed_workflow_1_v2_semNode4]
  loopNodes := []
  conditionalNodes := []
  goalSpec := passed_workflow_1_v2_goalSpec
  specInvariant := by decide
}

/-
========================================================================
UNIFIED LAYER-2 VERIFICATION  (variables + information flow + goal coverage)
========================================================================
-/

#eval IO.println (passed_workflow_1_v2SemanticGraph.verifyWorkflowReport (label := "passed_workflow_1_v2"))

theorem passed_workflow_1_v2_hoare_sound : (passed_workflow_1_v2SemanticGraph.verifyWorkflow).hoareSound = true := by native_decide
theorem passed_workflow_1_v2_info_sound : (passed_workflow_1_v2SemanticGraph.verifyWorkflow).infoSound = true := by native_decide

open AgenticKernel.Dyn

/- Recorded-run artifacts, relative to `FormalAgentLib/` (the directory
   `lake env lean` runs from). They live under the git-ignored `tmp/`, so a
   fresh clone won't have them — the `#eval` below then prints a note instead
   of failing, and the file still fully type-checks. -/
def reportPath_24870 : System.FilePath :=
  "../tmp/runs/baseline_eval/logs/run_evaluation/glm5_baseline/bedrock__zai.glm-5/matplotlib__matplotlib-24870/report.json"
def eventLogPath_24870 : System.FilePath :=
  "../tmp/runs/passed_workflow_1/matplotlib__matplotlib-24870_agent_events.log"

/- Trajectory pairings: (l2_node_name, trajectory_step_id) — resolved by name. -/
def stepEntries_24870 : List (String × String) :=
  [ ("explore_repository", "1"),
    ("reproduce_issue", "2"),
    ("fix_issue", "3"),
    ("verify_fix", "4"),
    ("create_patch", "5") ]

def execState_24870 : NodeExecutionState := makeExecutionState
  [ ("code_path", "/testbed"),
    ("problem_statement", "[ENH]: Auto-detect bool arrays passed to contour()?\n### Problem\n\nI find myself fairly regularly calling\r\n```python\r\nplt.contour(boolean_2d_array, levels=[.5], ...)\r\n```\r\nto draw the boundary line betw…"),
    ("regression_test_cmd", "pytest -rA"),
    ("shell_run", "<tool>"),
    ("fs_read", "<tool>"),
    ("fs_write", "<tool>"),
    ("repository_understanding", "Agent explored repository structure, found /testbed/lib/matplotlib/contour.py, identified _process_contour_level_args at line 1120 and _contour_args at line 1443, produced solution plan for auto-detecting boolean arrays"),
    ("reproduction_evidence", "Agent created /testbed/reproduce_issue.py and executed it with rc=0, output confirmed issue: Default levels for boolean array are [0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05] instead of [0.5]"),
    ("fix_implementation_evidence", "Agent modified /testbed/lib/matplotlib/contour.py to add boolean array detection in _process_contour_level_args, _contour_args, and _check_xyz methods. However, eval_evidence.resolved=false indicates the fix is incomplete."),
    ("fix_verification_evidence", "Agent ran local tests: 65 passed, 1 skipped in test_contour.py. However, eval_evidence.resolved=false indicates verification was incomplete - the harness test test_bool_autolevel failed."),
    ("patch_submission_evidence", "Agent created patch.txt with git diff -- lib/matplotlib/contour.py. eval_evidence.patch_successfully_applied=true but eval_evidence.resolved=false indicates the patch does not fully resolve the issue.") ]

def stepIdMap_24870 : StepIdMap :=
  ElaipBench.buildStepIdMapByName passed_workflow_1_v2SemanticGraph stepEntries_24870

def dynamicGraph_24870 : DynamicVerificationGraph :=
  ElaipBench.buildDynamicGraphByName passed_workflow_1_v2SemanticGraph execState_24870 stepEntries_24870

/- Per-step LLM judgements (the only LLM-written block). -/
def llmInjections_24870 : List PerPredicateLLMInjection :=
  [ { stepName := "explore_repository", varName := "repository_understanding"
      judgement := makeLLMJudgementResult
        (holds := true) (confidence := 0.85)
        (llmExplanation := "Trace shows successful exploration: 20 tool calls all with rc=0, found /testbed/lib/matplotlib/contour.py, identified _process_contour_level_args at line 1120 and _contour_args at line 1443, produced solution plan for auto-detecting boolean arrays") },
    { stepName := "reproduce_issue", varName := "reproduction_evidence"
      judgement := makeLLMJudgementResult
        (holds := true) (confidence := 0.85)
        (llmExplanation := "Trace shows successful reproduction: /testbed/reproduce_issue.py written, python reproduce_issue.py executed with rc=0, output confirmed issue with Default levels for boolean array: [0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05]") },
    { stepName := "fix_issue", varName := "fix_implementation_evidence"
      judgement := makeLLMJudgementResult
        (holds := false) (confidence := 0.99)
        (llmExplanation := "[GROUND_TRUTH_GATE] eval reports resolved=false; FAIL_TO_PASS still failing (1): lib/matplotlib/tests/test_contour.py::test_bool_autolevel; fix-side variable fix_implementation_evidence cannot hold by definition. (Original judge said holds=False; original explanation: 'GROUND-TRUTH GATE: eval_evidence.resolved=false, failing test test_bool_autolevel in f2p_fail shows fix incomplete. Test expects contourf(z.tolist()).levels.tolist() == [0, .5, 1] but got [0.0, 0.1500')") },
    { stepName := "verify_fix", varName := "fix_verification_evidence"
      judgement := makeLLMJudgementResult
        (holds := false) (confidence := 0.99)
        (llmExplanation := "[GROUND_TRUTH_GATE] eval reports resolved=false; FAIL_TO_PASS still failing (1): lib/matplotlib/tests/test_contour.py::test_bool_autolevel; fix-side variable fix_verification_evidence cannot hold by definition. (Original judge said holds=False; original explanation: 'GROUND-TRUTH GATE: eval_evidence.resolved=false, failing test test_bool_autolevel in f2p_fail shows verification incomplete. Agent local tests passed (65 passed, 1 skipped) but harness test failed: co')") },
    { stepName := "create_patch", varName := "patch_submission_evidence"
      judgement := makeLLMJudgementResult
        (holds := false) (confidence := 0.99)
        (llmExplanation := "[GROUND_TRUTH_GATE] eval reports resolved=false; FAIL_TO_PASS still failing (1): lib/matplotlib/tests/test_contour.py::test_bool_autolevel; fix-side variable patch_submission_evidence cannot hold by definition. (Original judge said holds=False; original explanation: 'GROUND-TRUTH GATE: eval_evidence.resolved=false, failing test test_bool_autolevel in f2p_fail shows patch incomplete. While patch_successfully_applied=true, the test expects contourf(z.tolist()).level')") } ]

#eval! (do
  unless (← reportPath_24870.pathExists) && (← eventLogPath_24870.pathExists) do
    IO.println "[skipped] recorded run artifacts not found under ../tmp/runs/ (they are not shipped with the repo); the verification above still type-checks."
    return
  let report ← SWEBench.InstanceReport.loadFromFile reportPath_24870
  IO.println s!"PER-STEP MOVE ANALYSIS — matplotlib__matplotlib-24870 — report.json resolved={report.resolved}, F2P fail={report.testsStatus.failToPass.failure.length}, P2P fail={report.testsStatus.passToPass.failure.length}"
  let trace ← ExecutionTrace.loadEventLog eventLogPath_24870
  let rules := SWEBench.rulesFromReport report
  let analyses := analyzeAllSteps dynamicGraph_24870 trace stepIdMap_24870 rules llmInjections_24870
  IO.println (renderFullReport dynamicGraph_24870 trace analyses (stepIdMap := stepIdMap_24870) (label := "PER-STEP MOVE ANALYSIS — matplotlib__matplotlib-24870"))
  -- IO.println (layer3ToJson dynamicGraph_24870 trace analyses (stepIdMap := stepIdMap_24870) (label := "PER-STEP MOVE ANALYSIS — matplotlib__matplotlib-24870")).compress
  : IO Unit)

end AgenticKernel
