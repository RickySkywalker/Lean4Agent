# leanagent

The Python pipeline around [`FormalAgentLib`](../FormalAgentLib/).

- **`lean_query/`** — Lean⇄Python bridge: builds a driver, runs `lake`, and parses the
  layer-1/2/3 JSON (`runner.py`, `driver_gen.py`, `schema.py`, `cli.py`, `discovery.py`).
- **`codegen/`** — workflow YAML → IR → Lean spec:
  - `lean_verifier/` — Layer-1/2 codegen (`TaskPlanToLean*.py`, `yaml_parser.py`, `layer3_v2_codegen.py`).
  - `agent_evolve/` — Layer-3 IR + evolve generators (`ir_to_lean.py`, `run_agent_evolve.py`, …).
- **`tools/`** — utilities operating on the Lean text (IR builders, migration helpers).
