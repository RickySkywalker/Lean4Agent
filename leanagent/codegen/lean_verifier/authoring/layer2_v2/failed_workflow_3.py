"""Author IR JSON for failed_workflow_3_layer2_v2.lean.

7 nodes: 4 task (0-3) + 3 step (4-6). Info flows: task chain for 0-3,
save_as variables for 4-6. Uses markInfoContent in both preconds and postconds.
Node 6 postcond uses varContainsSentinel (containsSubstring).
paramNode has isNonEmptyString regression_test_cmd.
"""

from _common import t, P, VP, TV, GPK, SubGoal, save, seq_edges


NODE0_INSTR = (
    "Phase 1: Codebase Exploration & Issue Understanding\n"
    "\n"
    "You are a software engineer. Your working directory is /testbed.\n"
    "Your goal in this phase is to understand the codebase structure and the issue.\n"
    "\n"
    "{{problem_statement}}\n"
    "\n"
    "Step 1: Explore the repository structure\n"
    "Step 2: Understand the issue\n"
    "Step 3: Locate relevant source files\n"
    "\n"
    "Deliverable:\n"
    "1. Repository structure\n"
    "2. Issue summary\n"
    "3. Relevant files\n"
    "4. Initial hypothesis\n"
    "\n"
    "IMPORTANT: Do NOT modify any files in this phase.\n"
)

NODE1_INSTR = (
    "Phase 2: Issue Reproduction\n"
    "\n"
    "Based on the exploration from Phase 1:\n"
    "{{exploration_summary}}\n"
    "\n"
    "Create a minimal reproduction script that demonstrates the bug.\n"
    "\n"
    "Deliverable:\n"
    "1. Reproduction script path\n"
    "2. Reproduction output\n"
    "3. Root cause analysis\n"
)

NODE2_INSTR = (
    "Phase 3: Implement the Fix\n"
    "\n"
    "Based on the reproduction from Phase 2:\n"
    "{{reproduction_result}}\n"
    "\n"
    "Edit the source code to fix the issue. Make MINIMAL changes.\n"
    "\n"
    "Deliverable:\n"
    "1. Files modified\n"
    "2. Changes made\n"
    "3. Rationale\n"
)

NODE3_INSTR = (
    "Phase 4: Verify the Fix\n"
    "\n"
    "Based on the fix from Phase 3:\n"
    "{{fix_summary}}\n"
    "\n"
    "Verify that the fix resolves the issue without regressions.\n"
    "\n"
    "Deliverable:\n"
    "1. Reproduction result\n"
    "2. Edge case results\n"
    "3. Regression test results\n"
    "4. Final status: VERIFIED or NEEDS_REVISION\n"
)

NODE4_INSTR = (
    "Phase 5a: Generate the Patch\n"
    "\n"
    "The fix has been verified:\n"
    "{{verification_result}}\n"
    "\n"
    "The files that were modified during the fix:\n"
    "{{fix_summary}}\n"
    "\n"
    "Generate a git diff patch containing ONLY the source file changes.\n"
    "Do NOT include test files, helper scripts, or configuration files.\n"
)

NODE5_INSTR = (
    "Phase 5b: Verify the Patch\n"
    "\n"
    "A patch was generated in the previous step:\n"
    "{{patch_generation_result}}\n"
    "\n"
    "Read and inspect /testbed/patch.txt.\n"
    "Verify that the patch contains ONLY intended source file changes.\n"
    "\n"
    "Return either:\n"
    "- PATCH_VERIFIED if the patch is correct\n"
    "- A description of what needs to be fixed if it is not\n"
)

NODE6_INSTR = (
    "Phase 5c: Submit the Patch\n"
    "\n"
    "The patch has been verified:\n"
    "{{patch_verification_result}}\n"
    "\n"
    "Submit the patch using this EXACT command:\n"
    "```\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt\n"
    "```\n"
    "\n"
    "CRITICAL: You CANNOT continue working after submission.\n"
)


def build() -> "t.WorkflowIR":
    nodes = [
        t.NodeIR(
            id=0, name="explore_and_understand", step_type="task",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("exploration_summary", predicates=[])],
            instruction=NODE0_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[VP("exploration_summary", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("codebase_explored")],
            implicit_retries=[t.SubGoalTagIR("codebase_explored")],
        ),
        t.NodeIR(
            id=1, name="reproduce_issue", step_type="task",
            reads=[TV("exploration_summary", predicates=[])],
            writes=[TV("reproduction_result", predicates=[])],
            instruction=NODE1_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("exploration_summary", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("reproduction_result", "isNonEmptyString"),
                t.InfoContentIR("reproduction_result", "reproduction_script_path"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
            implicit_retries=[t.SubGoalTagIR("issue_reproduced")],
        ),
        t.NodeIR(
            id=2, name="implement_fix", step_type="task",
            reads=[TV("reproduction_result", predicates=[])],
            writes=[TV("fix_summary", predicates=[])],
            instruction=NODE2_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("reproduction_result", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("fix_summary", "isNonEmptyString"),
                t.InfoContentIR("fix_summary", "files_modified"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_implemented")],
        ),
        t.NodeIR(
            id=3, name="verify_fix", step_type="task",
            reads=[TV("fix_summary", predicates=[])],
            writes=[TV("verification_result", predicates=[])],
            instruction=NODE3_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_summary", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("verification_result", "isNonEmptyString"),
                t.InfoContentIR("verification_result", "verification_status"),
            ],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
            implicit_retries=[t.SubGoalTagIR("fix_verified")],
        ),
        t.NodeIR(
            id=4, name="generate_patch", step_type="step",
            reads=[TV("verification_result", predicates=[]), TV("fix_summary", predicates=[])],
            writes=[TV("patch_generation_result", predicates=[])],
            instruction=NODE4_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("verification_result", "isNonEmptyString"),
                t.InfoContentIR("verification_result", "verification_status"),
                VP("fix_summary", "isNonEmptyString"),
                t.InfoContentIR("fix_summary", "files_modified"),
            ],
            postcond_extra=[
                VP("patch_generation_result", "isNonEmptyString"),
                t.InfoContentIR("patch_generation_result", "patch_file_path"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_created")],
        ),
        t.NodeIR(
            id=5, name="verify_patch", step_type="step",
            reads=[TV("patch_generation_result", predicates=[])],
            writes=[TV("patch_verification_result", predicates=[])],
            instruction=NODE5_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("patch_generation_result", "isNonEmptyString"),
                t.InfoContentIR("patch_generation_result", "patch_file_path"),
            ],
            postcond_extra=[
                VP("patch_verification_result", "isNonEmptyString"),
                t.InfoContentIR("patch_verification_result", "patch_status"),
            ],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("patch_created")],
        ),
        t.NodeIR(
            id=6, name="submit_patch", step_type="step",
            reads=[TV("patch_verification_result", predicates=[])],
            writes=[TV("issue_solution", predicates=[])],
            instruction=NODE6_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("patch_verification_result", "isNonEmptyString"),
                t.InfoContentIR("patch_verification_result", "patch_status"),
            ],
            postcond_extra=[
                VP("issue_solution", "isNonEmptyString"),
                VP("issue_solution", "containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_submitted")],
        ),
    ]

    parameters = [
        TV("code_path", "TString", predicates=[P("isValidFilePath")]),
        TV("problem_statement", "TString", predicates=[P("isNonEmptyString")]),
        TV("regression_test_cmd", "TString", predicates=[P("isNonEmptyString")]),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal=(
            "Given a GitHub issue, systematically reproduce, diagnose, fix, and verify "
            "the issue through a structured multi-phase workflow"
        ),
        sub_goals=[
            SubGoal("codebase_explored", "exploration_summary",
                    P("isNonEmptyString"),
                    "Evidence that the repository structure and issue-relevant source areas have been explored and understood.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_reproduced", "reproduction_result",
                    P("isNonEmptyString"),
                    "Evidence that the reported bug has been reproduced with a concrete script or procedure.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_implemented", "fix_summary",
                    P("isNonEmptyString"),
                    "Evidence that a source-code fix addressing the root cause of the issue has been implemented.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack"),
                     GPK("verificationCoverage"), GPK("failSafe")]),
            SubGoal("fix_verified", "verification_result",
                    P("isNonEmptyString"),
                    "Evidence that the implemented fix was verified by re-running reproduction and targeted tests.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack")]),
            SubGoal("patch_created", "patch_generation_result",
                    P("isNonEmptyString"),
                    "Evidence that a clean git patch containing only the fix changes was created.",
                    [GPK("pathCoverage")]),
            SubGoal("patch_verified", "patch_verification_result",
                    P("isNonEmptyString"),
                    "Evidence that the generated patch was inspected and confirmed to contain only intended changes.",
                    [GPK("pathCoverage")]),
            SubGoal("patch_submitted", "issue_solution",
                    P("containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
                    "Evidence that the final patch was submitted as the workflow output.",
                    [GPK("pathCoverage")]),
        ],
    )

    ir = t.WorkflowIR(
        name="failed_workflow_3_v2",
        goal=(
            "Given a GitHub issue, systematically reproduce, diagnose, fix, and verify the issue through a structured multi-phase workflow."
        ),
        parameters=parameters, nodes=nodes, edges=seq_edges(7),
        entry=0, exits=[6],
        goal_spec=goal_spec,
    )
    ir.infer_param_postcond()
    return ir


if __name__ == "__main__":
    save(build(), "failed_workflow_3_layer2_v2")
