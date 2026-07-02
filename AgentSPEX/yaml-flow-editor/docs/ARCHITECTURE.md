# YAML Flow Editor — Architecture

This document describes the architecture of the yaml-flow-editor: state, data flow, converters, and the run-agent API.

---

## 1. Overview

The editor keeps two representations of the same workflow:

1. **Graph** — React Flow nodes and edges (`FlowNode[]`, `FlowEdge[]`) with positions and node-type-specific `data`.
2. **YAML** — String form of a **workflow** (`name`, `goal`, `config`, `parameters`, `workflow`).

They are kept in sync:

- **YAML → Graph**: `yamlToGraph(yaml)` produces `{ nodes, edges }`; used on load and when the user applies YAML editor changes.
- **Graph → YAML**: `graphToYaml(nodes, edges)` produces a YAML string; used when the user edits the graph (with debounce) and on undo/redo.

The **workflow** in the workflow is a linear list of **workflow steps** (each step is one of `step`, `if`, `while`, `for_each`, `switch`, `gather`, `call`, `input`, `return`, `increment`, `set_variable`, `parallel`). Control-flow steps like `if`/`while`/`for_each`/`switch` contain **nested** step lists. The graph flattens this into a visual DAG with **Start** and **End** nodes and explicit edges.

---

## 2. Directory layout

```
src/
├── App.tsx                 # Root: React Flow, state, YAML sync, run panel, layout
├── main.tsx, index.css
├── components/
│   ├── Sidebar.tsx         # Draggable node list + module list
│   ├── Toolbar.tsx         # Layout, Export, Import, YAML toggle, Undo/Redo, Run
│   ├── NodeConfigPanel.tsx # Right panel: config for selected graph node
│   ├── YamlEditor.tsx      # Monaco YAML editor (bidirectional sync)
│   ├── Resizer.tsx         # Draggable dividers for sidebar/panel width
│   ├── ModuleDetailPanel.tsx      # Selected module template / uploaded module
│   ├── InnerStepConfigPanel.tsx   # Config for a step inside if/while/for_each/switch
│   ├── SubmoduleStepConfigPanel.tsx # Config for a step in a submodule (call target)
│   ├── SubmoduleInlineViewer.tsx   # Inline view of submodule workflow
│   └── nodes/              # React Flow node components
│       ├── index.ts        # nodeTypes map
│       ├── BaseNode.tsx, StepNode.tsx, CallNode.tsx, ...
│       ├── IfContainerNode.tsx, WhileContainerNode.tsx, ForEachContainerNode.tsx, SwitchContainerNode.tsx
│       ├── GatherNode.tsx, ParallelNode.tsx, InputNode.tsx, ReturnNode.tsx
│       └── StartEndNode.tsx
├── contexts/
│   ├── InnerStepContext.tsx        # Selected “inner” step (inside a container)
│   ├── SubmoduleStepContext.tsx    # Selected step in a submodule
│   ├── LayoutContext.tsx           # Layout options
│   ├── LayoutDirectionContext.tsx # TB vs LR
│   └── ModulesContext.tsx          # Uploaded/custom modules
├── converters/
│   ├── yaml-to-graph.ts    # Parse YAML → build nodes + edges
│   └── graph-to-yaml.ts    # Traverse graph from Start → emit workflow steps → YAML
├── hooks/
│   └── useHistory.ts       # Undo/redo (nodes + edges), keyboard shortcuts
├── types/
│   └── index.ts           # Workflow, WorkflowStep, FlowNodeData, NODE_CONFIGS, etc.
└── utils/
    ├── layout.ts           # dagre layout (getLayoutedElements, getNodeDimensions)
    ├── image.ts            # Export canvas as PNG/SVG/PDF (html-to-image, jsPDF)
    ├── flow-utils.ts       # Flow helpers
    ├── moduleYaml.ts       # Read/update module YAML files
    ├── parseModuleYaml.ts  # Parse module YAML, detect “main” plan
    └── workflowStepConverters.ts  # workflowStep ↔ FlowNodeData (used by both converters)
```

---

## 3. State (App.tsx)

- **React Flow state**: `nodes`, `edges` via `useNodesState` / `useEdgesState`.
- **YAML**: `yaml` (string), `yamlError` (parse error if any).
- **UI**: `selectedNode`, `selectedModule`, `showYamlEditor`, `layoutDirection` ('TB' | 'LR'), `sidebarWidth`, `rightPanelWidth`.
- **Run**: `runPanelOpen`, `runId`, `runState`, `runExitCode`, `runLog`, `runOptions`, `dashboardUrl`, `dashboardOpen`, `terminalHeight`.
- **Submodules**: `uploadedModules` (path, content, template); used when exporting/importing and when running (uploaded files are written next to the run plan).
- **Sync guards**: `isUpdatingFromYaml`, `isUpdatingFromGraph` refs to avoid circular updates.
- **History**: `useHistory` stores snapshots of `(nodes, edges)`; undo/redo replace graph state and then regenerate YAML from the restored graph.

Initial YAML is parsed once with `yamlToGraph`; when `layoutDirection` changes, the graph is re-parsed and re-laid out. When the user edits the graph, a debounced effect calls `graphToYaml` and sets `yaml`. When the user edits in the YAML panel and applies, the YAML string is set and a separate effect (or handler) runs `yamlToGraph` and sets nodes/edges (with layout).

---

## 4. Converters

### 4.1 yaml-to-graph (`converters/yaml-to-graph.ts`)

- Parses the YAML string into a **Workflow** (using `js-yaml`).
- Walks `workflow.workflow` and, for each workflow step, creates one or more **FlowNode**s and **FlowEdge**s.
- Uses a **ConversionContext** to assign unique node IDs and track positions (e.g. `NODE_SPACING_Y`).
- **Start** and **End** nodes are created; linear steps become a chain; `if`/`while`/`for_each`/`switch` create container nodes and subgraphs with `thenSteps`/`elseSteps`/`loopSteps`/`cases`/`defaultSteps` stored in node `data`.
- Mapping from workflow step to node data is centralized in **workflowStepConverters** (`workflowStepToFlowNodeData`, `workflowStepsToFlowNodeData`, etc.).

### 4.2 graph-to-yaml (`converters/graph-to-yaml.ts`)

- Builds a **ConversionContext** from current `nodes` and `edges`: maps by node id, outgoing edges per node, incoming edges per node.
- Finds the **Start** node and then follows edges (preferring default “bottom” handle) to do a **topological walk** of the graph.
- For each node, **convertNodeToStep** produces a **WorkflowStep** (or null). Container nodes (if/while/for_each/switch) recursively convert their inner nodes to nested workflow steps.
- Collects the step list and builds a **Workflow** object; serializes to YAML string (via `js-yaml` or equivalent). Workflow `name`/`goal`/`config`/`parameters` are taken from the first node’s stored metadata or from a dedicated store if present; the editor often keeps them in the YAML string and re-parses so they are preserved across round-trips.

---

## 5. Workflow step ↔ Node data (`utils/workflowStepConverters.ts`)

- **workflowStepToFlowNodeData**: one workflow step → one `FlowNodeData` (for use in graph nodes or in nested lists inside container node data).
- **flowNodeDataToWorkflowStep**: one `FlowNodeData` → one `WorkflowStep` (for graph-to-yaml).
- **workflowStepsToFlowNodeData**: list of workflow steps → list of `FlowNodeData` (for nested then/else/loop/cases/default).

These helpers keep a single place for the semantic mapping between YAML step shapes and editor node data (including handling optional fields and defaults).

---

## 6. Layout (`utils/layout.ts`)

- **getNodeDimensions**: Uses React Flow measured size when available; otherwise type-based defaults (with special handling for container nodes and nested step height).
- **getLayoutedElements**: Uses **dagre** to compute positions for all nodes (direction TB or LR), then returns nodes with updated `position` and edges (optionally with waypoints for cleaner lines). React Flow’s `useUpdateNodeInternals` is used so that handle positions are correct after layout.

---

## 7. Run Agent API (Vite plugin in `vite.config.ts`)

The Vite dev server is extended with a plugin that:

- **POST /api/run-agent**: Body `{ yaml: string, args?: string[], dashboard?: boolean, modules?: Record<string, string> }`. Writes the main plan to `outputs/_ui_runs/run_<id>.yaml` and, if `modules` is provided, writes each value to `outputs/_ui_runs/run_<id>_modules/<path>`. Replaces references to those paths in the YAML with absolute paths. Then spawns `scripts/run_agent.sh` with the plan path and optional `--no_dashboard` and extra args. Returns `{ id, planPath }`.
- **GET /api/run-agent/:id**: Returns run status (state, timestamps, exitCode, planPath, dashboardUrl, etc.).
- **GET /api/run-agent/:id/stream**: Server-Sent Events stream of run log and status updates.
- **POST /api/run-agent/:id/stop**: Sends SIGTERM (process group) to the run; after timeout, SIGKILL.
- **GET /api/dashboard/:id/***: Proxies to the dashboard server for that run (port discovered from run output or from `outputs/_ui_runs/run_<id>.meta.json`). The dashboard may be started on demand by the plugin (e.g. via `scripts/dashboard.py`).

So “Run” in the UI only works when the app is served by this Vite dev server; a static build has no backend.

---

## 8. Contexts

- **InnerStepContext**: Which step inside an if/while/for_each/switch is selected for editing; used by **InnerStepConfigPanel**.
- **SubmoduleStepContext**: Which step in a **submodule** (called module) is selected; used by **SubmoduleStepConfigPanel** and **SubmoduleInlineViewer**.
- **LayoutContext** / **LayoutDirectionContext**: Used for layout direction and any layout-related options.
- **ModulesContext**: Provides uploaded/custom module list to the sidebar and run payload.

---

## 9. History (Undo/Redo)

- **useHistory**: Maintains an array of `{ nodes, edges }` snapshots and a current index. `pushHistory` is called on graph changes (debounced); undo/redo move the index and return the snapshot. The app then sets React Flow state from that snapshot and regenerates YAML from the graph so that YAML and graph stay consistent.
- **useUndoRedoKeyboard**: Registers Ctrl/Cmd+Z (undo), Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y (redo), and skips when focus is in an input/textarea.

---

## 10. Image export (`utils/image.ts`)

Uses **html-to-image** to capture the React Flow viewport (or specified element) and optionally **jsPDF** for PDF. Supports PNG, SVG, and PDF; scale and format are chosen in the toolbar export menu.
