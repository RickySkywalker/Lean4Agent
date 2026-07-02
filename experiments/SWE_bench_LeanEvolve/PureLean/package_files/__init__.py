"""Self-contained helper package for the SWE-Bench Lean-guided plan-evolution
pipeline (experiments/SWE_bench_LeanEvolve/PureLean/run.py).

Mirrors experiments/elaip_LeanEvolve/package_files/. Every module here is a
relocated COPY of the corresponding helper from
leanagent/codegen/agent_evolve/ (plus yaml_runner.py copied from
experiments/elaip_LeanEvolve/package_files/), so the experiment directory
runs without importing leanagent/codegen/agent_evolve at runtime.

Stage A (annotate) helpers : trace_segmenter, eval_forensics, layer3_ir_init,
                             ir_to_lean, EditJson, summarize_ir,
                             tighten_layer3_verdicts.
Stage B (evolve)  helpers  : lean_report_loader, plan_validator,
                             classify_failure, inject_verify_directives,
                             EditYaml, EditJson, failure_pattern_templates.json.
Shared                     : staging_paths, yaml_runner (run_yaml_agent).
"""
