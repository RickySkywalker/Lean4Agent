#!/bin/bash

# Generate visualizations for all YAML plans
# This script creates both Mermaid (modern) and Graphviz (traditional) visualizations

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
WORKFLOWS_DIR="$PROJECT_ROOT/workflows"
OUTPUT_DIR="$PROJECT_ROOT/outputs/visualizations"

# Add src to PYTHONPATH
export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH}"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Generating YAML Plan Visualizations"
echo "=========================================="
echo ""

# Count YAML files
yaml_count=$(find "$WORKFLOWS_DIR" -maxdepth 1 -name "*.yaml" -type f | wc -l)
echo "Found $yaml_count YAML files to visualize"
echo ""

# Process each YAML file
counter=0
for yaml_file in "$WORKFLOWS_DIR"/*.yaml; do
    # Skip if no files found
    [ -e "$yaml_file" ] || continue

    counter=$((counter + 1))
    filename=$(basename "$yaml_file" .yaml)

    echo "[$counter/$yaml_count] Processing: $filename"

    # Generate Mermaid HTML (best for viewing)
    echo "  → Generating Mermaid HTML..."
    python3 -m agent.yaml_visualizer_mermaid \
        "$yaml_file" \
        -o "$OUTPUT_DIR/$filename" \
        -f html 2>/dev/null

    # Generate Mermaid text (for embedding)
    # echo "  → Generating Mermaid text..."
    # python3 -m agent.yaml_visualizer_mermaid \
    #     "$yaml_file" \
    #     -o "$OUTPUT_DIR/$filename" \
    #     -f mmd 2>/dev/null

    # echo "  ✓ Done"
    # echo ""
done

echo "=========================================="
echo "Visualization Summary"
echo "=========================================="
echo ""
echo "Generated files in: $OUTPUT_DIR"
echo ""
echo "HTML files (open in browser):"
ls -1 "$OUTPUT_DIR"/*.html 2>/dev/null | while read file; do
    echo "  - $(basename "$file")"
done
echo ""
echo "Mermaid files (embed in docs):"
ls -1 "$OUTPUT_DIR"/*.mmd 2>/dev/null | while read file; do
    echo "  - $(basename "$file")"
done
echo ""
echo "To view:"
echo "  1. Open HTML files in browser:"
echo "     open $OUTPUT_DIR/<filename>.html"
echo ""
echo "  2. View Mermaid online:"
echo "     https://mermaid.live"
echo ""
echo "  3. Use in Markdown:"
echo "     \`\`\`mermaid"
echo "     [paste content from .mmd file]"
echo "     \`\`\`"
echo ""
echo "Done!"
