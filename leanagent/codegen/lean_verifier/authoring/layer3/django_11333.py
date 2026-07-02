"""Author IR JSON for passed_workflow_1_django_11333_per_step.lean."""

from _common import (
    t, load_passed_workflow_1_v2_workflow, save,
    STANDARD_STEP_ID_MAP, STANDARD_DYN_NODES,
)


REPORT_PATH = (
    ""
    "benchmark_results/SWE_bench_verified_50problems_subset/GPT-5.2/"
    "logs/run_evaluation/passed_workflow_1/gpt-5.2/django__django-11333/report.json"
)
EVENT_LOG_PATH = (
    ""
    "outputs/gpt-5.2/SWE_bench_verified_50problems_subset/"
    "passed_workflow_1/django__django-11333_agent_events.log"
)


EXEC_STATE = [
    ("problem_statement",
     "get_resolver() caching bug: None vs ROOT_URLCONF produce separate lru_cache entries"),
    ("code_path", "/testbed"),
    ("regression_test_cmd",
     "./tests/runtests.py --settings=test_sqlite --parallel 1 urlpatterns.test_resolvers"),
    ("shell_run", "<tool>"),
    ("repository_understanding",
     "navigated to django/urls/resolvers.py; identified get_resolver() lru_cache key "
     "duplication when urlconf=None"),
    ("reproduction_evidence",
     "confirmed that calling get_resolver(None) and get_resolver(settings.ROOT_URLCONF) "
     "produce different cached objects"),
    ("fix_implementation_evidence",
     "introduced _get_cached_resolver with lru_cache; refactored get_resolver to resolve "
     "None to ROOT_URLCONF before calling the cached helper"),
    ("fix_verification_evidence",
     "ran urlpatterns.test_resolvers tests; all pass including "
     "test_resolver_cache_default__root_urlconf"),
    ("patch_submission_evidence",
     "unified diff against django/urls/resolvers.py emitted and applied cleanly"),
]


LLM_INJECTIONS = [
    t.LLMInjectionIR(
        step_name="explore_repository", var_name="repository_understanding",
        holds=True, confidence=0.85,
        llm_explanation=(
            "Upstream default applies. Agent navigated to django/urls/resolvers.py and produced a "
            "targeted edit to get_resolver() and a new _get_cached_resolver() helper. "
            "report.json confirms patch_exists=true and patch_successfully_applied=true, so "
            "repository exploration was sufficient to locate the relevant caching code. "
            "test_output.txt shows all 3 tests pass — no evidence of inadequate exploration."
        ),
    ),
    t.LLMInjectionIR(
        step_name="reproduce_issue", var_name="reproduction_evidence",
        holds=True, confidence=0.80,
        llm_explanation=(
            "Upstream default applies. The agent proceeded through all 5 steps and the resulting "
            "fix correctly addresses the get_resolver() cache-key duplication bug (None vs "
            "ROOT_URLCONF producing separate lru_cache entries). test_output.txt confirms "
            "test_resolver_cache_default__root_urlconf passes, consistent with the agent having "
            "understood and reproduced the caching discrepancy described in the issue."
        ),
    ),
    t.LLMInjectionIR(
        step_name="fix_issue", var_name="fix_implementation_evidence",
        holds=True, confidence=0.95,
        llm_explanation=(
            "Fix is confirmed correct by downstream test execution. test_output.txt shows "
            "test_resolver_cache_default__root_urlconf (urlpatterns.test_resolvers.ResolverCacheTests) "
            "... ok — this is the sole FAIL_TO_PASS test and it now passes. The two PASS_TO_PASS "
            "tests (test_str for RegexPatternTests and RoutePatternTests) also pass. report.json "
            "records 0 FAIL_TO_PASS failures and 0 PASS_TO_PASS regressions. Ran 3 tests in "
            "0.002s with result OK. resolved=true."
        ),
    ),
    t.LLMInjectionIR(
        step_name="verify_fix", var_name="fix_verification_evidence",
        holds=True, confidence=0.90,
        llm_explanation=(
            "Verification is confirmed by the evaluation harness. test_output.txt shows the test "
            "runner executed ./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 "
            "urlpatterns.test_resolvers and all 3 tests passed including the critical "
            "test_resolver_cache_default__root_urlconf. report.json shows 0 failures across all "
            "categories (FAIL_TO_PASS, PASS_TO_PASS, FAIL_TO_FAIL, PASS_TO_FAIL). The agent's "
            "verification step correctly identified the fix as working."
        ),
    ),
    t.LLMInjectionIR(
        step_name="create_patch", var_name="patch_submission_evidence",
        holds=True, confidence=0.98,
        llm_explanation=(
            "Patch creation succeeded. report.json records patch_is_None=false, patch_exists=true, "
            "patch_successfully_applied=true. The saved .diff is a well-formed unified diff "
            "against django/urls/resolvers.py that introduces _get_cached_resolver with "
            "lru_cache and refactors get_resolver to resolve None before caching. "
            "test_output.txt confirms the patch applied cleanly and all tests pass with OK status."
        ),
    ),
]


def build() -> "t.Layer3IR":
    return t.Layer3IR(
        workflow=load_passed_workflow_1_v2_workflow(),
        prefix="passed_workflow_1_v2",
        suffix="_11333",
        report_path=REPORT_PATH,
        event_log_path=EVENT_LOG_PATH,
        step_id_map=STANDARD_STEP_ID_MAP,
        exec_state=EXEC_STATE,
        dyn_nodes=STANDARD_DYN_NODES,
        llm_injections=LLM_INJECTIONS,
        banner_title="PER-STEP PER-PREDICATE MOVE ANALYSIS — django__django-11333",
        banner_subtitle="Layer 3 discharging Layer 2's verification artifact  [RESOLVED]",
    )


if __name__ == "__main__":
    save(build(), "passed_workflow_1_django_11333_per_step")
