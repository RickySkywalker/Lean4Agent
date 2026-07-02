"""Author IR JSON for passed_workflow_1_layer2_v2.lean.

5 task nodes. All preconditions expressed via precond_extra so ordering
matches the hand-written Lean exactly.
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
    "For each response:\n"
    "1. Include a THOUGHT section explaining your reasoning and what you're trying to accomplish\n"
    "2. Provide one or more bash tool calls to execute\n"
    "\n"
    "<boundaries>\n"
    "- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)\n"
    "- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n"
    "</boundaries>\n"
    "\n"
    "Now begin. Start by exploring the repository structure at /testbed to understand the codebase, focusing on files and directories most relevant to the issue described in the PR description."
)

NODE1_INSTR = (
    "Now that you've explored the repository, create a script to reproduce the issue described in the PR description.\n"
    "\n"
    "Steps:\n"
    "1. Based on the PR description and the code you've read, write a small reproduction script (e.g. /testbed/reproduce_issue.py or /testbed/reproduce_issue.sh) that demonstrates the bug or failure.\n"
    "2. Run the script and confirm the issue is reproducible. Show the error output.\n"
    "3. If the issue is not directly reproducible with a simple script (e.g., it's a behavioral or logic error), explain what you observe and how it differs from expected behavior.\n"
    "\n"
    "Remember:\n"
    "- Work in the /testbed directory\n"
    "- Use non-interactive commands only\n"
    "- Every response MUST include at least one bash tool call"
)

NODE2_INSTR = (
    "Now that you've reproduced the issue, locate the relevant source code and implement a fix.\n"
    "\n"
    "Steps:\n"
    "1. Identify the exact source files and functions that need to be changed\n"
    "2. Understand the root cause of the issue by reading the relevant code carefully\n"
    "3. Implement a fix that:\n"
    "   - Addresses the root cause, not just the symptoms\n"
    "   - Is consistent with the existing codebase style and patterns\n"
    "   - Is general enough to handle edge cases\n"
    "   - Does NOT modify any test files or configuration files (pyproject.toml, setup.cfg, etc.)\n"
    "4. Use sed, python scripts, or heredocs to make the edits -- do NOT use interactive editors\n"
    "\n"
    "Remember:\n"
    "- Work in the /testbed directory\n"
    "- Every response MUST include at least one bash tool call\n"
    "- ONLY modify regular source code files"
)

NODE3_INSTR = (
    "Now verify that your fix resolves the issue.\n"
    "\n"
    "Steps:\n"
    "1. Re-run the reproduction script you created earlier to confirm the issue is fixed\n"
    "2. If there is a regression test command available, run it: {{regression_test_cmd}}\n"
    "3. Test edge cases to ensure your fix is robust and doesn't break other functionality\n"
    "4. If anything fails, go back and refine your fix\n"
    "\n"
    "Remember:\n"
    "- Work in the /testbed directory\n"
    "- Every response MUST include at least one bash tool call"
)

NODE4_INSTR = (
    "Your fix is verified. Now create and submit the final patch.\n"
    "\n"
    "Follow these steps IN ORDER, with SEPARATE commands:\n"
    "\n"
    "Step 1: Create the patch file\n"
    "Run `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\n"
    "Do NOT commit your changes.\n"
    "<IMPORTANT>\n"
    "The patch must only contain changes to the specific source files you modified to fix the issue.\n"
    "Do not submit file creations or changes to any of the following files:\n"
    "- test and reproduction files\n"
    "- helper scripts, tests, or tools that you created\n"
    "- installation, build, packaging, configuration, or setup scripts\n"
    "- binary or compiled files\n"
    "</IMPORTANT>\n"
    "\n"
    "Step 2: Verify your patch\n"
    "Inspect patch.txt to confirm it only contains your intended changes.\n"
    "\n"
    "Step 3: Submit (EXACT command required)\n"
    "You MUST use this EXACT command to submit:\n"
    "```bash\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt\n"
    "```"
)


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="explore_repository", step_type="task",
            reads=[TV("problem_statement", predicates=[])],
            writes=[],
            instruction=NODE0_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("repository_understanding", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
            implicit_retries=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=1, name="reproduce_issue", step_type="task",
            reads=[], writes=[],
            instruction=NODE1_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("repository_understanding", "isNonEmptyString"),
            ],
            postcond_extra=[VP("reproduction_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
            implicit_retries=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=2, name="fix_issue", step_type="task",
            reads=[], writes=[],
            instruction=NODE2_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("reproduction_evidence", "isNonEmptyString"),
                VP("repository_understanding", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_implementation_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=3, name="verify_fix", step_type="task",
            reads=[TV("regression_test_cmd", predicates=[])],
            writes=[],
            instruction=NODE3_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("regression_test_cmd", "nameExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
                VP("reproduction_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_verification_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_verified")],
        ),
        t.NodeIR(
            id=4, name="create_patch", step_type="task",
            reads=[], writes=[],
            instruction=NODE4_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
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
            "Given a GitHub issue, reproduce it and fix it by producing a minimal git patch"
        ),
        sub_goals=[
            SubGoal(
                name="repository_explored",
                variable_name="repository_understanding",
                required_predicate=P("isNonEmptyString"),
                description=(
                    "Evidence that the repository structure was explored and relevant source "
                    "files were identified based on the GitHub issue."
                ),
                required_graph_predicates=[GPK("pathCoverage")],
            ),
            SubGoal(
                name="issue_reproduced",
                variable_name="reproduction_evidence",
                required_predicate=P("isNonEmptyString"),
                description=(
                    "Evidence that a reproduction script was created and the bug was reproduced. "
                    "Context continuity PASSES because task chain provides conversation history."
                ),
                required_graph_predicates=[GPK("pathCoverage"), GPK("contextContinuity")],
            ),
            SubGoal(
                name="fix_implemented",
                variable_name="fix_implementation_evidence",
                required_predicate=P("isNonEmptyString"),
                description=(
                    "Evidence that source code was modified to fix the issue. "
                    "Context flows via task chain. "
                    "unifiedLoopBack PASSES due to markImplicitRetry on task nodes."
                ),
                required_graph_predicates=[
                    GPK("pathCoverage"),
                    GPK("contextContinuity"),
                    GPK("informationSufficiency"),
                    GPK("unifiedLoopBack"),
                    GPK("verificationCoverage"),
                ],
            ),
            SubGoal(
                name="fix_verified",
                variable_name="fix_verification_evidence",
                required_predicate=P("isNonEmptyString"),
                description=(
                    "Evidence that the fix was verified by rerunning reproduction and regression "
                    "tests. Context continuity PASSES via task chain."
                ),
                required_graph_predicates=[GPK("pathCoverage"), GPK("contextContinuity")],
            ),
            SubGoal(
                name="patch_submitted",
                variable_name="patch_submission_evidence",
                required_predicate=P("isNonEmptyString"),
                description=(
                    "Evidence that a git patch was created and submitted. "
                    "Context flows via task chain but no fail-safe exists."
                ),
                required_graph_predicates=[
                    GPK("pathCoverage"),
                    GPK("contextContinuity"),
                    GPK("failSafe"),
                ],
            ),
        ],
    )

    ir = t.WorkflowIR(
        name="passed_workflow_1_v2",
        goal=(
            "Given a GitHub issue, reproduce it and fix it by producing a minimal git patch"
        ),
        parameters=parameters,
        nodes=nodes,
        edges=seq_edges(5),
        entry=0,
        exits=[4],
        goal_spec=goal_spec,
    )
    ir.infer_param_postcond()
    return ir


if __name__ == "__main__":
    save(build(), "passed_workflow_1_layer2_v2")
