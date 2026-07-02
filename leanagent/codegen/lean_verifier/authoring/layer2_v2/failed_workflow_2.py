"""Author IR JSON for failed_workflow_2_layer2_v2.lean.

12 nodes with while loop (node 5), conditional-like node 8 (emitted as plain
SemanticWorkflowNode in the original). Uses markInfoContent extensively.
"""

from _common import t, P, VP, TV, GPK, SubGoal, save


INSTR = {
    0: "Explore /testbed, list directory, identify main source package.\nReturn:\nREPO_ROOT: ...\nSOURCE_PACKAGE: ...\nKEY_DIRECTORIES: ...\nBUILD_SYSTEM: ...",
    1: "Based on issue and repo_structure, find relevant source files.\nReturn:\nRELEVANT_FILES:\n- <file>: <reason>\nPRIMARY_FILE: <path>",
    2: "Read primary file, understand the specific function/class involved.\nReturn:\nCODE_UNDERSTANDING:\n- Function/class: ...\n- Current behavior: ...\n- Expected behavior: ...\n- Suspected root cause: ...",
    3: "Create minimal reproduction script, run it to confirm bug.\nReturn:\nREPRODUCTION_STATUS: ...\nSCRIPT_PATH: ...\nERROR_OUTPUT: ...",
    4: "Trace code path, perform root-cause analysis. This is IMMUTABLE.\nReturn:\nROOT_CAUSE: ...\nFIX_STRATEGY: ...",
    6: "Implement the fix based on root cause analysis. If retry, use retry_notes.\nReturn:\nMODIFIED_FILES: ...\nFIX_SUMMARY: ...",
    7: "Re-run reproduction script to verify the fix works.\nReturn:\nVERIFIED: <true|false>",
    9: "Test edge cases after the fix. No feedback path if these fail.\nReturn:\nEDGE_CASE_RESULTS: ...\nALL_PASSED: <true|false>",
    10: "Create git diff patch from the applied fix.\nReturn:\nPATCH_FILE: /testbed/patch.txt\nPATCH_VALID: <true|false>",
    11: "Submit the final patch.\nRun: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt",
}


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="explore_repo_structure", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("repo_structure", predicates=[])],
            instruction=INSTR[0],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("repo_structure", "repo_root"),
                t.InfoContentIR("repo_structure", "source_package"),
                t.InfoContentIR("repo_structure", "key_directories"),
                t.InfoContentIR("repo_structure", "build_system"),
                VP("repo_structure", "isNonEmptyString"),
                VP("repo_structure", "containsSubstring", substring="REPO_ROOT:"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=1, name="locate_relevant_files", step_type="step",
            reads=[TV("problem_statement", predicates=[]), TV("repo_structure", predicates=[])],
            writes=[TV("relevant_files", predicates=[])],
            instruction=INSTR[1],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("repo_structure", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("relevant_files", "primary_file"),
                VP("relevant_files", "isNonEmptyString"),
                VP("relevant_files", "containsSubstring", substring="RELEVANT_FILES:"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=2, name="read_and_understand_code", step_type="step",
            reads=[TV("problem_statement", predicates=[]), TV("relevant_files", predicates=[])],
            writes=[TV("code_understanding", predicates=[])],
            instruction=INSTR[2],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("relevant_files", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("code_understanding", "function_name"),
                t.InfoContentIR("code_understanding", "file_path"),
                t.InfoContentIR("code_understanding", "line_range"),
                t.InfoContentIR("code_understanding", "current_behavior"),
                t.InfoContentIR("code_understanding", "expected_behavior"),
                t.InfoContentIR("code_understanding", "suspected_root_cause"),
                VP("code_understanding", "isNonEmptyString"),
            ],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_understood")],
        ),
        t.NodeIR(
            id=3, name="create_reproduce_script", step_type="step",
            reads=[TV("problem_statement", predicates=[]), TV("code_understanding", predicates=[])],
            writes=[TV("reproduction_result", predicates=[])],
            instruction=INSTR[3],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("code_understanding", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("reproduction_result", "reproduction_status"),
                t.InfoContentIR("reproduction_result", "script_path"),
                t.InfoContentIR("reproduction_result", "error_output"),
                VP("reproduction_result", "isNonEmptyString"),
                VP("reproduction_result", "containsSubstring", substring="REPRODUCTION_STATUS:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("bug_reproduced")],
        ),
        t.NodeIR(
            id=4, name="root_cause_analysis", step_type="step",
            reads=[TV("problem_statement", predicates=[]),
                   TV("code_understanding", predicates=[]),
                   TV("reproduction_result", predicates=[])],
            writes=[TV("root_cause_analysis", predicates=[])],
            instruction=INSTR[4],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("code_understanding", "isNonEmptyString"),
                VP("reproduction_result", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("root_cause_analysis", "bug_location"),
                t.InfoContentIR("root_cause_analysis", "root_cause"),
                t.InfoContentIR("root_cause_analysis", "symptom_cause"),
                t.InfoContentIR("root_cause_analysis", "fix_strategy"),
                t.InfoContentIR("root_cause_analysis", "what_to_change"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "risk_areas"),
                VP("root_cause_analysis", "isNonEmptyString"),
                VP("root_cause_analysis", "containsSubstring", substring="ROOT_CAUSE:"),
            ],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("root_cause_identified")],
        ),
        t.NodeIR(
            id=5, name="fix_loop", step_type="whileLoop",
            reads=[TV("fix_verified", predicates=[])], writes=[], instruction=None,
            precond_extra=[VP("fix_verified", "nameExists")],
            loop_invariant=[
                VP("fix_verified", "nameExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("root_cause_analysis", "isNonEmptyString"),
                t.InfoContentIR("root_cause_analysis", "bug_location"),
                t.InfoContentIR("root_cause_analysis", "root_cause"),
                t.InfoContentIR("root_cause_analysis", "symptom_cause"),
                t.InfoContentIR("root_cause_analysis", "fix_strategy"),
                t.InfoContentIR("root_cause_analysis", "what_to_change"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "risk_areas"),
                VP("retry_notes", "nameExists"),
            ],
            termination_kind="finiteCondition",
            termination_vars=["{fix_verified}"],
            exit_postcond=[
                VP("final_fix_summary", "isNonEmptyString"),
                VP("fix_result", "isNonEmptyString"),
                t.InfoContentIR("fix_result", "modified_files"),
                t.InfoContentIR("fix_result", "fix_summary"),
                VP("verification_result", "isNonEmptyString"),
                VP("fix_verified", "nameExists"),
            ],
            loop_executes_at_least_once=True,
        ),
        t.NodeIR(
            id=6, name="implement_fix", step_type="step",
            reads=[TV("problem_statement", predicates=[]),
                   TV("root_cause_analysis", predicates=[]),
                   TV("retry_notes", predicates=[])],
            writes=[TV("fix_result", predicates=[])],
            instruction=INSTR[6],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("root_cause_analysis", "isNonEmptyString"),
                VP("retry_notes", "nameExists"),
                t.InfoContentIR("root_cause_analysis", "bug_location"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "root_cause"),
                t.InfoContentIR("root_cause_analysis", "fix_strategy"),
            ],
            postcond_extra=[
                t.InfoContentIR("fix_result", "modified_files"),
                t.InfoContentIR("fix_result", "fix_summary"),
                VP("fix_result", "isNonEmptyString"),
                VP("fix_result", "containsSubstring", substring="MODIFIED_FILES:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=7, name="verify_reproduction", step_type="step",
            reads=[TV("fix_result", predicates=[])],
            writes=[TV("verification_result", predicates=[])],
            instruction=INSTR[7],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_result", "isNonEmptyString"),
                t.InfoContentIR("fix_result", "modified_files"),
            ],
            postcond_extra=[VP("verification_result", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
        ),
        # Node 8: conditional in stepType but emitted as plain SemanticWorkflowNode
        # (original has NO then_target_id/else_target_id — this is a "conditional"
        # step-type without semantic conditional structure; graph uses loopBack from it).
        t.NodeIR(
            id=8, name="is_verified_check", step_type="conditional",
            reads=[TV("verification_result", predicates=[])], writes=[], instruction=None,
            precond_extra=[VP("verification_result", "isNonEmptyString")],
            postcond_extra=[],
            # NO then_target_id/else_target_id → emitted as plain SemanticWorkflowNode
        ),
        t.NodeIR(
            id=9, name="test_edge_cases", step_type="step",
            reads=[TV("problem_statement", predicates=[]),
                   TV("root_cause_analysis", predicates=[]),
                   TV("final_fix_summary", predicates=[])],
            writes=[TV("edge_case_results", predicates=[])],
            instruction=INSTR[9],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("root_cause_analysis", "isNonEmptyString"),
                VP("final_fix_summary", "isNonEmptyString"),
                t.InfoContentIR("root_cause_analysis", "root_cause"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
            ],
            postcond_extra=[VP("edge_case_results", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("edge_cases_checked")],
        ),
        t.NodeIR(
            id=10, name="create_patch", step_type="step",
            reads=[TV("final_fix_summary", predicates=[])],
            writes=[TV("patch_result", predicates=[])],
            instruction=INSTR[10],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("final_fix_summary", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("patch_result", "isNonEmptyString"),
                VP("patch_result", "containsSubstring", substring="PATCH_FILE:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_created")],
        ),
        t.NodeIR(
            id=11, name="submit_patch", step_type="step",
            reads=[], writes=[TV("submission_result", predicates=[])],
            instruction=INSTR[11],
            precond_extra=[VP("shell_run", "toolExists")],
            postcond_extra=[
                VP("submission_result", "isNonEmptyString"),
                VP("submission_result", "containsSubstring",
                   substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_submitted")],
        ),
    ]

    parameters = [
        TV("code_path", "TString", predicates=[P("isValidFilePath")]),
        TV("problem_statement", "TString", predicates=[P("isNonEmptyString")]),
        TV("regression_test_cmd", "TString", predicates=[]),
        TV("retry_count", "TInt", predicates=[P("isInt")]),
        TV("max_retries", "TInt", predicates=[P("isInt")]),
        TV("fix_verified", "TString", predicates=[P("isNonEmptyString")]),
        TV("retry_notes", "TString", predicates=[]),
        TV("final_fix_summary", "TString", predicates=[]),
    ]

    # Irregular paramNode order: first 6 params get nameExists (not 7 or 8),
    # then all predicates in a non-standard order, then retry_notes/final_fix_summary
    # nameExists AFTER shell_run.
    param_postcond = [
        VP("code_path", "nameExists"),
        VP("problem_statement", "nameExists"),
        VP("regression_test_cmd", "nameExists"),
        VP("retry_count", "nameExists"),
        VP("max_retries", "nameExists"),
        VP("fix_verified", "nameExists"),
        VP("code_path", "isValidFilePath"),
        VP("problem_statement", "isNonEmptyString"),
        VP("retry_count", "isInt"),
        VP("max_retries", "isInt"),
        VP("fix_verified", "isNonEmptyString"),
        VP("retry_notes", "nameExists"),
        VP("final_fix_summary", "nameExists"),
        VP("shell_run", "toolExists"),
    ]

    edges = [
        t.EdgeIR("seq", from_node=0, to_node=1),
        t.EdgeIR("seq", from_node=1, to_node=2),
        t.EdgeIR("seq", from_node=2, to_node=3),
        t.EdgeIR("seq", from_node=3, to_node=4),
        t.EdgeIR("seq", from_node=4, to_node=5),
        t.EdgeIR("loop", header=5, body_entry=6, exit_node=9),
        t.EdgeIR("seq", from_node=6, to_node=7),
        t.EdgeIR("seq", from_node=7, to_node=8),
        t.EdgeIR("loopBack", from_node=8, to_node=5),
        t.EdgeIR("seq", from_node=9, to_node=10),
        t.EdgeIR("seq", from_node=10, to_node=11),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal="Given a GitHub issue, systematically reproduce, diagnose, fix, and verify the issue",
        sub_goals=[
            SubGoal("repository_explored", "repo_structure", P("isNonEmptyString"),
                    "Repository structure and source package identified via exploratory step.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_understood", "code_understanding", P("isNonEmptyString"),
                    "The issue, relevant files, and current vs expected behavior are understood.",
                    [GPK("pathCoverage")]),
            SubGoal("bug_reproduced", "reproduction_result", P("isNonEmptyString"),
                    "A reproduction script confirms the bug is present.",
                    [GPK("pathCoverage")]),
            SubGoal("root_cause_identified", "root_cause_analysis", P("isNonEmptyString"),
                    "Root cause of the bug is identified with fix strategy.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_implemented", "fix_result", P("isNonEmptyString"),
                    "A code fix has been implemented inside the retry loop. Under STRICT rules, implement_fix demands root_cause and fix_strategy aspects that are free-form → informationSufficiency FAILS.",
                    [GPK("pathCoverage"), GPK("informationSufficiency"),
                     GPK("unifiedLoopBack"), GPK("verificationCoverage"), GPK("failSafe")]),
            SubGoal("fix_verified", "verification_result", P("isNonEmptyString"),
                    "The fix passes verification via reproduction re-run.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack")]),
            SubGoal("edge_cases_checked", "edge_case_results", P("isNonEmptyString"),
                    "Edge cases tested after fix (dead-end: no feedback path if fails). Under STRICT rules, test_edge_cases demands root_cause aspect (free-form) → informationSufficiency FAILS.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
            SubGoal("patch_created", "patch_result", P("isNonEmptyString"),
                    "A git diff patch has been created from the fix.",
                    [GPK("pathCoverage")]),
            SubGoal("patch_submitted", "submission_result",
                    P("containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
                    "The final patch was submitted as the workflow output.",
                    [GPK("pathCoverage")]),
        ],
    )

    ir = t.WorkflowIR(
        name="failed_workflow_2",
        goal="Given a GitHub issue, systematically reproduce, diagnose, fix, and verify the issue through a structured multi-phase workflow.",
        parameters=parameters, nodes=nodes, edges=edges,
        entry=0, exits=[11],
        param_postcond=param_postcond,
        goal_spec=goal_spec,
    )
    return ir


if __name__ == "__main__":
    save(build(), "failed_workflow_2_layer2_v2")
