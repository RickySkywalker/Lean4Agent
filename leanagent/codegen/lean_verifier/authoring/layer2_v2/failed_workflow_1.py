"""Author IR JSON for failed_workflow_1_layer2_v2.lean.

5 step nodes with broken information flow. expected_semantically_sound=False.
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
    "IMPORTANT BOUNDARIES:\n"
    "- MODIFY: Regular source code files in /testbed (this is the working directory for all your subsequent commands)\n"
    "- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n"
    "\n"
    "Begin by exploring the repository structure to understand the codebase. Identify the relevant source files that may need to be changed based on the PR description.\n"
    "\n"
    "Start now. Explore the repository at {{code_path}} to understand the project structure, find relevant files, and understand the codebase organization."
)

NODE1_INSTR = (
    "<pr_description>\n"
    "Consider the following PR description:\n"
    "{{problem_statement}}\n"
    "</pr_description>\n"
    "\n"
    "Based on your exploration of the codebase, now create a script to reproduce the issue described in the PR description. Write a small Python (or appropriate language) script that demonstrates the bug.\n"
    "\n"
    "Steps:\n"
    "1. Create a reproduction script at /testbed/reproduce_issue.py (or appropriate extension)\n"
    "2. Run the script to confirm the issue exists\n"
    "3. Analyze the error output to understand the root cause\n"
    "\n"
    "IMPORTANT:\n"
    "- The working directory for all commands is /testbed\n"
    "- Directory or environment variable changes are not persistent\n"
    "- Prefix commands with `cd /testbed && ...`\n"
    "- Your response MUST include AT LEAST ONE bash tool call"
)

NODE2_INSTR = (
    "<pr_description>\n"
    "Consider the following PR description:\n"
    "{{problem_statement}}\n"
    "</pr_description>\n"
    "\n"
    "Now that you've reproduced the issue and understand the root cause, implement a fix.\n"
    "\n"
    "Follow this workflow:\n"
    "1. Identify the exact source file(s) and location(s) that need to be modified\n"
    "2. Understand the surrounding code logic before making changes\n"
    "3. Implement the minimal, targeted fix that addresses the issue\n"
    "4. Make sure your fix is general and consistent with the existing codebase patterns\n"
    "\n"
    "IMPORTANT BOUNDARIES:\n"
    "- MODIFY: Regular source code files in /testbed\n"
    "- DO NOT MODIFY: Tests, configuration files (pyproject.toml, setup.cfg, etc.)\n"
    "- Use `sed`, `python -c`, or heredoc to edit files (no interactive editors)\n"
    "- Your response MUST include AT LEAST ONE bash tool call"
)

NODE3_INSTR = (
    "<pr_description>\n"
    "Consider the following PR description:\n"
    "{{problem_statement}}\n"
    "</pr_description>\n"
    "\n"
    "Verify your fix works correctly:\n"
    "1. Run your reproduction script again to confirm the issue is resolved\n"
    "2. Test edge cases to ensure your fix is robust and doesn't introduce regressions\n"
    "3. If a regression test command is available ({{regression_test_cmd}}), run it\n"
    "4. If the fix doesn't work, iterate: analyze what went wrong, adjust, and re-test\n"
    "\n"
    "IMPORTANT:\n"
    "- The working directory for all commands is /testbed\n"
    "- Directory or environment variable changes are not persistent\n"
    "- Prefix commands with `cd /testbed && ...`\n"
    "- Your response MUST include AT LEAST ONE bash tool call"
)

NODE4_INSTR = (
    "Your fix has been verified. Now submit your changes as a git patch.\n"
    "\n"
    "Follow these steps IN ORDER, with SEPARATE commands:\n"
    "\n"
    "Step 1: Create the patch file\n"
    "Run `cd /testbed && git diff -- path/to/file1 path/to/file2 > patch.txt` listing only the source files you modified.\n"
    "Do NOT commit your changes.\n"
    "<IMPORTANT>\n"
    "The patch must only contain changes to the specific source files you modified to fix the issue.\n"
    "Do not submit file creations or changes to any of the following files:\n"
    "- test and reproduction files (e.g., reproduce_issue.py)\n"
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
            id=0, name="setup_and_explore", step_type="step",
            reads=[TV("code_path", predicates=[]), TV("problem_statement", predicates=[])],
            writes=[], instruction=NODE0_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("code_path", "isValidFilePath"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("repository_exploration_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("repository_explored")],
        ),
        t.NodeIR(
            id=1, name="reproduce_issue", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[], instruction=NODE1_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                t.InfoContentIR("repository_exploration_evidence", "relevant_files"),
                t.InfoContentIR("repository_exploration_evidence", "project_structure"),
            ],
            postcond_extra=[VP("issue_reproduction_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=2, name="implement_fix", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[], instruction=NODE2_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("issue_reproduction_evidence", "isNonEmptyString"),
                t.InfoContentIR("repository_exploration_evidence", "relevant_files"),
            ],
            postcond_extra=[VP("fix_implementation_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=3, name="verify_fix", step_type="step",
            reads=[TV("problem_statement", predicates=[]), TV("regression_test_cmd", predicates=[])],
            writes=[], instruction=NODE3_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
                VP("regression_test_cmd", "nameExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
                VP("issue_reproduction_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("fix_verification_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=4, name="submit_patch", step_type="step",
            reads=[], writes=[], instruction=NODE4_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_implementation_evidence", "isNonEmptyString"),
            ],
            postcond_extra=[VP("patch_submission_evidence", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_submitted")],
        ),
    ]

    parameters = [
        TV("code_path", "TString", predicates=[P("isValidFilePath")]),
        TV("problem_statement", "TString", predicates=[P("isNonEmptyString")]),
        TV("regression_test_cmd", "TString", predicates=[]),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal=(
            "Given a GitHub issue, reproduce the bug and fix it by modifying source code, "
            "then submit a patch"
        ),
        sub_goals=[
            SubGoal("repository_explored", "repository_exploration_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the repository structure was explored and relevant source files were identified based on the GitHub issue.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_reproduced", "issue_reproduction_evidence",
                    P("isNonEmptyString"),
                    "Evidence that a reproduction script was created and the bug was reproduced. Requires context continuity from exploration step, which is MISSING.",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("fix_implemented", "fix_implementation_evidence",
                    P("isNonEmptyString"),
                    "Evidence that source code was modified to fix the issue. Requires context from exploration and reproduction, which is MISSING. Also needs retry capability, which is MISSING.",
                    [GPK("pathCoverage"), GPK("contextContinuity"),
                     GPK("informationSufficiency"), GPK("unifiedLoopBack"),
                     GPK("verificationCoverage")]),
            SubGoal("fix_verified", "fix_verification_evidence",
                    P("isNonEmptyString"),
                    "Evidence that the fix was verified. Requires knowledge of what was fixed, which is MISSING (step type, no save_as from implement_fix).",
                    [GPK("pathCoverage"), GPK("contextContinuity")]),
            SubGoal("patch_submitted", "patch_submission_evidence",
                    P("isNonEmptyString"),
                    "Evidence that a git patch was created and submitted. Requires knowledge of modified files, which is MISSING.",
                    [GPK("pathCoverage"), GPK("contextContinuity"), GPK("failSafe")]),
        ],
    )

    ir = t.WorkflowIR(
        name="failed_workflow_1",
        goal=(
            "Given a GitHub issue, reproduce the bug and fix it by modifying source code, "
            "then submit a patch"
        ),
        parameters=parameters,
        nodes=nodes,
        edges=seq_edges(5),
        entry=0, exits=[4],
        goal_spec=goal_spec,
        expected_semantically_sound=False,
    )
    ir.infer_param_postcond()
    return ir


if __name__ == "__main__":
    save(build(), "failed_workflow_1_layer2_v2")
