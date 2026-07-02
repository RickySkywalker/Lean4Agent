"""Author IR JSON for passed_workflow_2_layer2_v2.lean.

9 nodes: node 0 is step, nodes 1-8 form a task chain. expected_sound=True.
"""

from _common import t, P, VP, TV, GPK, SubGoal, save, seq_edges


NODE0_INSTR = (
    "<pr_description>\n"
    "Consider the following PR description:\n"
    "{{problem_statement}}\n"
    "</pr_description>\n"
    "\n"
    "You're a software engineer interacting continuously with a computer by submitting commands.\n"
    "You'll be helping implement necessary changes to meet requirements in the PR description.\n"
    "Your task is specifically to make changes to non-test files in the current directory in order to fix the issue described in the PR description in a way that is general and consistent with the codebase.\n"
    "<IMPORTANT>This is an interactive process where you will think and issue AT LEAST ONE command for every step, see the result, then think and issue your next command(s).</IMPORTANT>\n"
    "\n"
    "For each response:\n"
    "1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n"
    "2. Provide one or more bash tool calls to execute\n"
    "\n"
    "Start by exploring the repository structure to understand the codebase. List the top-level directory structure of /testbed and identify key files related to the issue."
)

NODE1_INSTR = (
    "Continue exploring the codebase. Based on the PR description, identify and read the most relevant source files.\n"
    "Use grep, find, and cat to locate the code areas that need changes.\n"
    "Focus on understanding the current behavior that causes the issue."
)

NODE2_INSTR = (
    "Now create a script to reproduce the issue described in the PR description.\n"
    "Save the script to /testbed/reproduce_issue.py (or a similarly named script).\n"
    "Run the script and confirm that the issue is reproduced.\n"
    "Show the error output or incorrect behavior."
)

NODE3_INSTR = (
    "Based on the reproduction and your codebase exploration, identify the root cause of the issue.\n"
    "Read the specific source files and functions responsible for the bug.\n"
    "Explain your analysis and pinpoint the exact lines/functions that need to be modified."
)

NODE4_INSTR = (
    "Implement the fix for the issue. Edit the source code files to resolve the bug.\n"
    "Remember:\n"
    "- ONLY modify regular source code files in /testbed\n"
    "- DO NOT modify test files, configuration files (pyproject.toml, setup.cfg, etc.)\n"
    "- Make targeted, minimal changes that fix the issue without breaking other functionality\n"
    "- Ensure your fix is general and consistent with the codebase style"
)

NODE5_INSTR = (
    "Run the reproduction script again to verify that the fix resolves the issue.\n"
    "The script should now produce the expected/correct behavior instead of the error.\n"
    "If the fix does not work, iterate on your changes."
)

NODE6_INSTR = (
    "Test edge cases to ensure the fix is robust:\n"
    "1. Create additional test scenarios in your reproduction script to cover edge cases\n"
    "2. Run the existing test suite if applicable: {{regression_test_cmd}}\n"
    "3. Verify that you haven't introduced any regressions\n"
    "\n"
    "If any edge case fails, go back and refine your fix."
)

NODE7_INSTR = (
    "Now create the final patch. Follow these steps IN ORDER, with SEPARATE commands:\n"
    "\n"
    "Step 1: Create the patch file\n"
    "Run `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\n"
    "Do NOT commit your changes.\n"
    "\n"
    "Step 2: Verify your patch\n"
    "Inspect patch.txt to confirm it only contains your intended changes and headers show `--- a/` and `+++ b/` paths."
)

NODE8_INSTR = (
    "Submit your patch using this EXACT command:\n"
    "```bash\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n"
    "```\n"
    "If the command fails (nonzero exit status), it will not submit."
)


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="present_problem", step_type="step",
            reads=[TV("code_path", predicates=[]), TV("problem_statement", predicates=[])],
            writes=[], instruction=NODE0_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("code_path", "isValidFilePath"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("initial_exploration_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=1, name="explore_codebase", step_type="task",
            reads=[], writes=[], instruction=NODE1_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("codebase_exploration_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
            implicit_retries=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=2, name="reproduce_issue", step_type="task",
            reads=[], writes=[], instruction=NODE2_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("codebase_exploration_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("issue_reproduction_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
            implicit_retries=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=3, name="identify_root_cause", step_type="task",
            reads=[], writes=[], instruction=NODE3_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("codebase_exploration_evidence", "isNonEmptyString"),
                VP("issue_reproduction_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("root_cause_analysis_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("root_cause_identified")],
            implicit_retries=[t.SubGoalTagIR("root_cause_identified")],
        ),
        t.NodeIR(
            id=4, name="implement_fix", step_type="task",
            reads=[], writes=[], instruction=NODE4_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("root_cause_analysis_evidence", "isNonEmptyString"),
                VP("issue_reproduction_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_implementation_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=5, name="verify_fix", step_type="task",
            reads=[], writes=[], instruction=NODE5_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
                VP("issue_reproduction_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_verification_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_verified")],
        ),
        t.NodeIR(
            id=6, name="test_edge_cases", step_type="task",
            reads=[TV("regression_test_cmd", predicates=[])], writes=[], instruction=NODE6_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("regression_test_cmd", "nameExists"),
                VP("fix_verification_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("edge_case_test_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("edge_cases_tested")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_verified")],
            implicit_retries=[t.SubGoalTagIR("edge_cases_tested")],
        ),
        t.NodeIR(
            id=7, name="create_patch", step_type="task",
            reads=[], writes=[], instruction=NODE7_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("patch_creation_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_created")],
            implicit_retries=[t.SubGoalTagIR("patch_created")],
        ),
        t.NodeIR(
            id=8, name="submit_patch", step_type="task",
            reads=[], writes=[], instruction=NODE8_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("patch_creation_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("patch_submission_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_submitted")],
            implicit_retries=[t.SubGoalTagIR("patch_submitted")],
        ),
    ]

    parameters = [
        TV("code_path", "TString", predicates=[P("isValidFilePath")]),
        TV("problem_statement", "TString", predicates=[P("isNonEmptyString")]),
        TV("regression_test_cmd", "TString", predicates=[]),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal=(
            "Given a GitHub issue, reproduce the bug and fix it by producing a minimal source-code patch"
        ),
        sub_goals=[
            SubGoal("repository_explored", "codebase_exploration_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the repository structure was explored and relevant source files were identified. Node 0 (step) does initial exploration but its results are lost. Node 1 (task) re-explores.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_reproduced", "issue_reproduction_evidence",
                    P("isNonEmptyString"),
                    "Evidence that a reproduction script was created and the bug was confirmed. Task chain provides context continuity from exploration.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("root_cause_identified", "root_cause_analysis_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the root cause was identified via analysis of reproduction results and codebase exploration.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("fix_implemented", "fix_implementation_evidence",
                    P("isNonEmptyString"),
                    "Evidence that source code was modified to fix the issue. Task chain carries root cause analysis and reproduction context.",
                    [GPK("pathCoverage"), GPK("contextContinuity"),
                     GPK("informationSufficiency"), GPK("unifiedLoopBack"),
                     GPK("verificationCoverage")]),
            SubGoal("fix_verified", "fix_verification_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the fix was verified by re-running the reproduction script. Task chain carries full implementation context.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("edge_cases_tested", "edge_case_test_evidence",
                    P("isNonEmptyString"),
                    "Evidence that edge cases were tested and regression tests were run.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("patch_created", "patch_creation_evidence",
                    P("isNonEmptyString"),
                    "Evidence that a git patch was created containing only the source file changes.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("patch_submitted", "patch_submission_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the patch was submitted via COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT.",
                    [GPK("pathCoverage"), GPK("contextContinuity"), GPK("failSafe")]),
        ],
    )

    ir = t.WorkflowIR(
        name="passed_workflow_2_v2",
        goal=(
            "Given a GitHub issue, reproduce the bug and fix it by producing a minimal source-code patch"
        ),
        parameters=parameters, nodes=nodes, edges=seq_edges(9),
        entry=0, exits=[8],
        goal_spec=goal_spec,
    )
    ir.infer_param_postcond()
    return ir


if __name__ == "__main__":
    save(build(), "passed_workflow_2_layer2_v2")
