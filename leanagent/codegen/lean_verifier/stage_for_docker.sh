#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# stage_for_docker.sh
# ─────────────────────────────────────────────────────────────────────
# Recursively discovers and stages all files needed for Lean
# verification generation into workspace/_verifier_staging/.
#
# Usage:
#   bash leanagent/codegen/lean_verifier/stage_for_docker.sh <target_yaml_plan> [already_verified_json]
#
# Examples:
#   # Simple plan (no submodules)
#   bash leanagent/codegen/lean_verifier/stage_for_docker.sh AgentSPEX/workflows/quickstart.yaml
#
#   # Plan with submodules
#   bash leanagent/codegen/lean_verifier/stage_for_docker.sh \
#     AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
#
#   # With pre-verified modules
#   bash leanagent/codegen/lean_verifier/stage_for_docker.sh \
#     AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml \
#     '[{"module_name":"web_search","lean_path":"/workspace/...","prefix":"web_search","semantic_graph_name":"web_searchSemanticGraph","soundness_theorem_name":"web_search_semantically_sound"}]'
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="${PROJECT_ROOT}/workspace"
STAGING="${WORKSPACE}/_verifier_staging"
EXAMPLES="${STAGING}/examples"

# ── Validate arguments ──────────────────────────────────────────────
TARGET_YAML="${1:-}"
ALREADY_VERIFIED="${2:-[]}"

if [[ -z "$TARGET_YAML" ]]; then
    echo "Usage: $0 <target_yaml_plan_path> [already_verified_json]"
    echo ""
    echo "  target_yaml_plan_path   Path to root YAML plan (abs or relative to project root)"
    echo "  already_verified_json   Optional JSON array of pre-verified module specs"
    exit 1
fi

# Resolve to absolute path
if [[ ! "$TARGET_YAML" = /* ]]; then
    TARGET_YAML="${PROJECT_ROOT}/${TARGET_YAML}"
fi

if [[ ! -f "$TARGET_YAML" ]]; then
    echo "ERROR: Target YAML plan not found: $TARGET_YAML"
    exit 1
fi

# ── Clean & create staging directory ────────────────────────────────
echo "=== Staging files for Docker ==="
echo "Project root:  $PROJECT_ROOT"
echo "Target YAML:   $TARGET_YAML"
echo ""

rm -rf "$STAGING"
mkdir -p "$STAGING/examples"

# ── 1. Copy Python tools ───────────────────────────────────────────
SRC_TASKPLAN="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/TaskPlanToLean.py"
SRC_PARSER="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/yaml_parser.py"
SRC_EXPLORE="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/explore_submodule.py"
SRC_EDITJSON="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/EditJson.py"

for f in "$SRC_TASKPLAN" "$SRC_PARSER" "$SRC_EXPLORE" "$SRC_EDITJSON"; do
    if [[ -f "$f" ]]; then
        cp "$f" "$STAGING/"
        echo "✓ Copied $(basename "$f")"
    else
        echo "✗ ERROR: $(basename "$f") not found at: $f"
        exit 1
    fi
done

# ── 1b. Copy predicate documentation ───────────────────────────────
PRED_DOCS_DIR="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/predicate_docs"
if [[ -d "$PRED_DOCS_DIR" ]]; then
    cp -r "$PRED_DOCS_DIR" "$STAGING/predicate_docs"
    echo "✓ Copied predicate_docs/ directory ($(ls "$PRED_DOCS_DIR" | wc -l | tr -d ' ') files)"
else
    echo "⚠ WARNING: predicate_docs/ directory not found at: $PRED_DOCS_DIR"
fi

# ── 2. Copy reference Lean examples ────────────────────────────────
VERIF_DIR="${PROJECT_ROOT}/FormalAgentLib/TestVerifications"
AI_SCI_DIR="${VERIF_DIR}/Verification_ai_scientists"
WRITER_DIR="${AI_SCI_DIR}/writer/modules"
SEM_DIR="${PROJECT_ROOT}/FormalAgentLib/AgentVerifier/StaticSemanticLayer"

# Copy reference Lean examples (bash 3.2 compatible, no associative arrays)
LEAN_NAMES=(
    "Verification_extract_single_citation.lean"
    "Verification_extract_citation.lean"
    "SWE_bench_verification.lean"
)
LEAN_SRCS=(
    "${AI_SCI_DIR}/Verification_extract_single_citation.lean"
    "${WRITER_DIR}/Verification_extract_citation.lean"
    "${VERIF_DIR}/SWE_bench_verification.lean"
)

for i in "${!LEAN_NAMES[@]}"; do
    name="${LEAN_NAMES[$i]}"
    src="${LEAN_SRCS[$i]}"
    if [[ -f "$src" ]]; then
        cp "$src" "$EXAMPLES/$name"
        echo "✓ Copied $name"
    else
        echo "⚠ WARNING: $name not found at: $src"
    fi
done

# Extract predicate helpers from StaticSemanticVariables.lean
PRED_SRC="${SEM_DIR}/StaticSemanticVariables.lean"
if [[ -f "$PRED_SRC" ]]; then
    sed -n '390,470p' "$PRED_SRC" > "$EXAMPLES/StaticSemanticVariables_predicates.lean"
    echo "✓ Extracted predicates (lines 390-470)"
else
    echo "⚠ WARNING: StaticSemanticVariables.lean not found"
fi

# ── 3. Recursively copy target YAML and all submodule YAMLs ────────
echo ""
echo "--- Discovering YAML module tree ---"

# Use explore_submodule.py for recursive discovery (home-dir = project root)
DISCOVER_JSON=$(python3 "$SRC_EXPLORE" \
    --yaml_plan_path "$TARGET_YAML" \
    --home-dir "$PROJECT_ROOT" \
    --json)

# Copy each discovered YAML into staging at project-relative paths
python3 - "$DISCOVER_JSON" "$TARGET_YAML" "$PROJECT_ROOT" "$STAGING" <<'PYEOF'
import json, os, sys, shutil

discover_json = sys.argv[1]
root_yaml     = sys.argv[2]
project_root  = sys.argv[3]
staging       = sys.argv[4]

modules = json.loads(discover_json)
count = 0
env_copied = 0
env_created = 0

for mod in modules:
    yaml_path = mod["yaml_path"]
    # Resolve to absolute if needed
    if not os.path.isabs(yaml_path):
        yaml_path = os.path.normpath(os.path.join(project_root, yaml_path))
    else:
        yaml_path = os.path.normpath(yaml_path)

    if not os.path.exists(yaml_path):
        print(f"  ⚠ MISSING: {yaml_path}", file=sys.stderr)
        continue

    # ── Copy at project-root-relative path inside staging ──
    # e.g. AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
    #    → staging/AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
    try:
        proj_rel = os.path.relpath(yaml_path, project_root)
    except ValueError:
        proj_rel = os.path.basename(yaml_path)
    if proj_rel.startswith('..'):
        proj_rel = os.path.basename(yaml_path)

    dest = os.path.join(staging, proj_rel)
    if os.path.normpath(dest) != os.path.normpath(yaml_path):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(yaml_path, dest)
    print(f"  ✓ {proj_rel}")
    count += 1

    # ── Ensure companion .env exists in staging for every YAML ──
    env_path = os.path.splitext(yaml_path)[0] + ".env"
    env_rel = os.path.splitext(proj_rel)[0] + ".env"
    env_dest = os.path.join(staging, env_rel)
    os.makedirs(os.path.dirname(env_dest), exist_ok=True)

    if os.path.isfile(env_path):
        if os.path.normpath(env_dest) != os.path.normpath(env_path):
            shutil.copy2(env_path, env_dest)
        print(f"  ✓ {env_rel}  (companion .env)")
        env_copied += 1
    else:
        # Some verifier steps require --env_file to exist; create placeholder to avoid hard failure.
        with open(env_dest, "w", encoding="utf-8") as f:
            f.write("# Auto-generated placeholder by stage_for_docker.sh\n")
        print(f"  ⚠ {env_rel}  missing in source; created empty placeholder")
        env_created += 1

print(f"\nTotal YAML files staged: {count}")
print(f"Companion .env copied: {env_copied}")
print(f"Placeholder .env created: {env_created}")
PYEOF

echo ""

# ── 4. Compute project-relative path for Docker ────────────────────
# Inside Docker, staging is at /workspace/_verifier_staging/.
# YAML plans are mirrored at their project-root-relative paths, e.g.
#   AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
#   → /workspace/_verifier_staging/AgentSPEX/workflows/deep_research_with_module/deep_research_main.yaml
PROJ_REL=$(python3 -c "import os; print(os.path.relpath('$TARGET_YAML', '$PROJECT_ROOT'))")
echo "✓ Project-relative path: ${PROJ_REL}"

# ── 5. Create output directories ───────────────────────────────────
mkdir -p "${WORKSPACE}/outputs/lean_verifier/modules"
echo "✓ Created output directories"

# ── Summary ─────────────────────────────────────────────────────────
echo ""
echo "=== Staging Complete ==="
echo ""
echo "Staged in: $STAGING"
echo ""
echo "├── TaskPlanToLean.py"
echo "├── yaml_parser.py"
echo "├── explore_submodule.py"
echo "├── ${PROJ_REL}   ←  root plan (project-relative)"
echo "├── (submodule YAMLs at project-relative paths)"
echo "├── predicate_docs/    ←  predicate system documentation"
echo "│   ├── index.md       ←  compact index (for LLM context)"
echo "│   ├── ir_json_format.md"
echo "│   ├── predicates_basic.md"
echo "│   ├── predicates_path_url.md"
echo "│   ├── predicates_content.md"
echo "│   ├── predicates_tool_module.md"
echo "│   ├── predicates_json_schema.md"
echo "│   ├── predicates_semantic.md"
echo "│   ├── predicates_advanced.md"
echo "│   └── node_types.md"
echo "└── examples/          ←  reference Lean files"
echo ""
echo "=== Docker paths ==="
echo "  Root plan:   /workspace/_verifier_staging/${PROJ_REL}"
echo "  Staging:     /workspace/_verifier_staging/"
echo "  Output:      /workspace/outputs/lean_verifier/"
echo ""
# ── 6. Write YAML_PLAN_PATH into the .env file so run_agent.sh picks it up ──
DOCKER_ROOT="/workspace/_verifier_staging/${PROJ_REL}"
ENV_FILE="${PROJECT_ROOT}/leanagent/codegen/lean_verifier/generate_lean_verification.env"
if [[ -f "$ENV_FILE" ]]; then
    # Update the YAML_PLAN_PATH= line in-place
    sed -i '' "s|^YAML_PLAN_PATH=.*|YAML_PLAN_PATH=${DOCKER_ROOT}|" "$ENV_FILE" 2>/dev/null \
      || sed -i "s|^YAML_PLAN_PATH=.*|YAML_PLAN_PATH=${DOCKER_ROOT}|" "$ENV_FILE"
    echo "✓ Updated .env: YAML_PLAN_PATH=${DOCKER_ROOT}"
else
    echo "⚠ .env file not found: ${ENV_FILE}"
fi
echo ""
echo "=== Run the agent ==="
echo ""
echo "  bash scripts/run_agent.sh leanagent/codegen/lean_verifier/generate_lean_verification.yaml"
echo ""
echo "  (YAML_PLAN_PATH is auto-set in generate_lean_verification.env)"
if [[ "$ALREADY_VERIFIED" != "[]" ]]; then
    echo "  To pass already-verified modules, override on command line:"
    echo "  ALREADY_VERIFIED_MODULES='${ALREADY_VERIFIED}' \\"
    echo "  bash scripts/run_agent.sh leanagent/codegen/lean_verifier/generate_lean_verification.yaml"
fi
echo ""
