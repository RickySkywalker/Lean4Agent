"""Author IR JSON for seed_004_layer2_v2.lean.

19 nodes: forEachLoop (3), switchBranch (7), conditional (14). Uses discover
and synthesize step types. Custom TList TJson parameter type. expected_sound=False.
"""

from _common import t, P, VP, TV, GPK, SubGoal, save


INSTR = {
    0: "Do a shallow orientation pass over /testbed: list top-level layout, identify main source package, skim README.\nOUTPUT_FORMAT:\nrepo_layout: ...\nmain_package: ...\nbuild_system: ...\nskim_notes: ...",
    1: "Using the PR description and orientation, find source files most likely responsible.\nReturn:\nCANDIDATE_FILES:\n- <path_1>: <reason>\nPRIMARY_SUSPECT: <single path>",
    2: "Extract absolute file paths under CANDIDATE_FILES as a JSON array of strings.",
    4: "Inspect the candidate source file {{candidate_path}}. Read relevant sections, note functions/classes, jot a one-paragraph summary. Concise scouting pass.",
    5: "Write /testbed/reproduce_issue.py. Prints BUG PRESENT/BUG FIXED and exits 1/0.\nRun it once, capture output.\nReport:\nREPRO_SCRIPT: ...\nREPRO_STATUS: ...\nREPRO_OUTPUT_TAIL: ...",
    6: "Decide kind of fix. Pick one of logic_fix/boundary_guard/refactor_small/data_model_fix.\nOUTPUT_FORMAT:\nstrategy: ...\ntarget_file: ...\ntarget_symbols: ...\nrationale: ...",
    8: "Edit target file's logic inline. Show git diff.",
    9: "Add a defensive guard at the target location. Show git diff.",
    10: "Perform minimal restructuring. Show git diff.",
    11: "Adjust the data-model definition. Show git diff.",
    12: "Fallback minimal code change implied by the PR description. Show the diff.",
    13: "Re-run reproduction. Optionally run narrow pytest.\nIf regression_test_cmd is non-empty, run it.\nReport:\nREPRO_AFTER_FIX: <pass|fail>\nTARGETED_TEST: <pass|fail|skipped>\nNOTES: ...",
    15: "Re-read the target file, make ONE focused adjustment. Re-run repro once, include final line in your reply.",
    16: "Verification passed. Briefly note remaining concerns for edge-case pass.",
    17: "Enumerate 3-5 concrete edge cases. For each: one-liner, run, record result. Produce EDGE_CASE_REPORT.",
    18: "Produce the patch and submit.\ngit diff -- path/to/file1 ... > patch.txt\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt",
}


def fix_apply_node(node_id: int, name: str, instruction: str) -> "t.NodeIR":
    """Nodes 8-11 share a common shape."""
    return t.NodeIR(
        id=node_id, name=name, step_type="step",
        reads=[TV("fix_strategy", predicates=[]), TV("reproduction_report", predicates=[])],
        writes=[TV("fix_application", predicates=[])],
        instruction=instruction,
        precond_extra=[
            VP("shell_run", "toolExists"),
            VP("fix_strategy", "isNonEmptyString"),
            VP("reproduction_report", "isNonEmptyString"),
            t.InfoContentIR("fix_strategy", "target_file"),
            t.InfoContentIR("fix_strategy", "strategy"),
        ],
        postcond_extra=[VP("fix_application", "isNonEmptyString")],
        step_tag=t.StepTagIR(kind="transformative"),
        sub_goal_contributions=[t.SubGoalTagIR("fix_applied")],
    )


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="orient_and_scan", step_type="step",
            reads=[TV("code_path", predicates=[]), TV("problem_statement", predicates=[])],
            writes=[TV("repo_overview", predicates=[])],
            instruction=INSTR[0],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("code_path", "isValidFilePath"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("repo_overview", "repo_layout"),
                t.InfoContentIR("repo_overview", "main_package"),
                t.InfoContentIR("repo_overview", "build_system"),
                t.InfoContentIR("repo_overview", "skim_notes"),
                VP("repo_overview", "isNonEmptyString"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_oriented")],
        ),
        t.NodeIR(
            id=1, name="locate_candidate_files", step_type="step",
            reads=[TV("repo_overview", predicates=[])],
            writes=[TV("candidate_files_report", predicates=[])],
            instruction=INSTR[1],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("repo_overview", "isNonEmptyString"),
                t.InfoContentIR("repo_overview", "main_package"),
            ],
            postcond_extra=[
                t.InfoContentIR("candidate_files_report", "primary_suspect"),
                t.InfoContentIR("candidate_files_report", "candidate_files"),
                VP("candidate_files_report", "isNonEmptyString"),
                VP("candidate_files_report", "containsSubstring", substring="PRIMARY_SUSPECT:"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("candidates_located")],
        ),
        t.NodeIR(
            id=2, name="candidate_file_list", step_type="discover",
            reads=[TV("candidate_files_report", predicates=[])],
            writes=[TV("candidate_file_list", base_type="TList TJson", predicates=[])],
            instruction=INSTR[2],
            precond_extra=[
                VP("candidate_files_report", "isNonEmptyString"),
                t.InfoContentIR("candidate_files_report", "candidate_files"),
            ],
            postcond_extra=[
                VP("candidate_file_list", "isValidList"),
                VP("candidate_file_list", "isValidJson"),
                VP("candidate_file_list", "matchesJsonSchema",
                   schema=t.JsonSchemaIR(kind="jArray",
                                         element_schema=t.JsonSchemaIR(kind="jString"))),
            ],
        ),
        t.NodeIR(
            id=3, name="for_each_candidate", step_type="forEachLoop",
            reads=[TV("candidate_file_list", base_type="TList TJson", predicates=[])],
            writes=[], instruction=None,
            precond_extra=[
                VP("candidate_file_list", "isValidList"),
                VP("candidate_file_list", "matchesJsonSchema",
                   schema=t.JsonSchemaIR(kind="jArray",
                                         element_schema=t.JsonSchemaIR(kind="jString"))),
            ],
            loop_invariant=[
                VP("candidate_file_list", "isValidList"),
                VP("problem_statement", "isNonEmptyString"),
                VP("shell_run", "toolExists"),
            ],
            termination_kind="finiteCondition",
            termination_vars=["{candidate_file_list}"],
            exit_postcond=[VP("candidate_file_list", "isValidList")],
            loop_executes_at_least_once=False,
        ),
        t.NodeIR(
            id=4, name="inspect_candidate", step_type="step",
            reads=[TV("candidate_path", predicates=[])], writes=[], instruction=INSTR[4],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("candidate_path", "nameExists"),
            ],
            postcond_extra=[],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("candidates_inspected")],
        ),
        t.NodeIR(
            id=5, name="build_reproduction", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("reproduction_report", predicates=[])],
            instruction=INSTR[5],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                t.InfoContentIR("candidate_files_report", "primary_suspect"),
                VP("candidate_inspection_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("reproduction_report", "repro_script"),
                t.InfoContentIR("reproduction_report", "repro_status"),
                VP("reproduction_report", "isNonEmptyString"),
                VP("reproduction_report", "containsSubstring", substring="REPRO_STATUS:"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=6, name="choose_fix_strategy", step_type="step",
            reads=[TV("candidate_files_report", predicates=[]),
                   TV("reproduction_report", predicates=[])],
            writes=[TV("fix_strategy", predicates=[])],
            instruction=INSTR[6],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("candidate_files_report", "isNonEmptyString"),
                VP("reproduction_report", "isNonEmptyString"),
                t.InfoContentIR("candidate_files_report", "primary_suspect"),
                t.InfoContentIR("reproduction_report", "repro_status"),
            ],
            postcond_extra=[
                t.InfoContentIR("fix_strategy", "strategy"),
                t.InfoContentIR("fix_strategy", "target_file"),
                t.InfoContentIR("fix_strategy", "target_symbols"),
                VP("fix_strategy", "isNonEmptyString"),
                VP("fix_strategy", "containsSubstring", substring="strategy:"),
            ],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("strategy_chosen")],
        ),
        t.NodeIR(
            id=7, name="dispatch_fix_strategy", step_type="switchBranch",
            reads=[TV("fix_strategy", predicates=[])], writes=[], instruction=None,
            precond_extra=[
                VP("fix_strategy", "isNonEmptyString"),
                t.InfoContentIR("fix_strategy", "strategy"),
            ],
            postcond_extra=[],
        ),
        fix_apply_node(8, "apply_logic_fix", INSTR[8]),
        fix_apply_node(9, "apply_boundary_guard", INSTR[9]),
        fix_apply_node(10, "apply_small_refactor", INSTR[10]),
        fix_apply_node(11, "apply_data_model_fix", INSTR[11]),
        t.NodeIR(
            id=12, name="apply_generic_fix", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("fix_application", predicates=[])],
            instruction=INSTR[12],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_application", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_applied")],
        ),
        t.NodeIR(
            id=13, name="verify_reproduction_post_fix", step_type="step",
            reads=[TV("regression_test_cmd", predicates=[])],
            writes=[TV("post_fix_verification", predicates=[])],
            instruction=INSTR[13],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("regression_test_cmd", "nameExists"),
                VP("fix_application", "isNonEmptyString"),
            ],
            postcond_extra=[
                t.InfoContentIR("post_fix_verification", "repro_after_fix"),
                t.InfoContentIR("post_fix_verification", "targeted_test"),
                VP("post_fix_verification", "isNonEmptyString"),
                VP("post_fix_verification", "containsSubstring", substring="REPRO_AFTER_FIX:"),
            ],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("post_fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_applied")],
        ),
        t.NodeIR(
            id=14, name="if_reproduction_still_failing", step_type="conditional",
            reads=[TV("post_fix_verification", predicates=[])], writes=[], instruction=None,
            precond_extra=[
                VP("post_fix_verification", "isNonEmptyString"),
                t.InfoContentIR("post_fix_verification", "repro_after_fix"),
            ],
            postcond_extra=[],
            # NO then/else targets → emitted as plain SemanticWorkflowNode
        ),
        t.NodeIR(
            id=15, name="adjust_fix_once", step_type="step",
            reads=[TV("post_fix_verification", predicates=[])],
            writes=[TV("fix_adjustment", predicates=[])],
            instruction=INSTR[15],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("post_fix_verification", "isNonEmptyString"),
                VP("fix_application", "isNonEmptyString"),
                t.InfoContentIR("post_fix_verification", "repro_after_fix"),
            ],
            postcond_extra=[VP("fix_adjustment", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_adjusted")],
        ),
        t.NodeIR(
            id=16, name="note_passing_verification", step_type="step",
            reads=[], writes=[TV("fix_adjustment", predicates=[])], instruction=INSTR[16],
            precond_extra=[VP("shell_run", "toolExists")],
            postcond_extra=[VP("fix_adjustment", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_adjusted")],
        ),
        t.NodeIR(
            id=17, name="edge_case_plan", step_type="synthesize",
            reads=[TV("fix_strategy", predicates=[]),
                   TV("fix_application", predicates=[]),
                   TV("post_fix_verification", predicates=[]),
                   TV("fix_adjustment", predicates=[])],
            writes=[TV("edge_case_report", predicates=[])],
            instruction=INSTR[17],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_strategy", "isNonEmptyString"),
                VP("fix_application", "isNonEmptyString"),
                VP("post_fix_verification", "isNonEmptyString"),
                VP("fix_adjustment", "isNonEmptyString"),
                t.InfoContentIR("post_fix_verification", "repro_after_fix"),
                t.InfoContentIR("fix_adjustment", "repro_after_fix"),
            ],
            postcond_extra=[VP("edge_case_report", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("edge_cases_checked")],
        ),
        t.NodeIR(
            id=18, name="create_and_submit_patch", step_type="step",
            reads=[], writes=[TV("submission_result", predicates=[])],
            instruction=INSTR[18],
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_application", "isNonEmptyString"),
                t.InfoContentIR("fix_application", "modified_files"),
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
        TV("candidate_path", "TString", predicates=[]),
    ]

    # Irregular paramNode order: candidate_path gets nameExists only and appears
    # AFTER standard predicates; shell_run comes last.
    param_postcond = [
        VP("code_path", "nameExists"),
        VP("problem_statement", "nameExists"),
        VP("regression_test_cmd", "nameExists"),
        VP("code_path", "isValidFilePath"),
        VP("problem_statement", "isNonEmptyString"),
        VP("candidate_path", "nameExists"),
        VP("shell_run", "toolExists"),
    ]

    edges = [
        t.EdgeIR("seq", from_node=0, to_node=1),
        t.EdgeIR("seq", from_node=1, to_node=2),
        t.EdgeIR("seq", from_node=2, to_node=3),
        t.EdgeIR("loop", header=3, body_entry=4, exit_node=5),
        t.EdgeIR("loopBack", from_node=4, to_node=3),
        t.EdgeIR("seq", from_node=5, to_node=6),
        t.EdgeIR("seq", from_node=6, to_node=7),
        t.EdgeIR("switch", cond_node=7, branches=[8, 9, 10, 11], default_case=12),
        t.EdgeIR("seq", from_node=8, to_node=13),
        t.EdgeIR("seq", from_node=9, to_node=13),
        t.EdgeIR("seq", from_node=10, to_node=13),
        t.EdgeIR("seq", from_node=11, to_node=13),
        t.EdgeIR("seq", from_node=12, to_node=13),
        t.EdgeIR("branch", cond_node=14, then_entry=15, else_entry=16),
        t.EdgeIR("seq", from_node=13, to_node=14),
        t.EdgeIR("seq", from_node=15, to_node=17),
        t.EdgeIR("seq", from_node=16, to_node=17),
        t.EdgeIR("seq", from_node=17, to_node=18),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal="Reproduce the issue described by the PR and produce a git patch that fixes it.",
        sub_goals=[
            SubGoal("repository_oriented", "repo_overview", P("isNonEmptyString"),
                    "Repository layout and main package identified via orientation step.",
                    [GPK("pathCoverage")]),
            SubGoal("candidates_located", "candidate_files_report", P("isNonEmptyString"),
                    "Candidate source files reported with a primary suspect.",
                    [GPK("pathCoverage")]),
            SubGoal("candidates_inspected", "candidate_file_list", P("isNonEmptyString"),
                    "Candidate list is iterated; body produces no save_as so scouting is lost.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
            SubGoal("issue_reproduced", "reproduction_report", P("isNonEmptyString"),
                    "Reproduction script status captured.",
                    [GPK("pathCoverage")]),
            SubGoal("strategy_chosen", "fix_strategy", P("isNonEmptyString"),
                    "A fix strategy enum is produced.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_applied", "fix_application", P("isNonEmptyString"),
                    "One switch case applied a fix. Free-form diff — no markInfoContent.",
                    [GPK("pathCoverage"), GPK("verificationCoverage")]),
            SubGoal("post_fix_verified", "post_fix_verification", P("isNonEmptyString"),
                    "Titled repro_after_fix status captured.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_adjusted", "fix_adjustment", P("isNonEmptyString"),
                    "One-shot adjustment with NO re-verification — post_fix_verification stays stale.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack"), GPK("verificationCoverage")]),
            SubGoal("edge_cases_checked", "edge_case_report", P("isNonEmptyString"),
                    "Edge case synthesis consuming a possibly-stale post_fix_verification.",
                    [GPK("pathCoverage"), GPK("informationSufficiency")]),
            SubGoal("patch_submitted", "submission_result",
                    P("containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
                    "Patch submitted, but modified_files aspect is not structurally extractable.",
                    [GPK("pathCoverage"), GPK("failSafe")]),
        ],
    )

    ir = t.WorkflowIR(
        name="seed_004",
        goal="Reproduce the issue described by the PR and produce a git patch that fixes it.",
        parameters=parameters, nodes=nodes, edges=edges,
        entry=0, exits=[18],
        param_postcond=param_postcond,
        goal_spec=goal_spec,
        expected_semantically_sound=False,
        emit_structural_theorems=False,  # switch branches all write fix_application → allWritesConsistent=false
    )
    return ir


if __name__ == "__main__":
    save(build(), "seed_004_layer2_v2")
