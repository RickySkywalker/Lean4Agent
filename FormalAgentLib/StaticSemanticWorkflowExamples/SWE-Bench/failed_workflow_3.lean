/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.
   Graph contributions/verifications/retries and information flow now live on
   the semantic nodes; the goal spec is embedded in the graph; one
   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`
   annotations were dropped in porting — see the original seed_004_layer2_v2.lean. -/

import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel.seed_004_layer2_new

/- FIX #3: typed sub-goal identities. Each sub-goal name is declared once below as a
   `SubGoalName` constant and referenced (not re-typed) in the node markers and the
   `GoalSpecification`, so a typo is a compile error instead of a silent NONE. -/
namespace seed_004_layer2_v2.SG
  def repository_oriented : SubGoalName := ⟨"repository_oriented"⟩
  def candidates_located : SubGoalName := ⟨"candidates_located"⟩
  def candidates_inspected : SubGoalName := ⟨"candidates_inspected"⟩
  def issue_reproduced : SubGoalName := ⟨"issue_reproduced"⟩
  def strategy_chosen : SubGoalName := ⟨"strategy_chosen"⟩
  def fix_applied : SubGoalName := ⟨"fix_applied"⟩
  def post_fix_verified : SubGoalName := ⟨"post_fix_verified"⟩
  def fix_adjusted : SubGoalName := ⟨"fix_adjusted"⟩
  def edge_cases_checked : SubGoalName := ⟨"edge_cases_checked"⟩
  def patch_submitted : SubGoalName := ⟨"patch_submitted"⟩
end seed_004_layer2_v2.SG
open seed_004_layer2_v2.SG

/-
================================================================================
STATIC VERIFICATION: swe_agent_triage_and_fix (seed_004) — v2 STRICT
Source: Verifier/failed_workflow_playground/samples/seed_004.yaml
Goal: Reproduce the issue described by the PR and produce a git patch that fixes it.
Parameters: ['code_path', 'problem_statement', 'regression_test_cmd']
Nodes: 19, Entry: 0, Exits: [18]
Semantic layer: READY
Graph-level analysis: READY

Triage awareness (fail, high): titled sub-field demands without structural
producers; for_each body has no save_as (results lost); one-shot
adjust_fix_once without re-verification; stale post_fix_verification read
after adjustment.

STRICT ANNOTATION RULES APPLIED:
  R1: markImplicitRetry → ONLY for task nodes. ALL LLM nodes here are `step`
      / `discover` / `synthesize` → NONE used.
  R2: markInfoContent calibration:
      - repo_overview (titled repo_layout/main_package/build_system/skim_notes) → KEEP
      - candidate_files_report (titled CANDIDATE_FILES/PRIMARY_SUSPECT) → KEEP
      - reproduction_report (titled REPRO_SCRIPT/REPRO_STATUS) → KEEP
      - fix_strategy (titled strategy/target_file/target_symbols) → KEEP
      - post_fix_verification (titled REPRO_AFTER_FIX/TARGETED_TEST) → KEEP
      - fix_application / fix_adjustment / edge_case_report / submission_result
        → free-form diffs or prose → OMIT
  R3: Preconditions honestly demand specific info aspects from predecessors.

KEY PROBLEMS (semantic + structural):
  1. `for_each` body step `inspect_candidate` has NO save_as — scouting results
     are lost to downstream nodes (choose_fix_strategy re-reads only the report).
  2. `adjust_fix_once` runs exactly once and flows straight into
     edge_case_plan WITHOUT a second verify step — the repro result after
     the adjustment is never recorded.
  3. edge_case_plan / create_and_submit_patch read post_fix_verification
     semantics indirectly via fix_adjustment, but post_fix_verification is
     STALE (it reflects the pre-adjustment state). No fresh verification
     variable is produced after adjust_fix_once.
  4. All LLM nodes are `step` (fresh context each time) — no implicit
     retry via conversation history.

  Node   0: step             [READY]  "orient_and_scan"
          reads:  code_path, problem_statement
          writes: repo_overview
  Node   1: step             [READY]  "locate_candidate_files"
          reads:  repo_overview
          writes: candidate_files_report
  Node   2: discover         [READY]  "candidate_file_list"
          reads:  (from candidate_files_report)
          writes: candidate_file_list
  Node   3: forEachLoop      [DET]    "for_each_candidate"
          reads:  candidate_file_list
          writes: (none)
  Node   4: step             [READY]  "inspect_candidate" (loop body, NO save_as)
          reads:  candidate_path
          writes: (none)
  Node   5: step             [READY]  "build_reproduction"
          reads:  problem_statement
          writes: reproduction_report
  Node   6: step             [READY]  "choose_fix_strategy"
          reads:  candidate_files_report, reproduction_report
          writes: fix_strategy
  Node   7: switchBranch     [DET]    "dispatch_fix_strategy"
          reads:  fix_strategy
          writes: (none)
  Node   8: step             [READY]  "apply_logic_fix"
          reads:  fix_strategy, reproduction_report
          writes: fix_application
  Node   9: step             [READY]  "apply_boundary_guard"
          reads:  fix_strategy, reproduction_report
          writes: fix_application
  Node  10: step             [READY]  "apply_small_refactor"
          reads:  fix_strategy, reproduction_report
          writes: fix_application
  Node  11: step             [READY]  "apply_data_model_fix"
          reads:  fix_strategy, reproduction_report
          writes: fix_application
  Node  12: step             [READY]  "apply_generic_fix" (default case)
          reads:  problem_statement
          writes: fix_application
  Node  13: step             [READY]  "verify_reproduction_post_fix"
          reads:  regression_test_cmd
          writes: post_fix_verification
  Node  14: conditional      [DET]    "if_reproduction_still_failing"
          reads:  post_fix_verification
          writes: (none)
  Node  15: step             [READY]  "adjust_fix_once" (then branch, ONE SHOT)
          reads:  post_fix_verification
          writes: fix_adjustment
  Node  16: step             [READY]  "note_passing_verification" (else branch)
          reads:  (none)
          writes: fix_adjustment
  Node  17: synthesize       [READY]  "edge_case_plan"
          reads:  fix_strategy, fix_application, post_fix_verification,
                  fix_adjustment
          writes: edge_case_report
  Node  18: step             [READY]  "create_and_submit_patch"
          reads:  (none)
          writes: submission_result
================================================================================
-/

/-
========================================================================
STEP 1: WORKFLOW GRAPH
========================================================================
-/

def seed_004_nodeId0  : NodeId := ⟨0⟩
def seed_004_nodeId1  : NodeId := ⟨1⟩
def seed_004_nodeId2  : NodeId := ⟨2⟩
def seed_004_nodeId3  : NodeId := ⟨3⟩
def seed_004_nodeId4  : NodeId := ⟨4⟩
def seed_004_nodeId5  : NodeId := ⟨5⟩
def seed_004_nodeId6  : NodeId := ⟨6⟩
def seed_004_nodeId7  : NodeId := ⟨7⟩
def seed_004_nodeId8  : NodeId := ⟨8⟩
def seed_004_nodeId9  : NodeId := ⟨9⟩
def seed_004_nodeId10 : NodeId := ⟨10⟩
def seed_004_nodeId11 : NodeId := ⟨11⟩
def seed_004_nodeId12 : NodeId := ⟨12⟩
def seed_004_nodeId13 : NodeId := ⟨13⟩
def seed_004_nodeId14 : NodeId := ⟨14⟩
def seed_004_nodeId15 : NodeId := ⟨15⟩
def seed_004_nodeId16 : NodeId := ⟨16⟩
def seed_004_nodeId17 : NodeId := ⟨17⟩
def seed_004_nodeId18 : NodeId := ⟨18⟩

def seed_004_node0 : WorkflowNode := {
  id := seed_004_nodeId0, name := some "orient_and_scan"
  stepType := .task
  reads := [⟨"code_path", .TString⟩, ⟨"problem_statement", .TString⟩]
  writes := [⟨"repo_overview", .TString⟩]
  llmInstruction := some "Do a shallow orientation pass over /testbed: list top-level layout, identify main source package, skim README.\nOUTPUT_FORMAT:\nrepo_layout: ...\nmain_package: ...\nbuild_system: ...\nskim_notes: ..."
}

def seed_004_semNode0 : SemanticWorkflowNode := {
  baseNode := seed_004_node0
  precondVariables := [
    varIsValidTool "shell_run",
    varIsValidFilePath "code_path",
    varIsNonEmptyString "problem_statement"
  ]
  postcondVariables := [varIsNonEmptyString "repo_overview"]
  producesVariableInfo := [varInfo "repo_overview"
        ["repo_layout", "main_package", "build_system", "skim_notes"]]
  graphContributions := [repository_oriented]
}

def seed_004_node1 : WorkflowNode := {
  id := seed_004_nodeId1, name := some "locate_candidate_files"
  stepType := .task
  reads := [⟨"repo_overview", .TString⟩]
  writes := [⟨"candidate_files_report", .TString⟩]
  llmInstruction := some "Using the PR description and orientation, find source files most likely responsible.\nReturn:\nCANDIDATE_FILES:\n- <path_1>: <reason>\nPRIMARY_SUSPECT: <single path>"
}

def seed_004_semNode1 : SemanticWorkflowNode := {
  baseNode := seed_004_node1
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement",
    varIsNonEmptyString "repo_overview"

  ]
  postcondVariables := [varIsNonEmptyString "candidate_files_report", varContainsSentinel "candidate_files_report" "PRIMARY_SUSPECT:"]
  infoRequires := [info "main_package"]
  producesVariableInfo := [varInfo "candidate_files_report"
        ["primary_suspect", "candidate_files"]]
  graphContributions := [candidates_located]
}

def seed_004_node2 : WorkflowNode := {
  id := seed_004_nodeId2, name := some "candidate_file_list"
  stepType := .task
  reads := [⟨"candidate_files_report", .TString⟩]
  writes := [⟨"candidate_file_list", .TList .TJson⟩]
  llmInstruction := some "Extract absolute file paths under CANDIDATE_FILES as a JSON array of strings."
}

def seed_004_semNode2 : SemanticWorkflowNode := {
  baseNode := seed_004_node2
  precondVariables := [
    varIsNonEmptyString "candidate_files_report"

  ]
  postcondVariables := [varIsValidList "candidate_file_list", varIsValidJson "candidate_file_list", varIsValidJsonSchema "candidate_file_list" (.jArray .jString)]
  infoRequires := [info "candidate_files"]
}

def seed_004_node3 : WorkflowNode := {
  id := seed_004_nodeId3, name := some "for_each_candidate"
  stepType := .forEachLoop
  reads := [⟨"candidate_file_list", .TList .TJson⟩]
  writes := []
  llmInstruction := none
}

def seed_004_loopNode3 : SemanticLoopNode := {
  baseNode := seed_004_node3
  precondVariables := [
    varIsValidList "candidate_file_list",
    varIsValidJsonSchema "candidate_file_list" (.jArray .jString)
  ]
  postcondVariables := []
  loopInvariant := [
    varIsValidList "candidate_file_list",
    varIsNonEmptyString "problem_statement",
    varIsValidTool "shell_run"
  ]
  terminationSpec := .finiteCondition ["{candidate_file_list}"]

  exitPostconditions := [
    varIsValidList "candidate_file_list"
  ]
  executesAtLeastOnce := false
}
def seed_004_semNode3 : SemanticWorkflowNode := seed_004_loopNode3.toSemanticWorkflowNode

def seed_004_node4 : WorkflowNode := {
  id := seed_004_nodeId4
  name := some "inspect_candidate"
  stepType := .task
  reads := [⟨"candidate_path", .TString⟩]
  writes := []
  llmInstruction := some "Inspect the candidate source file {{candidate_path}}. Read relevant sections, note functions/classes, jot a one-paragraph summary. Concise scouting pass."
}

def seed_004_semNode4 : SemanticWorkflowNode := {
  baseNode := seed_004_node4
  precondVariables := [
    varIsValidTool "shell_run",
    varNameExists "candidate_path"
  ]
  postcondVariables := []
  graphContributions := [candidates_inspected]
}

def seed_004_node5 : WorkflowNode := {
  id := seed_004_nodeId5, name := some "build_reproduction"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩]
  writes := [⟨"reproduction_report", .TString⟩]
  llmInstruction := some "Write /testbed/reproduce_issue.py. Prints BUG PRESENT/BUG FIXED and exits 1/0.\nRun it once, capture output.\nReport:\nREPRO_SCRIPT: ...\nREPRO_STATUS: ...\nREPRO_OUTPUT_TAIL: ..."
}

def seed_004_semNode5 : SemanticWorkflowNode := {
  baseNode := seed_004_node5
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement",

    varIsNonEmptyString "candidate_inspection_evidence"
  ]
  postcondVariables := [varIsNonEmptyString "reproduction_report", varContainsSentinel "reproduction_report" "REPRO_STATUS:"]
  infoRequires := [info "primary_suspect"]
  producesVariableInfo := [varInfo "reproduction_report"
        ["repro_script", "repro_status"]]
  graphContributions := [issue_reproduced]
}

def seed_004_node6 : WorkflowNode := {
  id := seed_004_nodeId6, name := some "choose_fix_strategy"
  stepType := .task
  reads := [⟨"candidate_files_report", .TString⟩, ⟨"reproduction_report", .TString⟩]
  writes := [⟨"fix_strategy", .TString⟩]
  llmInstruction := some "Decide kind of fix. Pick one of logic_fix/boundary_guard/refactor_small/data_model_fix.\nOUTPUT_FORMAT:\nstrategy: ...\ntarget_file: ...\ntarget_symbols: ...\nrationale: ..."
}

def seed_004_semNode6 : SemanticWorkflowNode := {
  baseNode := seed_004_node6
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "candidate_files_report",
    varIsNonEmptyString "reproduction_report"

  ]
  postcondVariables := [varIsNonEmptyString "fix_strategy", varContainsSentinel "fix_strategy" "strategy:"]
  infoRequires := [info "primary_suspect", info "repro_status"]
  producesVariableInfo := [varInfo "fix_strategy"
        ["strategy", "target_file", "target_symbols"]]
  graphContributions := [strategy_chosen]
}

def seed_004_node7 : WorkflowNode := {
  id := seed_004_nodeId7, name := some "dispatch_fix_strategy"
  stepType := .switchBranch
  reads := [⟨"fix_strategy", .TString⟩]
  writes := []
  llmInstruction := none
}

def seed_004_semNode7 : SemanticWorkflowNode := {
  baseNode := seed_004_node7
  precondVariables := [
    varIsNonEmptyString "fix_strategy"

  ]
  postcondVariables := []
  infoRequires := [info "strategy"]
}

def seed_004_node8 : WorkflowNode := {
  id := seed_004_nodeId8, name := some "apply_logic_fix"
  stepType := .task
  reads := [⟨"fix_strategy", .TString⟩, ⟨"reproduction_report", .TString⟩]
  writes := [⟨"fix_application", .TString⟩]
  llmInstruction := some "Edit target file's logic inline. Show git diff."
}
def seed_004_semNode8 : SemanticWorkflowNode := {
  baseNode := seed_004_node8
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_strategy",
    varIsNonEmptyString "reproduction_report"

  ]
  postcondVariables := [varIsNonEmptyString "fix_application"]
  infoRequires := [info "target_file", info "strategy"]
  graphContributions := [fix_applied]
}

def seed_004_node9 : WorkflowNode := {
  id := seed_004_nodeId9, name := some "apply_boundary_guard"
  stepType := .task
  reads := [⟨"fix_strategy", .TString⟩, ⟨"reproduction_report", .TString⟩]
  writes := [⟨"fix_application", .TString⟩]
  llmInstruction := some "Add a defensive guard at the target location. Show git diff."
}
def seed_004_semNode9 : SemanticWorkflowNode := {
  baseNode := seed_004_node9
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_strategy",
    varIsNonEmptyString "reproduction_report"

  ]
  postcondVariables := [varIsNonEmptyString "fix_application"]
  infoRequires := [info "target_file", info "strategy"]
  graphContributions := [fix_applied]
}

def seed_004_node10 : WorkflowNode := {
  id := seed_004_nodeId10, name := some "apply_small_refactor"
  stepType := .task
  reads := [⟨"fix_strategy", .TString⟩, ⟨"reproduction_report", .TString⟩]
  writes := [⟨"fix_application", .TString⟩]
  llmInstruction := some "Perform minimal restructuring. Show git diff."
}
def seed_004_semNode10 : SemanticWorkflowNode := {
  baseNode := seed_004_node10
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_strategy",
    varIsNonEmptyString "reproduction_report"

  ]
  postcondVariables := [varIsNonEmptyString "fix_application"]
  infoRequires := [info "target_file", info "strategy"]
  graphContributions := [fix_applied]
}

def seed_004_node11 : WorkflowNode := {
  id := seed_004_nodeId11, name := some "apply_data_model_fix"
  stepType := .task
  reads := [⟨"fix_strategy", .TString⟩, ⟨"reproduction_report", .TString⟩]
  writes := [⟨"fix_application", .TString⟩]
  llmInstruction := some "Adjust the data-model definition. Show git diff."
}
def seed_004_semNode11 : SemanticWorkflowNode := {
  baseNode := seed_004_node11
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_strategy",
    varIsNonEmptyString "reproduction_report"

  ]
  postcondVariables := [varIsNonEmptyString "fix_application"]
  infoRequires := [info "target_file", info "strategy"]
  graphContributions := [fix_applied]
}

def seed_004_node12 : WorkflowNode := {
  id := seed_004_nodeId12, name := some "apply_generic_fix"
  stepType := .task
  reads := [⟨"problem_statement", .TString⟩]
  writes := [⟨"fix_application", .TString⟩]
  llmInstruction := some "Fallback minimal code change implied by the PR description. Show the diff."
}
def seed_004_semNode12 : SemanticWorkflowNode := {
  baseNode := seed_004_node12
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "problem_statement"
  ]
  postcondVariables := [varIsNonEmptyString "fix_application"]
  graphContributions := [fix_applied]
}

def seed_004_node13 : WorkflowNode := {
  id := seed_004_nodeId13, name := some "verify_reproduction_post_fix"
  stepType := .task
  reads := [⟨"regression_test_cmd", .TString⟩]
  writes := [⟨"post_fix_verification", .TString⟩]
  llmInstruction := some "Re-run reproduction. Optionally run narrow pytest.\nIf regression_test_cmd is non-empty, run it.\nReport:\nREPRO_AFTER_FIX: <pass|fail>\nTARGETED_TEST: <pass|fail|skipped>\nNOTES: ..."
}

def seed_004_semNode13 : SemanticWorkflowNode := {
  baseNode := seed_004_node13
  precondVariables := [
    varIsValidTool "shell_run",
    varNameExists "regression_test_cmd",
    varIsNonEmptyString "fix_application"
  ]
  postcondVariables := [varIsNonEmptyString "post_fix_verification", varContainsSentinel "post_fix_verification" "REPRO_AFTER_FIX:"]
  producesVariableInfo := [varInfo "post_fix_verification"
        ["repro_after_fix", "targeted_test"]]
  graphContributions := [post_fix_verified]
  graphVerifications := [fix_applied]
}

def seed_004_node14 : WorkflowNode := {
  id := seed_004_nodeId14, name := some "if_reproduction_still_failing"
  stepType := .conditional
  reads := [⟨"post_fix_verification", .TString⟩]
  writes := []
  llmInstruction := none
}

def seed_004_semNode14 : SemanticWorkflowNode := {
  baseNode := seed_004_node14
  precondVariables := [
    varIsNonEmptyString "post_fix_verification"

  ]
  postcondVariables := []
  infoRequires := [info "repro_after_fix"]
}

def seed_004_node15 : WorkflowNode := {
  id := seed_004_nodeId15, name := some "adjust_fix_once"
  stepType := .task
  reads := [⟨"post_fix_verification", .TString⟩]
  writes := [⟨"fix_adjustment", .TString⟩]
  llmInstruction := some "Re-read the target file, make ONE focused adjustment. Re-run repro once, include final line in your reply."
}

def seed_004_semNode15 : SemanticWorkflowNode := {
  baseNode := seed_004_node15
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "post_fix_verification",
    varIsNonEmptyString "fix_application"

  ]
  postcondVariables := [varIsNonEmptyString "fix_adjustment"]
  infoRequires := [info "repro_after_fix"]
  graphContributions := [fix_adjusted]
}

def seed_004_node16 : WorkflowNode := {
  id := seed_004_nodeId16, name := some "note_passing_verification"
  stepType := .task
  reads := []
  writes := [⟨"fix_adjustment", .TString⟩]
  llmInstruction := some "Verification passed. Briefly note remaining concerns for edge-case pass."
}

def seed_004_semNode16 : SemanticWorkflowNode := {
  baseNode := seed_004_node16
  precondVariables := [
    varIsValidTool "shell_run"
  ]
  postcondVariables := [varIsNonEmptyString "fix_adjustment"]
  graphContributions := [fix_adjusted]
}

def seed_004_node17 : WorkflowNode := {
  id := seed_004_nodeId17, name := some "edge_case_plan"
  stepType := .task
  reads := [⟨"fix_strategy", .TString⟩, ⟨"fix_application", .TString⟩, ⟨"post_fix_verification", .TString⟩, ⟨"fix_adjustment", .TString⟩]
  writes := [⟨"edge_case_report", .TString⟩]
  llmInstruction := some "Enumerate 3-5 concrete edge cases. For each: one-liner, run, record result. Produce EDGE_CASE_REPORT."
}

def seed_004_semNode17 : SemanticWorkflowNode := {
  baseNode := seed_004_node17
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_strategy",
    varIsNonEmptyString "fix_application",
    varIsNonEmptyString "post_fix_verification",
    varIsNonEmptyString "fix_adjustment"

  ]
  postcondVariables := [varIsNonEmptyString "edge_case_report"]
  infoRequires := [info "repro_after_fix"]
  graphContributions := [edge_cases_checked]
}

def seed_004_node18 : WorkflowNode := {
  id := seed_004_nodeId18, name := some "create_and_submit_patch"
  stepType := .task
  reads := []
  writes := [⟨"submission_result", .TString⟩]
  llmInstruction := some "Produce the patch and submit.\ngit diff -- path/to/file1 ... > patch.txt\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt"
}

def seed_004_semNode18 : SemanticWorkflowNode := {
  baseNode := seed_004_node18
  precondVariables := [
    varIsValidTool "shell_run",
    varIsNonEmptyString "fix_application"

  ]
  postcondVariables := [varIsNonEmptyString "submission_result", varContainsSentinel "submission_result" "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]
  infoRequires := [info "modified_files"]
  graphContributions := [patch_submitted]
}

def seed_004Graph : WorkflowGraph := {
  nodes := [
    seed_004_node0, seed_004_node1, seed_004_node2, seed_004_node3,
    seed_004_node4, seed_004_node5, seed_004_node6, seed_004_node7,
    seed_004_node8, seed_004_node9, seed_004_node10, seed_004_node11,
    seed_004_node12, seed_004_node13, seed_004_node14, seed_004_node15,
    seed_004_node16, seed_004_node17, seed_004_node18
  ]
  edges := [
    
    .seqEdge seed_004_nodeId0 seed_004_nodeId1,
    .seqEdge seed_004_nodeId1 seed_004_nodeId2,
    
    .seqEdge seed_004_nodeId2 seed_004_nodeId3,
    .loopEdge seed_004_nodeId3 seed_004_nodeId4 seed_004_nodeId5,
    .loopBackEdge seed_004_nodeId4 seed_004_nodeId3,
    
    .seqEdge seed_004_nodeId5 seed_004_nodeId6,
    .seqEdge seed_004_nodeId6 seed_004_nodeId7,
    
    .switchEdge seed_004_nodeId7
      [seed_004_nodeId8, seed_004_nodeId9, seed_004_nodeId10, seed_004_nodeId11]
      (some seed_004_nodeId12),
    
    .seqEdge seed_004_nodeId8  seed_004_nodeId13,
    .seqEdge seed_004_nodeId9  seed_004_nodeId13,
    .seqEdge seed_004_nodeId10 seed_004_nodeId13,
    .seqEdge seed_004_nodeId11 seed_004_nodeId13,
    .seqEdge seed_004_nodeId12 seed_004_nodeId13,
    
    .branchEdge seed_004_nodeId14 seed_004_nodeId15 seed_004_nodeId16,
    .seqEdge seed_004_nodeId13 seed_004_nodeId14,
    
    .seqEdge seed_004_nodeId15 seed_004_nodeId17,
    .seqEdge seed_004_nodeId16 seed_004_nodeId17,
    
    .seqEdge seed_004_nodeId17 seed_004_nodeId18
  ]
  entry := seed_004_nodeId0
  exits := [seed_004_nodeId18]
  parameters := [
    ⟨"code_path", .TString⟩,
    ⟨"problem_statement", .TString⟩,
    ⟨"regression_test_cmd", .TString⟩,
    ⟨"candidate_path", .TString⟩
  ]
}

/-
========================================================================
STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS
========================================================================
-/

#eval do
  let g := seed_004Graph
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
      let status := if fromParam || fromPred then "OK" else "UNRESOLVED"
      IO.println s!"    read  \"{rv.name}\" ({repr rv.type}): {status}"
    for wv in node.writes do
      IO.println s!"    write \"{wv.name}\" ({repr wv.type})"

/-
========================================================================
STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS
========================================================================
-/

#eval seed_004Graph.allWritesConsistent
#eval seed_004Graph.allReadResolvable
#eval seed_004Graph.edgesValid
#eval seed_004Graph.entryNodeValid
#eval seed_004Graph.exitNodesValid
#eval seed_004Graph.allExitsReachable
#eval seed_004Graph.noOrphanNodes
#eval seed_004Graph.returnType

def seed_004_paramNode : SemanticWorkflowNode := {
  baseNode := {
    id := ⟨20041122⟩, name := some "parameters",
    stepType := .setVariable, reads := [], writes := [],
    llmInstruction := none
  }
  precondVariables := []
  postcondVariables := [
    varNameExists "code_path",
    varNameExists "problem_statement",
    varNameExists "regression_test_cmd",
    varIsValidFilePath "code_path",
    varIsNonEmptyString "problem_statement",
    varNameExists "candidate_path",
    varIsValidTool "shell_run"
  ]
}

def seed_004_goalSpec : GoalSpecification := {
  originalGoal := "Reproduce the issue described by the PR and produce a git patch that fixes it."
  subGoals := [
    { name := repository_oriented
      variableName := "repo_overview"
      requiredPredicate := .isNonEmptyString
      description := "Repository layout and main package identified via orientation step."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := candidates_located
      variableName := "candidate_files_report"
      requiredPredicate := .isNonEmptyString
      description := "Candidate source files reported with a primary suspect."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := candidates_inspected
      variableName := "candidate_file_list"
      requiredPredicate := .isNonEmptyString
      description := "Candidate list is iterated; body produces no save_as so scouting is lost. Information is now judged by verifyInformationFlow (build_reproduction can no longer see primary_suspect — see STEP 6½)."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := issue_reproduced
      variableName := "reproduction_report"
      requiredPredicate := .isNonEmptyString
      description := "Reproduction script status captured."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := strategy_chosen
      variableName := "fix_strategy"
      requiredPredicate := .isNonEmptyString
      description := "A fix strategy enum is produced."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_applied
      variableName := "fix_application"
      requiredPredicate := .isNonEmptyString
      description := "One switch case applied a fix. Free-form diff — no markInfoContent."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.verificationCoverage] },
    { name := post_fix_verified
      variableName := "post_fix_verification"
      requiredPredicate := .isNonEmptyString
      description := "Titled repro_after_fix status captured."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := fix_adjusted
      variableName := "fix_adjustment"
      requiredPredicate := .isNonEmptyString
      description := "One-shot adjustment with NO re-verification — post_fix_verification stays stale."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.unifiedLoopBack, GraphLevelPredicateKeys.verificationCoverage] },
    { name := edge_cases_checked
      variableName := "edge_case_report"
      requiredPredicate := .isNonEmptyString
      description := "Edge case synthesis consuming a possibly-stale post_fix_verification. Information is now judged by verifyInformationFlow."
      
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage] },
    { name := patch_submitted
      variableName := "submission_result"
      requiredPredicate := .containsSubstring "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
      description := "Patch submitted, but modified_files aspect is not structurally extractable."
      requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, GraphLevelPredicateKeys.failSafe] }
  ]
}

def seed_004SemanticGraph : SemanticWorkflowGraph := {
  baseGraph := seed_004Graph
  paramNode := seed_004_paramNode
  semanticNodes := [
    seed_004_semNode0, seed_004_semNode1, seed_004_semNode2, seed_004_semNode3,
    seed_004_semNode4, seed_004_semNode5, seed_004_semNode6, seed_004_semNode7,
    seed_004_semNode8, seed_004_semNode9, seed_004_semNode10, seed_004_semNode11,
    seed_004_semNode12, seed_004_semNode13, seed_004_semNode14, seed_004_semNode15,
    seed_004_semNode16, seed_004_semNode17, seed_004_semNode18
  ]
  loopNodes := [seed_004_loopNode3]
  conditionalNodes := []
  specInvariant := by decide
  goalSpec := seed_004_goalSpec
}

/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/
/- One report — variable soundness + information flow + goal coverage. -/
#eval IO.println (seed_004SemanticGraph.verifyWorkflowReport (label := "seed_004"))

theorem seed_004_hoare_sound : (seed_004SemanticGraph.verifyWorkflow).hoareSound = false := by native_decide
theorem seed_004_info_sound : (seed_004SemanticGraph.verifyWorkflow).infoSound = false := by native_decide

end AgenticKernel.seed_004_layer2_new
