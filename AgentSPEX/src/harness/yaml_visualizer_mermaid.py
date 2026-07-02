"""
YAML Plan Visualizer - Mermaid Edition
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class YAMLPlanVisualizerMermaid:
    """Visualize YAML workflows as flowcharts using Mermaid.js"""

    def __init__(self):
        self.node_counter = 0
        self.mermaid_lines = []
        self.node_classes = {}
        self.node_full_text = {}  # Map node_id to full text for interactive display

        # Style definitions (using callStep instead of call which is a reserved word)
        self.style_definitions = {
            "step": "fill:#E3F2FD,stroke:#1976D2,stroke-width:2px",
            "loop": "fill:#F3E5F5,stroke:#7B1FA2,stroke-width:2px",
            "condition": "fill:#FFE0B2,stroke:#E64A19,stroke-width:2px",
            "parallel": "fill:#C8E6C9,stroke:#388E3C,stroke-width:2px",
            "callStep": "fill:#B3E5FC,stroke:#0277BD,stroke-width:2px",
            "operation": "fill:#DCEDC8,stroke:#558B2F,stroke-width:2px",
        }

    def visualize_yaml(
        self, yaml_file: str, output_file: Optional[str] = None, format: str = "mmd"
    ) -> str:
        """Generate a flowchart visualization from a YAML workflow using Mermaid."""
        # Load YAML file
        with open(yaml_file, "r", encoding="utf-8") as f:
            content = f.read()
            content = self._expand_env_variables(content)
            task_data = yaml.safe_load(content)

        # Determine output file path
        if output_file is None:
            yaml_path = Path(yaml_file)
            output_file = str(yaml_path.with_suffix(""))

        # Generate Mermaid diagram
        self._reset()
        self._generate_mermaid(task_data)

        # Determine output extension
        if format == "mmd":
            output_path = f"{output_file}.mmd"
            self._write_mermaid_file(output_path)
        elif format == "html":
            output_path = f"{output_file}.html"
            self._write_html_file(output_path, task_data.get("name", "Task"))
        elif format in ["svg", "png"]:
            mmd_path = f"{output_file}.mmd"
            self._write_mermaid_file(mmd_path)
            output_path = f"{output_file}.{format}"
            self._render_with_mmdc(mmd_path, output_path, format)
        else:
            raise ValueError(f"Unsupported format: {format}")

        return output_path

    def _reset(self):
        """Reset the visualizer state"""
        self.node_counter = 0
        self.mermaid_lines = []
        self.node_classes = {}
        self.node_full_text = {}

    def _expand_env_variables(self, content: str) -> str:
        """Expand environment variables in YAML content"""

        def replace_var(match):
            var_expr = match.group(1)
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.getenv(var_name, default_value)
            else:
                return os.getenv(var_expr, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replace_var, content)

    def _generate_mermaid(self, task_data: Dict[str, Any]):
        """Generate the complete Mermaid diagram"""
        task_name = task_data.get("name", "Task")
        task_goal = task_data.get("goal", "")

        # Start flowchart
        self.mermaid_lines.append("flowchart TB")
        self.mermaid_lines.append("")

        # Add title/start node - simplified format
        full_title = task_name
        title = task_name
        if task_goal:
            full_title = f"{task_name} - {task_goal}"
            goal_short = self._truncate_text(task_goal, 80)
            title = f"{task_name} - {goal_short}"

        # Save full text if truncated (Start node)
        self._save_full_text_if_truncated("Start", full_title, title)

        self.mermaid_lines.append(f'    Start(["{self._clean_text(title)}"])')
        self.mermaid_lines.append("")

        # Process workflow
        workflow = task_data.get("workflow", [])
        if workflow:
            last_node = self._process_workflow(workflow, "Start")
            self.mermaid_lines.append(f"    End([End])")
            self.mermaid_lines.append(f"    {last_node} --> End")
            self.mermaid_lines.append("")

        # Add class assignments (using 'class' syntax, not ':::')
        for node_id, style_name in sorted(self.node_classes.items()):
            self.mermaid_lines.append(f"    class {node_id} {style_name}")
        self.mermaid_lines.append("")

        # Add class definitions
        self.mermaid_lines.append("    %% Class definitions")
        for style_name, style_def in self.style_definitions.items():
            self.mermaid_lines.append(f"    classDef {style_name} {style_def};")

    def _process_workflow(self, workflow: List[Dict[str, Any]], prev_node: str) -> str:
        """Process a workflow and return the last node ID"""
        current_node = prev_node
        for step in workflow:
            current_node = self._process_step(step, current_node)
        return current_node

    def _process_workflow_no_connect(self, workflow: List[Dict[str, Any]]) -> str:
        """Process a workflow without connecting from a previous node. Returns the first node ID."""
        if not workflow:
            return None

        # Process first step with a dummy marker
        first_node = self._process_step_no_auto_connect(workflow[0])

        # Process remaining steps normally, chaining from previous
        current_node = first_node
        for step in workflow[1:]:
            current_node = self._process_step(step, current_node)

        return first_node

    def _process_step(self, step: Dict[str, Any], prev_node: str) -> str:
        """Process a single step and return its node ID"""
        step_type = list(step.keys())[0]
        step_data = step[step_type]

        if step_type == "step":
            return self._add_basic_step(step_data, prev_node)
        elif step_type == "for_each":
            return self._add_for_each_step(step_data, prev_node)
        elif step_type == "if":
            return self._add_if_step(step_data, prev_node)
        elif step_type == "while":
            return self._add_while_step(step_data, prev_node)
        elif step_type == "switch":
            return self._add_switch_step(step_data, prev_node)
        elif step_type == "parallel":
            return self._add_parallel_step(step_data, prev_node)
        elif step_type == "gather":
            return self._add_gather_step(step_data, prev_node)
        elif step_type == "call":
            return self._add_call_step(step_data, prev_node)
        elif step_type == "increment":
            return self._add_increment_step(step_data, prev_node)
        elif step_type == "set_variable":
            return self._add_set_variable_step(step_data, prev_node)
        else:
            return self._add_generic_step(step_type, step_data, prev_node)

    def _process_step_no_auto_connect(self, step: Dict[str, Any]) -> str:
        """Process a single step without auto-connecting from previous node. Only declares the node."""
        step_type = list(step.keys())[0]
        step_data = step[step_type]

        if step_type == "step":
            return self._add_basic_step_no_connect(step_data)
        elif step_type == "call":
            return self._add_call_step_no_connect(step_data)
        # For other types, we can use a dummy prev_node and skip the connection
        # But for simplicity, just handle the common cases
        else:
            # Fallback: use empty string as prev and it won't render a connection
            return self._process_step(step, "")

    def _save_full_text_if_truncated(
        self, node_id: str, full_label: str, display_label: str
    ):
        """Save full text only if it differs from display label (i.e., was truncated)"""
        # Clean both for comparison
        full_clean = " ".join(full_label.split())
        display_clean = " ".join(display_label.split())
        if full_clean != display_clean:
            self.node_full_text[node_id] = full_label

    def _add_basic_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a basic step node - simplified format without HTML"""
        node_id = self._get_next_node_id()
        name = step_data.get("name", "Step")
        instruction = step_data.get("instruction", "")
        save_as = step_data.get("save_as", "")

        # Build full text
        full_label = name
        if instruction:
            full_label += f" - {instruction}"
        if save_as:
            full_label += f" -> {save_as}"

        # Simplified label: name - instruction (truncated)
        instruction_short = self._truncate_text(instruction, 50)
        label = name
        if instruction_short:
            label += f" - {instruction_short}"
        if save_as:
            label += f" -> {save_as}"

        # Only save full text if truncated
        self._save_full_text_if_truncated(node_id, full_label, label)

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "step"
        return node_id

    def _add_basic_step_no_connect(self, step_data: Dict[str, Any]) -> str:
        """Add a basic step node without auto-connecting from previous node"""
        node_id = self._get_next_node_id()
        name = step_data.get("name", "Step")
        instruction = step_data.get("instruction", "")
        save_as = step_data.get("save_as", "")

        # Build full text
        full_label = name
        if instruction:
            full_label += f" - {instruction}"
        if save_as:
            full_label += f" -> {save_as}"

        # Simplified label: name - instruction (truncated)
        instruction_short = self._truncate_text(instruction, 50)
        label = name
        if instruction_short:
            label += f" - {instruction_short}"
        if save_as:
            label += f" -> {save_as}"

        # Only save full text if truncated
        self._save_full_text_if_truncated(node_id, full_label, label)

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        # No connection line added here
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "step"
        return node_id

    def _add_for_each_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a for_each loop node"""
        node_id = self._get_next_node_id()
        variable = step_data.get("variable", "item")
        source = step_data.get("in", "items")
        max_iterations = step_data.get("max_iterations", "")

        label = f"For Each {variable} in {source}"
        if max_iterations:
            label += f" (max: {max_iterations})"

        # Rectangle shape for loops (more compatible)
        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "loop"

        # Process loop body
        steps = step_data.get("steps", [])
        if steps:
            body_end = self._process_workflow(steps, node_id)
            self.mermaid_lines.append(f"    {body_end} -.->|next| {node_id}")

        # Exit node
        exit_node = self._get_next_node_id()
        self.mermaid_lines.append(f'    {exit_node}["Continue"]')
        self.mermaid_lines.append(f"    {node_id} -->|done| {exit_node}")
        self.mermaid_lines.append("")
        self.node_classes[exit_node] = "loop"
        return exit_node

    def _add_if_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add an if-else conditional node"""
        node_id = self._get_next_node_id()
        condition = step_data.get("condition", "condition")
        condition_short = self._truncate_text(condition, 40)

        full_label = f"If: {condition}"
        label = f"If: {condition_short}"
        self._save_full_text_if_truncated(node_id, full_label, label)

        # Rectangle for conditionals (more compatible)
        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "condition"

        # Merge node
        merge_node = self._get_next_node_id()
        self.mermaid_lines.append(f'    {merge_node}((" "))')
        self.mermaid_lines.append("")

        # Process then branch
        then_steps = step_data.get("then", [])
        if then_steps:
            # Use a dummy node to prevent automatic connection
            then_end = self._process_workflow_no_connect(then_steps)
            self.mermaid_lines.append(f"    {node_id} -->|true| {then_end}")
            self.mermaid_lines.append(f"    {then_end} --> {merge_node}")
        else:
            self.mermaid_lines.append(f"    {node_id} -->|true| {merge_node}")

        # Process else branch
        else_steps = step_data.get("else", [])
        if else_steps:
            else_end = self._process_workflow_no_connect(else_steps)
            self.mermaid_lines.append(f"    {node_id} -->|false| {else_end}")
            self.mermaid_lines.append(f"    {else_end} --> {merge_node}")
        else:
            self.mermaid_lines.append(f"    {node_id} -->|false| {merge_node}")

        self.mermaid_lines.append("")
        return merge_node

    def _add_while_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a while loop node"""
        node_id = self._get_next_node_id()
        condition = step_data.get("condition", "condition")
        max_iterations = step_data.get("max_iterations", "")
        condition_short = self._truncate_text(condition, 40)

        full_label = f"While: {condition}"
        if max_iterations:
            full_label += f" (max: {max_iterations})"

        label = f"While: {condition_short}"
        if max_iterations:
            label += f" (max: {max_iterations})"

        self._save_full_text_if_truncated(node_id, full_label, label)

        # Rectangle for loops (more compatible)
        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "loop"

        # Process loop body
        steps = step_data.get("steps", [])
        if steps:
            body_end = self._process_workflow(steps, node_id)
            self.mermaid_lines.append(f"    {body_end} -.->|continue| {node_id}")

        # Exit node
        exit_node = self._get_next_node_id()
        self.mermaid_lines.append(f'    {exit_node}["Continue"]')
        self.mermaid_lines.append(f"    {node_id} -->|exit| {exit_node}")
        self.mermaid_lines.append("")
        self.node_classes[exit_node] = "loop"
        return exit_node

    def _add_switch_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a switch statement node"""
        node_id = self._get_next_node_id()
        variable = step_data.get("variable", "value")

        # Rectangle for switch (more compatible)
        self.mermaid_lines.append(
            f'    {node_id}["Switch: {self._clean_text(variable)}"]'
        )
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "condition"

        # Merge node
        merge_node = self._get_next_node_id()
        self.mermaid_lines.append(f'    {merge_node}((" "))')
        self.mermaid_lines.append("")

        # Process cases
        cases = step_data.get("cases", {})
        for case_value, case_steps in cases.items():
            case_label = self._clean_text(str(case_value)[:20])
            if case_steps:
                case_end = self._process_workflow_no_connect(case_steps)
                self.mermaid_lines.append(f"    {node_id} -->|{case_label}| {case_end}")
                self.mermaid_lines.append(f"    {case_end} --> {merge_node}")
            else:
                self.mermaid_lines.append(
                    f"    {node_id} -->|{case_label}| {merge_node}"
                )

        # Default case
        default_steps = step_data.get("default", [])
        if default_steps:
            default_end = self._process_workflow_no_connect(default_steps)
            self.mermaid_lines.append(f"    {node_id} -->|default| {default_end}")
            self.mermaid_lines.append(f"    {default_end} --> {merge_node}")
        else:
            self.mermaid_lines.append(f"    {node_id} -->|default| {merge_node}")

        self.mermaid_lines.append("")
        return merge_node

    def _add_parallel_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a parallel execution node"""
        node_id = self._get_next_node_id()
        module = step_data.get("module", "")
        max_workers = step_data.get("max_workers", "")

        module_name = Path(module).stem if module else "Module"
        label = f"PARALLEL: {module_name}"
        if max_workers:
            label += f" (workers: {max_workers})"

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "parallel"
        return node_id

    def _add_gather_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a gather (parallel calls) node"""
        node_id = self._get_next_node_id()
        calls = step_data.get("calls", [])
        max_workers = step_data.get("max_workers", "")

        label = f"GATHER: {len(calls)} parallel calls"
        if max_workers:
            label += f" (workers: {max_workers})"

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "parallel"

        # Merge node
        merge_node = self._get_next_node_id()
        self.mermaid_lines.append(f'    {merge_node}["Wait All"]')
        self.mermaid_lines.append("")
        self.node_classes[merge_node] = "parallel"

        # Add individual calls
        for i, call in enumerate(calls):
            call_node = self._get_next_node_id()
            module = call.get("module", f"call_{i+1}")
            module_short = Path(module).stem if module else f"call_{i+1}"
            save_as = call.get("save_as", "")

            call_label = f"Call {module_short}"
            if save_as:
                call_label += f" -> {save_as}"

            self.mermaid_lines.append(
                f'    {call_node}["{self._clean_text(call_label)}"]'
            )
            self.mermaid_lines.append(f"    {node_id} --> {call_node}")
            self.mermaid_lines.append(f"    {call_node} --> {merge_node}")
            self.mermaid_lines.append("")
            self.node_classes[call_node] = "callStep"

        return merge_node

    def _add_call_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a module call node"""
        node_id = self._get_next_node_id()
        module = step_data.get("module", "Module")
        save_as = step_data.get("save_as", "")

        module_short = Path(module).stem if module else "Module"
        label = f"Call {module_short}"
        if save_as:
            label += f" -> {save_as}"

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = (
            "callStep"  # Using callStep instead of call (reserved word)
        )
        return node_id

    def _add_call_step_no_connect(self, step_data: Dict[str, Any]) -> str:
        """Add a module call node without auto-connecting"""
        node_id = self._get_next_node_id()
        module = step_data.get("module", "Module")
        save_as = step_data.get("save_as", "")

        module_short = Path(module).stem if module else "Module"
        label = f"Call {module_short}"
        if save_as:
            label += f" -> {save_as}"

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        # No connection line
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "callStep"
        return node_id

    def _add_increment_step(self, step_data: str, prev_node: str) -> str:
        """Add an increment step node"""
        node_id = self._get_next_node_id()
        variable = (
            step_data
            if isinstance(step_data, str)
            else step_data.get("variable", "var")
        )

        label = f"Increment {variable}"
        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "operation"
        return node_id

    def _add_set_variable_step(self, step_data: Dict[str, Any], prev_node: str) -> str:
        """Add a set_variable step node"""
        node_id = self._get_next_node_id()
        name = step_data.get("name", "variable")
        value = step_data.get("value", "")

        full_label = f"Set {name} = {value}"
        value_short = self._truncate_text(str(value), 30)
        label = f"Set {name} = {value_short}"

        self._save_full_text_if_truncated(node_id, full_label, label)

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "operation"
        return node_id

    def _add_generic_step(self, step_type: str, step_data: Any, prev_node: str) -> str:
        """Add a generic step node for unknown types"""
        node_id = self._get_next_node_id()
        data_str = str(step_data)
        full_label = f"{step_type}: {data_str}"
        label = f"{step_type}: {self._truncate_text(data_str, 40)}"

        self._save_full_text_if_truncated(node_id, full_label, label)

        self.mermaid_lines.append(f'    {node_id}["{self._clean_text(label)}"]')
        self.mermaid_lines.append(f"    {prev_node} --> {node_id}")
        self.mermaid_lines.append("")
        self.node_classes[node_id] = "step"
        return node_id

    def _get_next_node_id(self) -> str:
        """Generate next node ID"""
        node_id = f"N{self.node_counter}"
        self.node_counter += 1
        return node_id

    def _clean_text(self, text: str) -> str:
        """Clean text for Mermaid (remove problematic chars, NO HTML escaping here)"""
        if not isinstance(text, str):
            text = str(text)
        # Remove extra whitespace
        text = " ".join(text.split())
        # Escape quotes
        text = text.replace('"', "'")
        # Remove/escape curly braces that might conflict with Mermaid syntax
        text = text.replace("{", "(")
        text = text.replace("}", ")")
        # Note: Do NOT escape HTML entities here - that's done in _write_html_file
        return text

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to maximum length"""
        if not isinstance(text, str):
            text = str(text)
        text = " ".join(text.split())
        if len(text) > max_length:
            return text[: max_length - 3] + "..."
        return text

    def _write_mermaid_file(self, output_path: str):
        """Write Mermaid diagram to file"""
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.mermaid_lines))

        print(f"✓ Generated Mermaid file: {output_path}")

    def _write_html_file(self, output_path: str, title: str):
        """Write standalone HTML file with embedded Mermaid"""
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Escape HTML entities for embedding in HTML (must do & first!)
        def escape_html(text):
            text = text.replace("&", "&amp;")
            text = text.replace("<", "&lt;")
            text = text.replace(">", "&gt;")
            return text

        # Escape each line for HTML embedding
        escaped_lines = [escape_html(line) for line in self.mermaid_lines]

        mermaid_content = "\n".join(escaped_lines)
        # Indent for HTML
        indented_content = "\n".join("            " + line for line in escaped_lines)

        # Prepare node full text mapping as JSON
        import json

        node_full_text_json = json.dumps(self.node_full_text)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Workflow Visualization</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            flowchart: {{
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis'
            }}
        }});

        // Wait for Mermaid to render, then add click handlers
        window.addEventListener('load', function() {{
            setTimeout(addClickHandlers, 500);
        }});
    </script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            margin-top: 0;
        }}
        .mermaid {{
            text-align: center;
            margin-top: 30px;
        }}
        /* Only expandable nodes have pointer cursor - set via JS */
        .node.expandable rect,
        .node.expandable polygon,
        .node.expandable circle {{
            cursor: pointer;
        }}
        .node.expandable:hover rect,
        .node.expandable:hover polygon {{
            filter: brightness(0.95);
        }}
        .node.expanded rect,
        .node.expanded polygon {{
            stroke: #E65100 !important;
            stroke-width: 3px !important;
        }}
        
        /* Tooltip styles */
        .node-tooltip {{
            position: fixed;
            background: #333;
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
            max-width: 500px;
            word-wrap: break-word;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 1000;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s ease;
            --arrow-left: 50%;
        }}
        .node-tooltip.visible {{
            opacity: 1;
        }}
        /* Arrow pointing up (tooltip below node) */
        .node-tooltip.arrow-top::before {{
            content: '';
            position: absolute;
            top: -8px;
            left: var(--arrow-left);
            transform: translateX(-50%);
            border-width: 0 8px 8px 8px;
            border-style: solid;
            border-color: transparent transparent #333 transparent;
        }}
        /* Arrow pointing down (tooltip above node) */
        .node-tooltip.arrow-bottom::after {{
            content: '';
            position: absolute;
            bottom: -8px;
            left: var(--arrow-left);
            transform: translateX(-50%);
            border-width: 8px 8px 0 8px;
            border-style: solid;
            border-color: #333 transparent transparent transparent;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="mermaid">
{indented_content}
        </div>
    </div>
    <div id="nodeTooltip" class="node-tooltip"></div>

    <script>
        // Node full text data
        const nodeFullText = {node_full_text_json};

        // Track expanded nodes
        const expandedNodes = new Set();

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function addClickHandlers() {{
            const svg = document.querySelector('.mermaid svg');
            if (!svg) {{
                console.log('SVG not found, retrying...');
                setTimeout(addClickHandlers, 500);
                return;
            }}

            console.log('Adding click handlers...');

            // Find all node groups - try multiple selectors
            const nodes = svg.querySelectorAll('g.node, g[class*="node"], g[id*="flowchart"]');
            console.log('Found nodes:', nodes.length);

            nodes.forEach(node => {{
                const nodeId = node.id;
                console.log('Processing node:', nodeId);

                // Try multiple methods to extract node ID
                let actualNodeId = null;

                // Method 1: Remove 'flowchart-' prefix and get first part
                if (nodeId.includes('flowchart-')) {{
                    actualNodeId = nodeId.replace('flowchart-', '').split('-')[0];
                }}
                // Method 2: Direct match
                else if (nodeFullText[nodeId]) {{
                    actualNodeId = nodeId;
                }}
                // Method 3: Try to find in the ID
                else {{
                    for (let key in nodeFullText) {{
                        if (nodeId.includes(key)) {{
                            actualNodeId = key;
                            break;
                        }}
                    }}
                }}

                console.log('Extracted ID:', actualNodeId);

                if (actualNodeId && nodeFullText[actualNodeId]) {{
                    console.log('Setting up click for:', actualNodeId);

                    // Mark node as expandable (CSS will set cursor)
                    node.classList.add('expandable');

                    // Add click to the node and all its children
                    const clickHandler = function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        console.log('Clicked node:', actualNodeId);
                        toggleNodeText(node, actualNodeId);
                    }};

                    node.addEventListener('click', clickHandler, true);

                    // Also add click to rect/shape elements for better coverage
                    const shapes = node.querySelectorAll('rect, polygon, circle, ellipse, path');
                    shapes.forEach(shape => {{
                        shape.addEventListener('click', clickHandler, true);
                    }});
                }}
            }});
        }}

        // Current tooltip state
        let currentTooltipNode = null;
        const tooltip = document.getElementById('nodeTooltip');

        function toggleNodeText(nodeElement, nodeId) {{
            const fullText = nodeFullText[nodeId];
            
            // If clicking the same node, hide tooltip
            if (currentTooltipNode === nodeId) {{
                hideTooltip();
                nodeElement.classList.remove('expanded');
                currentTooltipNode = null;
                return;
            }}
            
            // Hide previous tooltip if any
            if (currentTooltipNode) {{
                const prevNode = document.querySelector('.node.expanded');
                if (prevNode) prevNode.classList.remove('expanded');
            }}
            
            // Show tooltip for this node
            nodeElement.classList.add('expanded');
            currentTooltipNode = nodeId;
            
            // Get node position
            const nodeRect = nodeElement.getBoundingClientRect();
            const nodeCenterX = nodeRect.left + (nodeRect.width / 2);
            
            // Position tooltip below the node
            tooltip.textContent = fullText;
            tooltip.className = 'node-tooltip visible';  // Reset classes
            
            // Calculate initial position - center below the node
            let left = nodeCenterX - (tooltip.offsetWidth / 2);
            let top = nodeRect.bottom + 12;
            let showAbove = false;
            
            // Keep tooltip within viewport
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            
            // Horizontal adjustment
            if (left < 10) {{
                left = 10;
            }} else if (left + tooltip.offsetWidth > viewportWidth - 10) {{
                left = viewportWidth - tooltip.offsetWidth - 10;
            }}
            
            // Vertical adjustment - check if need to show above
            if (top + tooltip.offsetHeight > viewportHeight - 10) {{
                top = nodeRect.top - tooltip.offsetHeight - 12;
                showAbove = true;
            }}
            
            // Calculate arrow position relative to tooltip
            const arrowLeft = nodeCenterX - left;
            // Clamp arrow position to stay within tooltip bounds
            const clampedArrowLeft = Math.max(16, Math.min(arrowLeft, tooltip.offsetWidth - 16));
            
            tooltip.style.setProperty('--arrow-left', clampedArrowLeft + 'px');
            tooltip.classList.add(showAbove ? 'arrow-bottom' : 'arrow-top');
            
            tooltip.style.left = left + 'px';
            tooltip.style.top = top + 'px';
        }}
        
        function hideTooltip() {{
            tooltip.className = 'node-tooltip';  // Reset all classes
        }}
        
        // Hide tooltip when clicking outside
        document.addEventListener('click', function(e) {{
            if (!e.target.closest('.node.expandable') && !e.target.closest('.node-tooltip')) {{
                if (currentTooltipNode) {{
                    const prevNode = document.querySelector('.node.expanded');
                    if (prevNode) prevNode.classList.remove('expanded');
                    hideTooltip();
                    currentTooltipNode = null;
                }}
            }}
        }});
        
        // Hide tooltip on scroll
        document.addEventListener('scroll', function() {{
            if (currentTooltipNode) {{
                hideTooltip();
                const prevNode = document.querySelector('.node.expanded');
                if (prevNode) prevNode.classList.remove('expanded');
                currentTooltipNode = null;
            }}
        }}, true);
    </script>
</body>
</html>
"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"✓ Generated HTML file: {output_path}")

    def _render_with_mmdc(self, mmd_path: str, output_path: str, format: str):
        """Render Mermaid to image using mmdc CLI"""
        import subprocess

        try:
            subprocess.run(["mmdc", "-V"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("\nWarning: 'mmdc' command not found.")
            print("Install Mermaid CLI: npm install -g @mermaid-js/mermaid-cli")
            return

        print(f"\nRendering to {format.upper()}...")
        subprocess.run(["mmdc", "-i", mmd_path, "-o", output_path], check=True)
        print(f"✓ Generated: {output_path}")


def main():
    """CLI interface for the Mermaid visualizer"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Visualize YAML workflows as flowcharts using Mermaid.js"
    )
    parser.add_argument("yaml_file", help="Path to the YAML workflow file")
    parser.add_argument(
        "-o", "--output", help="Output file path (without extension)", default=None
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["mmd", "html", "svg", "png"],
        default="html",
        help="Output format (default: html)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.yaml_file):
        print(f"Error: File not found: {args.yaml_file}")
        return 1

    visualizer = YAMLPlanVisualizerMermaid()
    try:
        output_file = visualizer.visualize_yaml(
            args.yaml_file, args.output, args.format
        )
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
