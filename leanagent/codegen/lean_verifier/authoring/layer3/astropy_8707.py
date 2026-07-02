"""Author IR JSON for passed_workflow_1_per_step_move_analysis_generated.lean.

Instance: astropy__astropy-8707. Uses unsuffixed def names (reportPath,
eventLogPath, stepIdMap, execState, dynamicGraph, llmInjections).
"""

from _common import (
    t, load_passed_workflow_1_v2_workflow, save,
    STANDARD_STEP_ID_MAP, STANDARD_DYN_NODES,
)


REPORT_PATH = (
    ""
    "benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/"
    "logs/run_evaluation/passed_workflow_1/gpt-5.2/astropy__astropy-8707/report.json"
)
EVENT_LOG_PATH = (
    ""
    "outputs/gpt-5.2/SWE_bench_verified_50problems_subset/"
    "passed_workflow_1/astropy__astropy-8707_agent_events.log"
)


EXEC_STATE = [
    ("problem_statement", "Header.fromstring / Card.fromstring raise TypeError on bytes"),
    ("code_path", "/testbed"),
    ("regression_test_cmd", "pytest -rA"),
    ("shell_run", "<tool>"),
    ("repository_understanding",
     "explored astropy/io/fits/header.py and card.py; identified decode_ascii as candidate"),
    ("reproduction_evidence",
     "reproduced TypeError on Header.fromstring(<bytes>)"),
    ("fix_implementation_evidence",
     "patched Card/Header.fromstring with decode_ascii branch"),
    ("fix_verification_evidence",
     "ran narrow pytest -k fromstring filter; agent declared verification successful"),
    ("patch_submission_evidence",
     "diff against astropy/io/fits/header.py and card.py emitted"),
]


LLM_INJECTIONS = [
    t.LLMInjectionIR(
        step_name="explore_repository", var_name="repository_understanding",
        holds=True, confidence=0.85,
        llm_explanation=(
            "Agent localized the bug to Card.fromstring and Header.fromstring in "
            "astropy/io/fits/{card,header}.py; test_output.txt shows every failure "
            "is at the test fixture setup layer ('is using nose-specific method: "
            "setup(self)'), not at a wrong-file fix path, so there is no runtime "
            "evidence that the explored files were misidentified."
        ),
    ),
    t.LLMInjectionIR(
        step_name="reproduce_issue", var_name="reproduction_evidence",
        holds=True, confidence=0.85,
        llm_explanation=(
            "Agent's reproduce_issue.py exhibited Header.fromstring(bytes) and "
            "Card.fromstring(bytes) raising TypeError on the pre-patch source and "
            "then printed 'SUCCESS: parsed header from bytes; SIMPLE= True NAXIS= 0' "
            "after restoring the patch; nothing in test_output.txt contradicts this "
            "reproduction signature."
        ),
    ),
    t.LLMInjectionIR(
        step_name="fix_issue", var_name="fix_implementation_evidence",
        holds=False, confidence=0.9,
        llm_explanation=(
            "test_output.txt places the FAIL_TO_PASS target in tests_status."
            "FAIL_TO_PASS.failure with signature 'pytest.PytestRemovedIn8Warning: "
            "...astropy/io/fits/tests/test_header.py::TestHeaderFunctions::"
            "test_card_from_bytes is using nose-specific method: setup(self)', "
            "so the fixture errors before ever calling the patched fromstring; the "
            "final tally '4 passed, 148 errors in 33.30s' and report.json "
            "resolved=false confirm the fix is not validated by downstream tests."
        ),
    ),
    t.LLMInjectionIR(
        step_name="verify_fix", var_name="fix_verification_evidence",
        holds=False, confidence=0.95,
        llm_explanation=(
            "The agent's verification command 'pytest -q -rA astropy/io/fits/tests/"
            "test_header.py -k fromstring' returned '2 passed, 148 deselected' — "
            "the -k filter matches only names containing 'fromstring' and therefore "
            "deselects the FAIL_TO_PASS target test_card_from_bytes (substring "
            "'from_bytes'). The subsequent 'pytest -rA' aborted at collection with "
            "'AttributeError: module numpy has no attribute int', so the 148 setup "
            "errors that test_output.txt later surfaced were never observed by the "
            "agent; verification did not exercise the failing test."
        ),
    ),
    t.LLMInjectionIR(
        step_name="create_patch", var_name="patch_submission_evidence",
        holds=True, confidence=0.95,
        llm_explanation=(
            "report.json records patch_exists=true and patch_successfully_applied=true, "
            "and the .diff file is a well-formed unified diff modifying only "
            "astropy/io/fits/card.py and astropy/io/fits/header.py with valid hunks; "
            "the patch-submission deliverable is an applicable diff, which holds "
            "independent of whether the tests validate the change."
        ),
    ),
]


def build() -> "t.Layer3IR":
    return t.Layer3IR(
        workflow=load_passed_workflow_1_v2_workflow(),
        prefix="passed_workflow_1_v2",
        suffix="",
        report_path=REPORT_PATH,
        event_log_path=EVENT_LOG_PATH,
        step_id_map=STANDARD_STEP_ID_MAP,
        exec_state=EXEC_STATE,
        dyn_nodes=STANDARD_DYN_NODES,
        llm_injections=LLM_INJECTIONS,
        banner_title="PER-STEP PER-PREDICATE MOVE ANALYSIS — astropy__astropy-8707",
        banner_subtitle="Layer 3 discharging Layer 2's verification artifact",
    )


if __name__ == "__main__":
    save(build(), "passed_workflow_1_per_step_move_analysis_generated")
