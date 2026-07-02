"""SWE_bench_LeanEvolve — joint LeanEvolve -> LLMEvolve correction cascade.

Merged entry point that orchestrates both workflow-evolution arms over a set of
previously-failed SWE-bench instances and reports how many additional problems
pass once. A thin wrapper: it shells out to the two in-package arm packages
(``PureLean`` and ``PureLLMAddsOn``) and the SWE-bench harness,
then merges their per-instance ``resolved`` verdicts. See ``run.py``.
"""
