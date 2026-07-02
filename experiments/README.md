# experiments

Reproduction of the paper's experiments. See the top-level [`../README.md`](../README.md)
for the full Quickstart (dependencies, credentials, and end-to-end commands).

| Directory | Role |
|---|---|
| `SWE_bench_verified/` | SWE-Bench-Verified (hard subset) main runs + Layer-2/3 plan YAMLs + judge prompts |
| `elaipbench/` | ELAIP-Bench main runs + Layer-2 plans |
| `SWE_bench_LeanEvolve/`, `elaip_LeanEvolve/` | **LeanEvolve** — verification-guided workflow revision (each also bundles the LLM-evolve baseline arm) |

Each benchmark is driven by its `run.py`; see the per-directory READMEs for flags.
Datasets (`data/`) and `.env` secrets are **not** committed — download/configure separately.
Runners depend on the `AgentSPEX` package being installed (`pip install -e AgentSPEX` from
the repo root, per the top-level Quickstart).
