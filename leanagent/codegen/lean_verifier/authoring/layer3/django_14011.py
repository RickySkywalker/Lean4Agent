"""Author IR JSON for passed_workflow_1_django_14011_per_step.lean."""

from _common import (
    t, load_passed_workflow_1_v2_workflow, save,
    STANDARD_STEP_ID_MAP, STANDARD_DYN_NODES,
)


REPORT_PATH = (
    ""
    "benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/"
    "logs/run_evaluation/passed_workflow_1/gpt-5.2/django__django-14011/report.json"
)
EVENT_LOG_PATH = (
    ""
    "outputs/gpt-5.2/SWE_bench_verified_50problems_subset/"
    "passed_workflow_1/django__django-14011_agent_events.log"
)


EXEC_STATE = [
    ("problem_statement",
     "LiveServerTestCase leaks database connections; request handlers must close "
     "connections after each request"),
    ("code_path", "/testbed"),
    ("regression_test_cmd",
     "./tests/runtests.py --settings=test_sqlite --parallel 1 servers.tests"),
    ("shell_run", "<tool>"),
    ("repository_understanding",
     "located django/core/servers/basehttp.py and django/test/testcases.py; "
     "identified WSGIRequestHandler / ThreadedWSGIServer as the request-handling surface"),
    ("reproduction_evidence",
     "observed database connection leak pattern in LiveServerTestCase runs"),
    ("fix_implementation_evidence",
     "added close_db_connections_on_request_end flag on ThreadedWSGIServer plus "
     "connections.close_all() in WSGIRequestHandler.handle_one_request finally block"),
    ("fix_verification_evidence",
     "agent ran tests and declared verification successful; accepted the fix and "
     "proceeded to patch"),
    ("patch_submission_evidence",
     "45-line unified diff against django/core/servers/basehttp.py emitted; "
     "applies cleanly"),
]


LLM_INJECTIONS = [
    t.LLMInjectionIR(
        step_name="explore_repository", var_name="repository_understanding",
        holds=True, confidence=0.8,
        llm_explanation=(
            "Exploration evidence is accepted by default: the agent proceeded through all 5 steps "
            "and produced a targeted edit localized to django/core/servers/basehttp.py "
            "(ThreadedWSGIServer and WSGIRequestHandler.handle_one_request), which matches the "
            "module implicated by the issue. report.json shows patch_exists=true and "
            "patch_successfully_applied=true, so repository navigation was adequate to locate the "
            "relevant files even though the eventual fix was semantically incorrect."
        ),
    ),
    t.LLMInjectionIR(
        step_name="reproduce_issue", var_name="reproduction_evidence",
        holds=True, confidence=0.7,
        llm_explanation=(
            "No runtime evidence contradicts reproduction: the step ran and downstream steps "
            "(fix_issue, verify_fix, create_patch) all executed, and the agent emitted a concrete "
            "patch touching ThreadedWSGIServer — consistent with having observed the "
            "LiveServerTestCase / connection-leak symptom described in the issue. Upstream default "
            "applies because test_output.txt and report.json do not show evidence of inadequate "
            "reproduction output."
        ),
    ),
    t.LLMInjectionIR(
        step_name="fix_issue", var_name="fix_implementation_evidence",
        holds=False, confidence=0.95,
        llm_explanation=(
            "The fix is semantically off-target. The agent added "
            "`close_db_connections_on_request_end = True` on ThreadedWSGIServer and a "
            "`connections.close_all()` finally-block in WSGIRequestHandler, but did NOT extend "
            "`ThreadedWSGIServer.__init__` to accept a `connections_override` kwarg. The upstream "
            "FAIL_TO_PASS test harness calls `self.server_class(..., connections_override=...)`, "
            "so every LiveServer setUpClass errors with `TypeError: __init__() got an unexpected "
            "keyword argument 'connections_override'` at "
            "django/core/servers/basehttp.py line 71. test_output.txt ends with "
            "`FAILED (errors=6)` and report.json lists 17 FAIL_TO_PASS failures including "
            "test_view, test_404, test_media_files, test_environ, "
            "test_keep_alive_connection_clears_previous_request_data, and "
            "test_live_server_url_is_class_property; resolved=false."
        ),
    ),
    t.LLMInjectionIR(
        step_name="verify_fix", var_name="fix_verification_evidence",
        holds=False, confidence=0.85,
        llm_explanation=(
            "The agent's verification did not exercise the actual FAIL_TO_PASS tests. If it had "
            "run the LiveServer test classes with the upstream-authored test modifications, it "
            "would have immediately hit `TypeError: __init__() got an unexpected keyword argument "
            "'connections_override'` raised from basehttp.py line 71 during setUpClass for "
            "LiveServerAddress, LiveServerDatabase, LiveServerPort, LiveServerThreadedTests, "
            "LiveServerTestCloseConnectionTest, and LiveServerViews. Instead verification passed "
            "and the agent advanced to create_patch, so the failing tests were never meaningfully "
            "exercised — 17 FAIL_TO_PASS tests fail at evaluation time."
        ),
    ),
    t.LLMInjectionIR(
        step_name="create_patch", var_name="patch_submission_evidence",
        holds=True, confidence=0.98,
        llm_explanation=(
            "Patch creation succeeded as a mechanical artifact. report.json records "
            "`patch_is_None: false, patch_exists: true, patch_successfully_applied: true`. The "
            "saved .diff is a well-formed 45-line unified diff against "
            "django/core/servers/basehttp.py that applies cleanly in the evaluation harness "
            "(test_output.txt shows `Applied patch django/test/testcases.py cleanly.` and the "
            "agent's own diff is cleanly committed before tests run). Correctness of the patch "
            "content is judged by fix_issue, not here."
        ),
    ),
]


def build() -> "t.Layer3IR":
    return t.Layer3IR(
        workflow=load_passed_workflow_1_v2_workflow(),
        prefix="passed_workflow_1_v2",
        suffix="_14011",
        report_path=REPORT_PATH,
        event_log_path=EVENT_LOG_PATH,
        step_id_map=STANDARD_STEP_ID_MAP,
        exec_state=EXEC_STATE,
        dyn_nodes=STANDARD_DYN_NODES,
        llm_injections=LLM_INJECTIONS,
        banner_title="PER-STEP PER-PREDICATE MOVE ANALYSIS — django__django-14011",
        banner_subtitle="Layer 3 discharging Layer 2's verification artifact",
    )


if __name__ == "__main__":
    save(build(), "passed_workflow_1_django_14011_per_step")
