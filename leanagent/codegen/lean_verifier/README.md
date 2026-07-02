# Lean Verification Generator (Recursive)

Automatically generates complete Lean4 verification code (Layer 1 + Layer 2) for a YAML agent plan **and all its submodules**, recursively, bottom-up.

## Key Feature: Recursive Submodule Handling

```
Main Plan
 ├─ call: module_A.yaml
 │    └─ call: module_X.yaml    ← leaf (processed first)
 ├─ parallel: module_B.yaml
 │    ├─ call: module_X.yaml    ← deduplicated, same as above
 │    └─ call: module_Y.yaml    ← leaf
 └─ call: module_C.yaml         ← leaf

Processing order (topo sort):
  1. module_X  (leaf, no children)
  2. module_Y  (leaf)
  3. module_C  (leaf)
  4. module_A  (has child X → already verified)
  5. module_B  (has children X, Y → already verified)
  6. Main Plan (has children A, B, C → all verified)
```

Each module's Layer 2 can reference its children's verified `SemanticWorkflowGraph` via `SubmoduleNode` / `makeParallelSubmoduleNode`.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                       HOST                            │
│                                                       │
│  1. stage_for_docker.sh                               │
│     • Recursively discovers ALL submodule YAMLs       │
│     • Copies everything into workspace/_verifier_*/   │
│                                                       │
│  2. run_agent.sh                                      │
│     • Runs agent on HOST (python -m agent.run)        │
│     • Agent sends MCP tool calls to Docker            │
│                                                       │
│  workspace/                                           │
│  ├── _verifier_staging/                               │
│  │   ├── TaskPlanToLean.py                            │
│  │   ├── yaml_parser.py                               │
│  │   ├── target_plan.yaml → plans/root.yaml           │
│  │   ├── plans/            ← ALL discovered YAMLs     │
│  │   │   ├── root.yaml                                │
│  │   │   └── modules/                                 │
│  │   │       ├── sub_a.yaml                           │
│  │   │       └── sub_b.yaml                           │
│  │   └── examples/         ← reference Lean files     │
│  └── outputs/lean_verifier/                           │
│      ├── Verification_root.lean       ← main output   │
│      ├── verified_registry.json       ← all specs     │
│      └── modules/                                     │
│          ├── Verification_sub_a.lean                   │
│          └── Verification_sub_b.lean                   │
├─────────────── Docker mount ──────────────────────────┤
│  /workspace/ ← same files, mounted via -v             │
└──────────────────────────────────────────────────────┘
```

## Usage

### Step 1: Stage files

```bash
cd Lean4Agent   # the repo root

# Stage a plan with submodules (recursively discovers all sub-YAMLs)
bash leanagent/codegen/lean_verifier/stage_for_docker.sh \
  AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
```

> NOTE: substitute any workflow YAML above; submodules are discovered recursively.

### Step 2: Run the agent

```bash
bash scripts/run_agent.sh leanagent/codegen/lean_verifier/generate_lean_verification.yaml
```

### Step 3: With pre-verified modules

If some submodules were already formalized (e.g., in a previous run):

```bash
# Stage
bash leanagent/codegen/lean_verifier/stage_for_docker.sh \
  task_plans/deep_research_with_module/deep_research_main.yaml \
  '[{"module_name":"web_search","lean_path":"/workspace/outputs/lean_verifier/modules/Verification_web_search.lean","prefix":"web_search","semantic_graph_name":"web_searchSemanticGraph","soundness_theorem_name":"web_search_semantically_sound"}]'

# Run (the pre-verified modules are skipped, their specs are used by parents)
ALREADY_VERIFIED_MODULES='[{"module_name":"web_search",...}]' \
  bash scripts/run_agent.sh leanagent/codegen/lean_verifier/generate_lean_verification.yaml
```

### Step 4: Retrieve & compile

```bash
# Copy generated files to Verifier
cp workspace/outputs/lean_verifier/Verification_*.lean \
   FormalAgentLib/TestVerifications/
cp workspace/outputs/lean_verifier/modules/Verification_*.lean \
   FormalAgentLib/TestVerifications/modules/

# Compile
cd Verifier && lake build
```

## Plan Phases

| Phase | Name | Description |
|-------|------|-------------|
| 0 | Setup | `pip install pyyaml`, validate staging, init registry |
| 1 | Examples | Read 4 reference Lean files (once, shared by all modules) |
| 2 | Discovery | Recursively find ALL submodules, deduplicate, topo-sort |
| 3 | Process | `for_each` module (leaves → root): Layer 1 + Layer 2 + accumulate |
| 4 | Validate | Check all files, generate summary |

### Phase 3 Detail (per module)

| Step | Name | Description |
|------|------|-------------|
| A | extract_module_info | Parse current module descriptor |
| B | generate_layer1 | YAML → JSON → Layer 1 Lean (Python) |
| C | collect_children_specs | Find verified children from registry |
| D | generate_layer2 | Generate COMPLETE Layer 2 code (LLM) |
| E | assemble_lean_file | Combine Layer 1 + Layer 2, write file |
| F | create_verified_spec | Save module spec to registry |

## Configuration

The generator reads the following environment variables (set them in your shell or a
sourced `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `YAML_PLAN_PATH` | `.../target_plan.yaml` | Root YAML plan path (Docker) |
| `ALREADY_VERIFIED_MODULES` | `[]` | JSON array of pre-verified specs |
| `OUTPUT_DIR` | `/workspace/outputs/lean_verifier` | Output directory |
| `STAGING_DIR` | `/workspace/_verifier_staging` | Staging directory |

## Verified Module Spec Format

```json
{
  "module_name": "extract_single_citation",
  "lean_path": "/workspace/outputs/lean_verifier/modules/Verification_extract_single_citation.lean",
  "prefix": "extract_single_citation",
  "semantic_graph_name": "extract_single_citationSemanticGraph",
  "soundness_theorem_name": "extract_single_citation_semantically_sound",
  "num_nodes": 7
}
```

This spec is what parents use to generate `SubmoduleNode` references and `PredicateRegistry` entries.
