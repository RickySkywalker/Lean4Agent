"""Author IR JSON for seed_001_layer2_v2.lean.

11 nodes with a conditional (node 2) and a whileLoop (node 8).
expected_sound=False (terminal submit reads nothing).
"""

from _common import t, P, VP, TV, GPK, SubGoal, save


INSTR = {
    0: "Orient agent and survey /testbed. OUTPUT_FORMAT:\nPROJECT: ...\nISSUE_SUMMARY: ...\nCANDIDATE_FILES: ...\nNOTES: ...",
    1: "Context from previous step: {{orientation_report}}. Build a reproduction script. OUTPUT_FORMAT:\nREPRO_STATUS: ...\nREPRO_SCRIPT: <absolute path>\nOBSERVED_OUTPUT: ...\nEXPECTED_OUTPUT: ...",
    3: "First reproduction didn't trigger the bug: {{repro_report}}. Try once more. Same OUTPUT_FORMAT:\nREPRO_STATUS: ...\nREPRO_SCRIPT: ...\nOBSERVED_OUTPUT: ...\nEXPECTED_OUTPUT: ...",
    4: "Reproduction already succeeded: {{repro_report}}. Acknowledge briefly with a one-line confirmation.",
    5: "Using orientation: {{orientation_report}} and reproduction: {{repro_report}}. OUTPUT_FORMAT:\nBUG_LOCATION: <file:line>\nROOT_CAUSE: <explanation>\nFILES_TO_MODIFY: <comma list>\nFIX_STRATEGY: <description>\nEDGE_CASES_TO_CHECK: <list>",
    6: "Apply the fix described in diagnosis: {{diagnosis}}. OUTPUT_FORMAT:\nMODIFIED_FILES: <one per line>\nEDIT_SUMMARY: ...\nPOST_FIX_REPRO: <short quote>",
    7: "Extract EDGE_CASES_TO_CHECK from diagnosis: {{diagnosis}} as a JSON array of short strings. If missing, return [].",
    9: "Fix applied so far: {{fix_result}}. EDGE CASE: {{edge_case}}. Probe it. Report EDGE_CASE/STATUS/NOTES — but these are never saved.",
    10: "Create git diff patch and submit. Run `git diff -- path/to/file1 ... > patch.txt`. Then submit with `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt`.",
}


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="orient_and_survey_repo", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("orientation_report", predicates=[])],
            instruction=INSTR[0],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("orientation_report", "project"),
                t.InfoContentIR("orientation_report", "issue_summary"),
                t.InfoContentIR("orientation_report", "candidate_files"),
                t.InfoContentIR("orientation_report", "notes"),
                VP("orientation_report", "isNonEmptyString"),
                VP("orientation_report", "containsSubstring", substring="CANDIDATE_FILES:"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=1, name="build_reproduction", step_type="step",
            reads=[TV("orientation_report", predicates=[])],
            writes=[TV("repro_report", predicates=[])],
            instruction=INSTR[1],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("orientation_report", "isNonEmptyString"),
                t.InfoContentIR("orientation_report", "candidate_files"),
                t.InfoContentIR("orientation_report", "issue_summary"),
            ],
            postcond_extra=[
                t.InfoContentIR("repro_report", "repro_status"),
                t.InfoContentIR("repro_report", "repro_script"),
                t.InfoContentIR("repro_report", "observed_output"),
                t.InfoContentIR("repro_report", "expected_output"),
                VP("repro_report", "isNonEmptyString"),
                VP("repro_report", "containsSubstring", substring="REPRO_STATUS:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=2, name="repro_check", step_type="conditional",
            reads=[TV("repro_report", predicates=[])], writes=[], instruction=None,
            precond_extra=[VP("repro_report", "isNonEmptyString")],
            postcond_extra=[],
            then_target_id=3, else_target_id=4,
            then_postcond=[
                VP("repro_report", "isNonEmptyString"),
                VP("repro_report", "containsSubstring", substring="could_not_reproduce"),
            ],
            else_postcond=[VP("repro_report", "isNonEmptyString")],
        ),
        t.NodeIR(
            id=3, name="reproduction_retry", step_type="step",
            reads=[TV("repro_report", predicates=[])],
            writes=[TV("repro_report", predicates=[])],
            instruction=INSTR[3],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("repro_report", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("repro_report", "repro_status"),
                t.InfoContentIR("repro_report", "repro_script"),
                t.InfoContentIR("repro_report", "observed_output"),
                t.InfoContentIR("repro_report", "expected_output"),
                VP("repro_report", "isNonEmptyString"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=4, name="reproduction_confirmed", step_type="step",
            reads=[TV("repro_report", predicates=[])], writes=[],
            instruction=INSTR[4],
            precond_extra=[VP("repro_report", "isNonEmptyString")],
            postcond_extra=[],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=5, name="diagnose_root_cause", step_type="step",
            reads=[TV("orientation_report", predicates=[]),
                   TV("repro_report", predicates=[])],
            writes=[TV("diagnosis", predicates=[])],
            instruction=INSTR[5],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("orientation_report", "isNonEmptyString"),
                VP("repro_report", "isNonEmptyString"),
                t.InfoContentIR("repro_report", "repro_script"),
                t.InfoContentIR("repro_report", "observed_output"),
                t.InfoContentIR("orientation_report", "candidate_files"),
            ],
            postcond_extra=[
                t.InfoContentIR("diagnosis", "bug_location"),
                t.InfoContentIR("diagnosis", "root_cause"),
                t.InfoContentIR("diagnosis", "files_to_modify"),
                t.InfoContentIR("diagnosis", "fix_strategy"),
                t.InfoContentIR("diagnosis", "edge_cases_to_check"),
                VP("diagnosis", "isNonEmptyString"),
                VP("diagnosis", "containsSubstring", substring="BUG_LOCATION:"),
            ],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("root_cause_identified")],
        ),
        t.NodeIR(
            id=6, name="apply_fix", step_type="step",
            reads=[TV("diagnosis", predicates=[])],
            writes=[TV("fix_result", predicates=[])],
            instruction=INSTR[6],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("diagnosis", "isNonEmptyString"),
                t.InfoContentIR("diagnosis", "bug_location"),
                t.InfoContentIR("diagnosis", "files_to_modify"),
                t.InfoContentIR("diagnosis", "fix_strategy"),
            ],
            postcond_extra=[
                t.InfoContentIR("fix_result", "modified_files"),
                t.InfoContentIR("fix_result", "edit_summary"),
                t.InfoContentIR("fix_result", "post_fix_repro"),
                VP("fix_result", "isNonEmptyString"),
                VP("fix_result", "containsSubstring", substring="MODIFIED_FILES:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=7, name="discover_edge_case_list", step_type="step",
            reads=[TV("diagnosis", predicates=[])],
            writes=[TV("edge_case_list", predicates=[])],
            instruction=INSTR[7],
            precond_extra=[
                VP("diagnosis", "isNonEmptyString"),
                t.InfoContentIR("diagnosis", "edge_cases_to_check"),
            ],
            postcond_extra=[VP("edge_case_list", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("edge_cases_discovered")],
        ),
        t.NodeIR(
            id=8, name="for_each_edge_cases", step_type="whileLoop",
            reads=[TV("edge_case_list", predicates=[])], writes=[], instruction=None,
            precond_extra=[VP("edge_case_list", "isNonEmptyString")],
            loop_invariant=[
                VP("edge_case_list", "isNonEmptyString"),
                VP("fix_result", "isNonEmptyString"),
                t.InfoContentIR("fix_result", "modified_files"),
                t.InfoContentIR("fix_result", "edit_summary"),
            ],
            termination_kind="finiteCondition",
            termination_vars=["{edge_case_list}"],
            exit_postcond=[VP("fix_result", "isNonEmptyString")],
            loop_executes_at_least_once=False,
        ),
        t.NodeIR(
            id=9, name="probe_edge_case", step_type="step",
            reads=[TV("fix_result", predicates=[]), TV("edge_case", predicates=[])],
            writes=[], instruction=INSTR[9],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_result", "isNonEmptyString"),
                t.InfoContentIR("fix_result", "modified_files"),
                VP("edge_case", "nameExists"),
            ],
            postcond_extra=[],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("edge_cases_checked")],
        ),
        t.NodeIR(
            id=10, name="create_and_submit_patch", step_type="step",
            reads=[], writes=[TV("submission_result", predicates=[])],
            instruction=INSTR[10],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_result", "isNonEmptyString"),
                t.InfoContentIR("fix_result", "modified_files"),
            ],
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
        TV("edge_case", "TString", predicates=[]),
    ]

    edges = [
        t.EdgeIR("seq", from_node=0, to_node=1),
        t.EdgeIR("seq", from_node=1, to_node=2),
        t.EdgeIR("branch", cond_node=2, then_entry=3, else_entry=4),
        t.EdgeIR("seq", from_node=3, to_node=5),
        t.EdgeIR("seq", from_node=4, to_node=5),
        t.EdgeIR("seq", from_node=5, to_node=6),
        t.EdgeIR("seq", from_node=6, to_node=7),
        t.EdgeIR("seq", from_node=7, to_node=8),
        t.EdgeIR("loop", header=8, body_entry=9, exit_node=10),
        t.EdgeIR("loopBack", from_node=9, to_node=8),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal="Reproduce the issue described by the PR and produce a git patch that fixes it.",
        sub_goals=[
            SubGoal("repository_explored", "orientation_report", P("isNonEmptyString"),
                    "Repo was surveyed, project/candidate files identified.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_reproduced", "repro_report", P("isNonEmptyString"),
                    "A reproduction script was built; conditional retry path exists.",
                    [GPK("pathCoverage")]),
            SubGoal("root_cause_identified", "diagnosis", P("isNonEmptyString"),
                    "Root cause diagnosed with titled BUG_LOCATION/ROOT_CAUSE/FILES_TO_MODIFY/FIX_STRATEGY.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_implemented", "fix_result", P("isNonEmptyString"),
                    "Fix applied; MODIFIED_FILES titled field published.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
            SubGoal("edge_cases_checked", "edge_case_list", P("isNonEmptyString"),
                    "for_each iterates over discovered edge cases, but the body has NO save_as — per-edge-case findings are lost. informationSufficiency suffers.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
            SubGoal("patch_submitted", "submission_result",
                    P("containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
                    "Terminal step submits patch. BAD: reads nothing upstream — needs modified_files but no {{fix_result}} is injected.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
        ],
    )

    ir = t.WorkflowIR(
        name="seed_001",
        goal="Reproduce the issue described by the PR and produce a git patch that fixes it.",
        parameters=parameters, nodes=nodes, edges=edges,
        entry=0, exits=[10],
        goal_spec=goal_spec,
        expected_semantically_sound=False,
    )
    ir.infer_param_postcond()
    return ir


if __name__ == "__main__":
    save(build(), "seed_001_layer2_v2")
