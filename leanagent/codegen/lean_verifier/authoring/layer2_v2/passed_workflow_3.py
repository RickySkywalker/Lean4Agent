"""Author IR JSON for passed_workflow_3_layer2_v2.lean.

11 nodes including a whileLoop (node 3) and a conditional (node 7) with two exits.
Parameters mix TString and TInt. paramNode ordering is irregular so we set
param_postcond explicitly rather than rely on infer_param_postcond.
"""

from _common import t, P, VP, TV, GPK, SubGoal, save


NODE0_INSTR = (
    "Explore the repository and understand the issue described in the problem statement.\n"
    "\n"
    "{{problem_statement}}\n"
    "\n"
    "Explore the repo structure, read relevant source files, identify the area of code related to the issue, and form a hypothesis about the root cause.\n"
    "\n"
    "Return a STRUCTURED summary:\n"
    "```\n"
    "PROJECT: <project name and description>\n"
    "ISSUE SUMMARY: <concise summary of the reported issue>\n"
    "KEY SYMPTOMS: <observable symptoms of the bug>\n"
    "RELEVANT FILES: <list of relevant source files>\n"
    "ROOT CAUSE HYPOTHESIS: <your initial hypothesis>\n"
    "```\n"
)

NODE1_INSTR = (
    "Based on the codebase analysis, create a reproduction script that demonstrates the bug.\n"
    "\n"
    "{{codebase_analysis}}\n"
    "\n"
    "Create a minimal script that triggers the reported issue. Run it and confirm the bug is present.\n"
    "\n"
    "Return a STRUCTURED summary:\n"
    "```\n"
    "REPRODUCTION STATUS: <REPRODUCED|FAILED_TO_REPRODUCE>\n"
    "REPRODUCTION SCRIPT: <path to script>\n"
    "OBSERVED ERROR: <error message or incorrect output>\n"
    "EXPECTED BEHAVIOR: <what should happen instead>\n"
    "```\n"
)

NODE2_INSTR = (
    "Pinpoint the exact source files and code causing the bug.\n"
    "\n"
    "Codebase analysis:\n"
    "{{codebase_analysis}}\n"
    "\n"
    "Reproduction result:\n"
    "{{reproduction_result}}\n"
    "\n"
    "Trace through the code to identify the precise location and mechanism of the bug.\n"
    "\n"
    "Return a STRUCTURED analysis:\n"
    "```\n"
    "ROOT CAUSE: <precise description of the bug mechanism>\n"
    "FILES TO MODIFY: <list of files that need changes>\n"
    "SPECIFIC LOCATIONS: <function names, line ranges>\n"
    "PLANNED FIX: <description of the fix strategy>\n"
    "```\n"
)

NODE4_INSTR = (
    "Edit source code to fix the bug based on the root cause analysis.\n"
    "\n"
    "Root cause analysis:\n"
    "{{root_cause_analysis}}\n"
    "\n"
    "Codebase analysis:\n"
    "{{codebase_analysis}}\n"
    "\n"
    "Reproduction result:\n"
    "{{reproduction_result}}\n"
    "\n"
    "Retry notes (from previous attempts):\n"
    "{{retry_notes}}\n"
    "\n"
    "Make the minimal, targeted changes to fix the issue. If this is a retry, use the retry notes to avoid repeating previous mistakes.\n"
    "\n"
    "Return:\n"
    "```\n"
    "MODIFIED FILES: <list of modified files>\n"
    "CHANGES MADE: <description of changes>\n"
    "```\n"
)

NODE5_INSTR = (
    "Verify the fix by re-running the reproduction script and running targeted tests.\n"
    "\n"
    "Fix description:\n"
    "{{fix_description}}\n"
    "\n"
    "Run the reproduction script to check if the bug is fixed. Then run targeted tests for the modified module.\n"
    "\n"
    "Return:\n"
    "```\n"
    "VERIFICATION STATUS: <PASS|FAIL>\n"
    "REPRODUCTION RESULT: <result of re-running the reproduction script>\n"
    "TARGETED TESTS: <result of running targeted tests>\n"
    "ISSUES FOUND: <any remaining issues, or 'none'>\n"
    "```\n"
)

NODE6_INSTR = (
    "Analyze the verification result and determine if the fix is verified.\n"
    "\n"
    "{{verification_result}}\n"
    "\n"
    "Return exactly one of:\n"
    "- FIX_VERIFIED=true  (if all checks pass)\n"
    "- FIX_VERIFIED=false (if any check fails)\n"
)

NODE8_INSTR = (
    "Create the final patch from your verified fix.\n"
    "\n"
    "Fix description:\n"
    "{{fix_description}}\n"
    "\n"
    "Create a clean git diff patch containing only the source file changes for the fix. Do not include test files, reproduction scripts, or configuration changes.\n"
    "\n"
    "Return:\n"
    "```\n"
    "PATCH FILE: <path to patch>\n"
    "PATCH VALID: <true|false>\n"
    "```\n"
)

NODE9_INSTR = (
    "Submit your verified patch using this EXACT command:\n"
    "```bash\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt\n"
    "```\n"
    "\n"
    "CRITICAL: You CANNOT continue working after submission.\n"
)

NODE10_INSTR = (
    "The fix could not be fully verified within the retry budget. Submit the best available patch as a best-effort attempt.\n"
    "\n"
    "```bash\n"
    "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt\n"
    "```\n"
    "\n"
    "CRITICAL: You CANNOT continue working after submission.\n"
)


def build() -> "t.WorkflowIR":
    nodes = [
        # Node 0: step "explore_codebase"
        t.NodeIR(
            id=0, name="explore_codebase", step_type="step",
            reads=[TV("problem_statement", predicates=[])],
            writes=[TV("codebase_analysis", predicates=[])],
            instruction=NODE0_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("problem_statement", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("codebase_analysis", "isNonEmptyString"),
                t.InfoContentIR("codebase_analysis", "project_description"),
                t.InfoContentIR("codebase_analysis", "issue_summary"),
                t.InfoContentIR("codebase_analysis", "relevant_files"),
                t.InfoContentIR("codebase_analysis", "root_cause_hypothesis"),
            ],
            step_tag=t.StepTagIR(kind="exploratory"),
            sub_goal_contributions=[t.SubGoalTagIR("codebase_explored")],
        ),
        # Node 1: step "reproduce_issue"
        t.NodeIR(
            id=1, name="reproduce_issue", step_type="step",
            reads=[TV("codebase_analysis", predicates=[])],
            writes=[TV("reproduction_result", predicates=[])],
            instruction=NODE1_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("codebase_analysis", "isNonEmptyString"),
                t.InfoContentIR("codebase_analysis", "relevant_files"),
            ],
            postcond_extra=[
                VP("reproduction_result", "isNonEmptyString"),
                t.InfoContentIR("reproduction_result", "reproduction_status"),
                t.InfoContentIR("reproduction_result", "reproduction_script"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("issue_reproduced")],
        ),
        # Node 2: step "localize_root_cause"
        t.NodeIR(
            id=2, name="localize_root_cause", step_type="step",
            reads=[TV("codebase_analysis", predicates=[]),
                   TV("reproduction_result", predicates=[])],
            writes=[TV("root_cause_analysis", predicates=[])],
            instruction=NODE2_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("codebase_analysis", "isNonEmptyString"),
                t.InfoContentIR("codebase_analysis", "relevant_files"),
                VP("reproduction_result", "isNonEmptyString"),
                t.InfoContentIR("reproduction_result", "reproduction_status"),
            ],
            postcond_extra=[
                VP("root_cause_analysis", "isNonEmptyString"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "specific_locations"),
            ],
            step_tag=t.StepTagIR(kind="comprehensive"),
            sub_goal_contributions=[t.SubGoalTagIR("root_cause_identified")],
        ),
        # Node 3: whileLoop "fix_loop"
        t.NodeIR(
            id=3, name="fix_loop", step_type="whileLoop",
            reads=[TV("fix_attempt", base_type="TInt", predicates=[]),
                   TV("max_fix_attempts", base_type="TInt", predicates=[])],
            writes=[], instruction=None,
            precond_extra=[
                VP("fix_attempt", "isInt"),
                VP("max_fix_attempts", "isInt"),
            ],
            loop_invariant=[
                VP("fix_attempt", "isInt"),
                VP("max_fix_attempts", "isInt"),
                VP("root_cause_analysis", "isNonEmptyString"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "specific_locations"),
                VP("codebase_analysis", "isNonEmptyString"),
                VP("reproduction_result", "isNonEmptyString"),
                VP("retry_notes", "isNonEmptyString"),
                VP("fix_verified", "nameExists"),
            ],
            termination_kind="finiteCondition",
            termination_vars=["fix_attempt", "max_fix_attempts"],
            exit_postcond=[
                VP("fix_description", "isNonEmptyString"),
                t.InfoContentIR("fix_description", "modified_files"),
                VP("verification_result", "isNonEmptyString"),
                t.InfoContentIR("verification_result", "verification_status"),
                VP("fix_verified", "isNonEmptyString"),
                VP("fix_verified", "containsSubstring", substring="true"),
            ],
            loop_executes_at_least_once=True,
        ),
        # Node 4: step "implement_fix"
        t.NodeIR(
            id=4, name="implement_fix", step_type="step",
            reads=[TV("root_cause_analysis", predicates=[]),
                   TV("retry_notes", predicates=[]),
                   TV("codebase_analysis", predicates=[]),
                   TV("reproduction_result", predicates=[])],
            writes=[TV("fix_description", predicates=[])],
            instruction=NODE4_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("root_cause_analysis", "isNonEmptyString"),
                t.InfoContentIR("root_cause_analysis", "files_to_modify"),
                t.InfoContentIR("root_cause_analysis", "specific_locations"),
                VP("retry_notes", "nameExists"),
                VP("codebase_analysis", "isNonEmptyString"),
                VP("reproduction_result", "isNonEmptyString"),
            ],
            postcond_extra=[
                VP("fix_description", "isNonEmptyString"),
                t.InfoContentIR("fix_description", "modified_files"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_implemented")],
        ),
        # Node 5: step "verify_fix"
        t.NodeIR(
            id=5, name="verify_fix", step_type="step",
            reads=[TV("fix_description", predicates=[])],
            writes=[TV("verification_result", predicates=[])],
            instruction=NODE5_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_description", "isNonEmptyString"),
                t.InfoContentIR("fix_description", "modified_files"),
            ],
            postcond_extra=[
                VP("verification_result", "isNonEmptyString"),
                t.InfoContentIR("verification_result", "verification_status"),
            ],
            step_tag=t.StepTagIR(kind="verificatory"),
            sub_goal_contributions=[t.SubGoalTagIR("fix_verified")],
            sub_goal_verifications=[t.SubGoalTagIR("fix_implemented")],
        ),
        # Node 6: step "check_verification"
        t.NodeIR(
            id=6, name="check_verification", step_type="step",
            reads=[TV("verification_result", predicates=[])],
            writes=[TV("fix_verified", predicates=[])],
            instruction=NODE6_INSTR,
            precond_extra=[
                VP("verification_result", "isNonEmptyString"),
                t.InfoContentIR("verification_result", "verification_status"),
            ],
            postcond_extra=[VP("fix_verified", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="incremental"),
        ),
        # Node 7: conditional "check_result"
        t.NodeIR(
            id=7, name="check_result", step_type="conditional",
            reads=[TV("fix_verified", predicates=[])],
            writes=[], instruction=None,
            precond_extra=[VP("fix_verified", "nameExists")],
            postcond_extra=[VP("fix_description", "isNonEmptyString")],
            then_target_id=8, else_target_id=10,
            then_postcond=[
                VP("fix_verified", "isNonEmptyString"),
                VP("fix_verified", "containsSubstring", substring="true"),
            ],
            else_postcond=[VP("fix_verified", "isNonEmptyString")],
        ),
        # Node 8: step "create_patch"
        t.NodeIR(
            id=8, name="create_patch", step_type="step",
            reads=[TV("fix_description", predicates=[])],
            writes=[TV("patch_status", predicates=[])],
            instruction=NODE8_INSTR,
            precond_extra=[
                VP("shell_run", "toolExists"),
                VP("fix_description", "isNonEmptyString"),
            ],
            postcond_extra=[VP("patch_status", "isNonEmptyString")],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_created")],
        ),
        # Node 9: step "submit_patch"
        t.NodeIR(
            id=9, name="submit_patch", step_type="step",
            reads=[], writes=[TV("submission_result", predicates=[])],
            instruction=NODE9_INSTR,
            precond_extra=[VP("shell_run", "toolExists")],
            postcond_extra=[
                VP("submission_result", "isNonEmptyString"),
                VP("submission_result", "containsSubstring",
                   substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[t.SubGoalTagIR("patch_submitted")],
        ),
        # Node 10: step "submit_best_effort" (fail-safe branch)
        t.NodeIR(
            id=10, name="submit_best_effort", step_type="step",
            reads=[], writes=[TV("submission_result", predicates=[])],
            instruction=NODE10_INSTR,
            precond_extra=[VP("shell_run", "toolExists")],
            postcond_extra=[
                VP("submission_result", "isNonEmptyString"),
                VP("submission_result", "containsSubstring",
                   substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
            ],
            step_tag=t.StepTagIR(kind="transformative"),
            sub_goal_contributions=[
                t.SubGoalTagIR("patch_created"),
                t.SubGoalTagIR("patch_submitted"),
            ],
        ),
    ]

    parameters = [
        TV("code_path", "TString", predicates=[P("isValidFilePath")]),
        TV("problem_statement", "TString", predicates=[P("isNonEmptyString")]),
        TV("regression_test_cmd", "TString", predicates=[P("isNonEmptyString")]),
        TV("fix_attempt", "TInt", predicates=[P("isInt")]),
        TV("max_fix_attempts", "TInt", predicates=[P("isInt")]),
        TV("retry_notes", "TString", predicates=[P("isNonEmptyString")]),
        TV("fix_verified", "TString", predicates=[]),
    ]

    # Explicit param_postcond: irregular ordering (first 5 params get nameExists +
    # predicates, retry_notes goes directly to its predicate, fix_verified only
    # gets nameExists). Hand-match the original Lean file's paramNode.
    param_postcond = [
        VP("code_path", "nameExists"),
        VP("problem_statement", "nameExists"),
        VP("regression_test_cmd", "nameExists"),
        VP("fix_attempt", "nameExists"),
        VP("max_fix_attempts", "nameExists"),
        VP("code_path", "isValidFilePath"),
        VP("problem_statement", "isNonEmptyString"),
        VP("regression_test_cmd", "isNonEmptyString"),
        VP("fix_attempt", "isInt"),
        VP("max_fix_attempts", "isInt"),
        VP("shell_run", "toolExists"),
        VP("retry_notes", "isNonEmptyString"),
        VP("fix_verified", "nameExists"),
    ]

    edges = [
        t.EdgeIR("seq", from_node=0, to_node=1),
        t.EdgeIR("seq", from_node=1, to_node=2),
        t.EdgeIR("seq", from_node=2, to_node=3),
        t.EdgeIR("loop", header=3, body_entry=4, exit_node=7),
        t.EdgeIR("seq", from_node=4, to_node=5),
        t.EdgeIR("seq", from_node=5, to_node=6),
        t.EdgeIR("loopBack", from_node=6, to_node=3),
        t.EdgeIR("branch", cond_node=7, then_entry=8, else_entry=10),
        t.EdgeIR("seq", from_node=8, to_node=9),
    ]

    goal_spec = t.GoalSpecificationIR(
        original_goal=(
            "Given a GitHub issue, reproduce the bug, locate the root cause, "
            "implement a fix, verify it, and submit a patch"
        ),
        sub_goals=[
            SubGoal("codebase_explored", "codebase_analysis",
                    P("isNonEmptyString"),
                    "Evidence that the repository structure and issue-relevant source areas have been explored and understood.",
                    [GPK("pathCoverage")]),
            SubGoal("issue_reproduced", "reproduction_result",
                    P("isNonEmptyString"),
                    "Evidence that the reported bug has been reproduced with a concrete script or procedure.",
                    [GPK("pathCoverage")]),
            SubGoal("root_cause_identified", "root_cause_analysis",
                    P("isNonEmptyString"),
                    "Evidence that the root cause of the bug has been pinpointed to specific files and code locations.",
                    [GPK("pathCoverage")]),
            SubGoal("fix_implemented", "fix_description",
                    P("isNonEmptyString"),
                    "Evidence that a source-code fix addressing the root cause has been implemented.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack"),
                     GPK("verificationCoverage"), GPK("failSafe")]),
            SubGoal("fix_verified", "verification_result",
                    P("isNonEmptyString"),
                    "Evidence that the implemented fix was verified by re-running reproduction and targeted tests.",
                    [GPK("pathCoverage"), GPK("unifiedLoopBack")]),
            SubGoal("patch_created", "patch_status",
                    P("isNonEmptyString"),
                    "Evidence that a clean git patch containing only the fix changes was created.",
                    [GPK("pathCoverage")]),
            SubGoal("patch_submitted", "submission_result",
                    P("containsSubstring", substring="COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"),
                    "Evidence that the final patch was submitted as the workflow output.",
                    [GPK("pathCoverage")]),
        ],
    )

    ir = t.WorkflowIR(
        name="passed_workflow_3_v2",
        goal=(
            "Given a GitHub issue, reproduce the bug, locate the root cause, "
            "implement a fix, verify it, and submit a patch."
        ),
        parameters=parameters, nodes=nodes, edges=edges,
        entry=0, exits=[9, 10],
        param_postcond=param_postcond,
        goal_spec=goal_spec,
    )
    return ir


if __name__ == "__main__":
    save(build(), "passed_workflow_3_layer2_v2")
