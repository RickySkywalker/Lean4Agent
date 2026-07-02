import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  BackgroundVariant,
  MarkerType,
  DefaultEdgeOptions,
  useUpdateNodeInternals,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { FlowNode, FlowEdge, FlowNodeData, NODE_CONFIGS, NodeType, WorkflowStep } from './types';
import Sidebar, { ModuleTemplate, PREDEFINED_MODULES } from './components/Sidebar';
import NodeConfigPanel from './components/NodeConfigPanel';
import YamlEditor from './components/YamlEditor';
import Toolbar, { RunOptions } from './components/Toolbar';
import Resizer from './components/Resizer';
import ModuleDetailPanel from './components/ModuleDetailPanel';
import InnerStepConfigPanel from './components/InnerStepConfigPanel';
import SubmoduleStepConfigPanel from './components/SubmoduleStepConfigPanel';
import { nodeTypes } from './components/nodes';
import { yamlToGraph } from './converters/yaml-to-graph';
import { graphToYaml } from './converters/graph-to-yaml';
import { getLayoutedElements } from './utils/layout';
import { downloadImage, ImageFormat } from './utils/image';
import { collectDependentModules } from './utils/collectModules';
import { parseModuleYaml, looksLikeMainPlan } from './utils/parseModuleYaml';
import { updateNestedStructure, insertNestedItem } from './utils/flow-utils';
import { InnerStepProvider, useInnerStep } from './contexts/InnerStepContext';
import { SubmoduleStepProvider, useSubmoduleStep } from './contexts/SubmoduleStepContext';
import { ModulesContext } from './contexts/ModulesContext';
import { LayoutDirectionProvider } from './contexts/LayoutDirectionContext';
import { LayoutProvider } from './contexts/LayoutContext';
import { useHistory, useUndoRedoKeyboard } from './hooks/useHistory';
import { workflowStepsToFlowNodeData } from './utils/workflowStepConverters';
import { updateModuleWorkflowYaml } from './utils/moduleYaml';
import { X, Square } from 'lucide-react';
import AnsiToHtml from 'ansi-to-html';
import yamlLib from 'js-yaml';

const MODULES_STORAGE_KEY = 'yaml-flow-editor-modules-library';

const UI_TERMINAL_BG = '#0b0f17';
const UI_TERMINAL_FG = '#e5e7eb';
// High-contrast ANSI palette (roughly aligned with modern terminals / VSCode Dark+)
const UI_TERMINAL_ANSI_COLORS = [
  '#000000', // black
  '#cd3131', // red
  '#0dbc79', // green
  '#e5e510', // yellow
  '#2472c8', // blue
  '#bc3fbc', // magenta
  '#11a8cd', // cyan
  '#e5e5e5', // white (light gray)
  '#666666', // bright black
  '#f14c4c', // bright red
  '#23d18b', // bright green
  '#f5f543', // bright yellow
  '#3b8eea', // bright blue
  '#d670d6', // bright magenta
  '#29b8db', // bright cyan
  '#ffffff', // bright white
];

const MIN_SIDEBAR_WIDTH = 120;
const MAX_SIDEBAR_WIDTH = 250;
const MIN_PANEL_WIDTH = 200;
const MAX_PANEL_WIDTH = 600;

type FolderYamlCandidate = {
  path: string;
  content: string;
};

const INITIAL_YAML = `name: "my_task"
goal: "A sample workflow"

workflow:
  - task:
      name: "first_task"
      instruction: "Do something first"
      save_as: "result1"

  - task:
      name: "second_task"
      instruction: "Do something second"
      save_as: "result2"
`;

function HandleInternalsSync({
  nodeIds,
  direction,
  updateNodeInternals,
}: {
  nodeIds: string[];
  direction: 'TB' | 'LR';
  updateNodeInternals: (id: string) => void;
}) {
  useEffect(() => {
    // update now and next frame for consistency
    nodeIds.forEach((id) => updateNodeInternals(id));
    requestAnimationFrame(() => nodeIds.forEach((id) => updateNodeInternals(id)));
  }, [direction, nodeIds, updateNodeInternals]);
  return null;
}

function FlowEditor() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChangeRaw] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChangeRaw] = useEdgesState<FlowEdge>([]);

  // ── Protect start/end nodes and their edges from deletion ────────
  const isProtectedType = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      return node?.type === 'start' || node?.type === 'end';
    },
    [nodes],
  );

  const onNodesChange = useCallback(
    (changes: import('@xyflow/react').NodeChange<FlowNode>[]) => {
      const filtered = changes.filter(
        (c) => c.type !== 'remove' || !isProtectedType(c.id),
      );
      onNodesChangeRaw(filtered);
    },
    [isProtectedType, onNodesChangeRaw],
  );

  // Block edge removal when it's triggered by selecting a start/end node and pressing Delete.
  // Allow edge removal when the user clicks directly on an edge and deletes it.
  // Distinction: if any selected node is start/end, the edge removal is collateral → block it.
  const onEdgesChange = useCallback(
    (changes: import('@xyflow/react').EdgeChange<FlowEdge>[]) => {
      const hasSelectedProtected = nodes.some(
        (n) => n.selected && (n.type === 'start' || n.type === 'end'),
      );
      if (!hasSelectedProtected) {
        // No protected node is selected → allow all edge changes (direct edge deletion)
        onEdgesChangeRaw(changes);
        return;
      }
      // A protected node is selected → block removal of edges touching it
      const filtered = changes.filter((c) => {
        if (c.type !== 'remove') return true;
        const edge = edges.find((e) => e.id === c.id);
        if (edge && (isProtectedType(edge.source) || isProtectedType(edge.target))) {
          return false;
        }
        return true;
      });
      onEdgesChangeRaw(filtered);
    },
    [nodes, edges, isProtectedType, onEdgesChangeRaw],
  );
  const nodesRef = useRef<FlowNode[]>([]);
  const edgesRef = useRef<FlowEdge[]>([]);
  const dragOverBranchRef = useRef<HTMLElement | null>(null);
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [selectedModule, setSelectedModule] = useState<ModuleTemplate | null>(null);
  const [yaml, setYaml] = useState(INITIAL_YAML);
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [showYamlEditor, setShowYamlEditor] = useState(false);
  const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
  const [layoutDirection, setLayoutDirection] = useState<'TB' | 'LR'>('TB');
  const [layoutCompact, setLayoutCompact] = useState(true);
  const updateNodeInternals = useUpdateNodeInternals();

  // Run agent (via Vite dev server middleware)
  const [runPanelOpen, setRunPanelOpen] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [runState, setRunState] = useState<'idle' | 'running' | 'exited'>('idle');
  const [runExitCode, setRunExitCode] = useState<number | null>(null);
  const [runLog, setRunLog] = useState('');
  const runLogContainerRef = useRef<HTMLDivElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [terminalHeight, setTerminalHeight] = useState(224); // default ~h-56
  const [isFollowingRunLog, setIsFollowingRunLog] = useState(true);
  const [runOptions, setRunOptions] = useState<RunOptions>({
    dashboard: true,
    resume: false,
    model: '',
    maxTokensPerStep: '',
    maxToolCallsPerStep: '',
    planRevisionMaxSteps: '',
    mcpUrl: '',
    outputDir: '',
    checkpointPath: '',
    tracePath: '',
    replayTrace: '',
    extraArgs: '',
  });
  const [dashboardUrl, setDashboardUrl] = useState<string | null>(null);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [pendingInput, setPendingInput] = useState<{
    runId: string;
    stepId: string;
    prompt: string;
    default: string;
    saveAs: string;
  } | null>(null);
  const [pendingInputValue, setPendingInputValue] = useState<string>('');
  const [pendingInputOpen, setPendingInputOpen] = useState<boolean>(false);
  const [folderImportOpen, setFolderImportOpen] = useState(false);
  const [folderImportCandidates, setFolderImportCandidates] = useState<FolderYamlCandidate[]>([]);
  const [folderImportSelectedPath, setFolderImportSelectedPath] = useState('');
  const [folderImportAllContents, setFolderImportAllContents] = useState<FolderYamlCandidate[]>([]);

  // User-uploaded submodules (path -> content + template for Sidebar)
  // Persisted to localStorage so they survive page refreshes and Clear operations.
  const [uploadedModules, setUploadedModules] = useState<Array<{ path: string; content: string; template: ModuleTemplate }>>(() => {
    try {
      const stored = localStorage.getItem(MODULES_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch { return []; }
  });

  useEffect(() => {
    try {
      localStorage.setItem(MODULES_STORAGE_KEY, JSON.stringify(uploadedModules));
    } catch { /* quota exceeded — silently ignore */ }
  }, [uploadedModules]);

  const modulesByPath = useMemo(() => {
    const record: Record<string, { path: string; content: string; template: ModuleTemplate }> = {};
    for (const m of uploadedModules) {
      record[m.path] = m;
    }
    return record;
  }, [uploadedModules]);

  const queueUploadedModules = useCallback((moduleContents: FolderYamlCandidate[]) => {
    if (moduleContents.length === 0) return;

    const BATCH_SIZE = 10;
    const processModulesBatch = (startIndex: number) => {
      try {
        const endIndex = Math.min(startIndex + BATCH_SIZE, moduleContents.length);
        const batch = moduleContents.slice(startIndex, endIndex);

        const newUploaded = batch.map((c) => {
          try {
            const template = parseModuleYaml(c.content, c.path);
            return { path: c.path, content: c.content, template };
          } catch (e) {
            console.warn(`Failed to parse module ${c.path}:`, e);
            return {
              path: c.path,
              content: c.content,
              template: {
                name: c.path.split('/').pop()?.replace(/\.(yaml|yml)$/i, '') || 'Module',
                path: c.path,
                description: 'Failed to parse',
                goal: '',
                defaultParams: {},
                workflow: [],
              },
            };
          }
        });

        if (newUploaded.length > 0) {
          setUploadedModules((prev) => {
            const byPath = new Map(prev.map((m) => [m.path, m]));
            newUploaded.forEach((u) => byPath.set(u.path, u));
            return Array.from(byPath.values());
          });
        }

        if (endIndex < moduleContents.length) {
          if (typeof requestIdleCallback !== 'undefined') {
            requestIdleCallback(() => processModulesBatch(endIndex), { timeout: 50 });
          } else {
            setTimeout(() => processModulesBatch(endIndex), 10);
          }
        }
      } catch (e) {
        console.error('Error in processModulesBatch:', e);
      }
    };

    setTimeout(() => {
      try {
        processModulesBatch(0);
      } catch (e) {
        console.error('Error starting module processing:', e);
      }
    }, 200);
  }, []);

  // Inner step selection context
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  // Submodule step selection context
  const { selectedSubmoduleStep, selectSubmoduleStep, updateSubmoduleStep, setOnUpdateCallback } = useSubmoduleStep();
  const selectedSubmoduleStepRef = useRef(selectedSubmoduleStep);
  selectedSubmoduleStepRef.current = selectedSubmoduleStep;

  // Mutual exclusion: selecting an inner step clears the submodule step and vice versa.
  // This prevents the right panel from getting stuck showing a stale selection.
  useEffect(() => {
    if (selectedInnerStep) selectSubmoduleStep(null);
  }, [selectedInnerStep]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (selectedSubmoduleStep) selectInnerStep(null);
  }, [selectedSubmoduleStep]); // eslint-disable-line react-hooks/exhaustive-deps

  // Panel widths
  const [sidebarWidth, setSidebarWidth] = useState(192); // w-48 = 12rem = 192px
  const [rightPanelWidth, setRightPanelWidth] = useState(320); // w-80 = 20rem = 320px

  // Sync flag to prevent circular updates
  const isUpdatingFromYaml = useRef(false);
  const isUpdatingFromGraph = useRef(false);
  
  // History management for undo/redo
  const { pushHistory, undo, redo, canUndo, canRedo, clearHistory } = useHistory({ maxHistorySize: 50 });
  const isUndoRedoRef = useRef(false);
  
  // Keep latest nodes/edges for async layout passes
  useEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, [nodes, edges]);

  // Track changes to push to history (debounced)
  const historyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  useEffect(() => {
    // Don't push to history during undo/redo operations
    if (isUndoRedoRef.current || isUpdatingFromYaml.current) return;
    if (nodes.length === 0) return;
    
    // Debounce history updates
    if (historyTimeoutRef.current) {
      clearTimeout(historyTimeoutRef.current);
    }
    
    historyTimeoutRef.current = setTimeout(() => {
      pushHistory(nodes, edges);
    }, 300);
    
    return () => {
      if (historyTimeoutRef.current) {
        clearTimeout(historyTimeoutRef.current);
      }
    };
  }, [nodes, edges, pushHistory]);
  
  // Undo handler
  const handleUndo = useCallback(() => {
    const state = undo();
    if (state) {
      isUndoRedoRef.current = true;
      setNodes(state.nodes);
      setEdges(state.edges);
      setSelectedNode(null);
      selectInnerStep(null);
      
      // Also update YAML
      try {
        isUpdatingFromGraph.current = true;
        const newYaml = graphToYaml(state.nodes, state.edges);
        setYaml(newYaml);
      } catch (e) {
        console.error('Failed to generate YAML after undo:', e);
      } finally {
        setTimeout(() => {
          isUpdatingFromGraph.current = false;
          isUndoRedoRef.current = false;
        }, 150);
      }
    }
  }, [undo, setNodes, setEdges, selectInnerStep, selectSubmoduleStep]);
  
  // Redo handler
  const handleRedo = useCallback(() => {
    const state = redo();
    if (state) {
      isUndoRedoRef.current = true;
      setNodes(state.nodes);
      setEdges(state.edges);
      setSelectedNode(null);
      selectInnerStep(null);
      selectSubmoduleStep(null);
      
      // Also update YAML
      try {
        isUpdatingFromGraph.current = true;
        const newYaml = graphToYaml(state.nodes, state.edges);
        setYaml(newYaml);
      } catch (e) {
        console.error('Failed to generate YAML after redo:', e);
      } finally {
        setTimeout(() => {
          isUpdatingFromGraph.current = false;
          isUndoRedoRef.current = false;
        }, 150);
      }
    }
  }, [redo, setNodes, setEdges, selectInnerStep, selectSubmoduleStep]);
  
  // Register keyboard shortcuts for undo/redo
  useUndoRedoKeyboard(handleUndo, handleRedo, true);

  // Delete/Backspace for selected inner steps
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      if (!selectedInnerStep) return;

      // Don't intercept when typing in inputs
      const el = document.activeElement;
      if (
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement ||
        (el as HTMLElement)?.isContentEditable
      ) return;

      e.preventDefault();
      e.stopPropagation();

      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id === selectedInnerStep.parentNodeId) {
            const nodeData = node.data as Record<string, unknown>;
            const pathParts = selectedInnerStep.branch.split('.');
            return {
              ...node,
              data: updateNestedStructure(nodeData, pathParts, selectedInnerStep.stepIndex, null),
            };
          }
          return node;
        })
      );
      selectInnerStep(null);
    };

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [selectedInnerStep, setNodes, selectInnerStep]);

  // Resize handlers
  const handleSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((prev) => Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, prev + delta)));
  }, []);

  const handleRightPanelResize = useCallback((delta: number) => {
    setRightPanelWidth((prev) => Math.max(MIN_PANEL_WIDTH, Math.min(MAX_PANEL_WIDTH, prev - delta)));
  }, []);

  // Track if initial fitView has been called for current layout direction
  const lastFitViewLayoutDirectionRef = useRef<'TB' | 'LR' | null>(null);
  const isInitialLoadRef = useRef(true);

  // Initialize from YAML
  useEffect(() => {
    try {
      isUpdatingFromYaml.current = true;
      const { nodes: newNodes, edges: newEdges } = yamlToGraph(yaml);
      const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(newNodes, newEdges, layoutDirection, { compact: layoutCompact });
      setNodes(layoutedNodes);
      setEdges(layoutedEdges);
      // Reset fitView flag when layout direction changes or on initial load
      if (lastFitViewLayoutDirectionRef.current !== layoutDirection || isInitialLoadRef.current) {
        lastFitViewLayoutDirectionRef.current = null;
      }
      isInitialLoadRef.current = false;
    } catch (e) {
      console.error('Failed to parse initial YAML:', e);
    } finally {
      isUpdatingFromYaml.current = false;
    }
  }, [layoutDirection]);

  // Re-layout when compact spacing is toggled (use current nodes/edges)
  const prevLayoutCompactRef = useRef(layoutCompact);
  useEffect(() => {
    if (prevLayoutCompactRef.current === layoutCompact) return;
    prevLayoutCompactRef.current = layoutCompact;
    const currentNodes = nodesRef.current;
    const currentEdges = edgesRef.current;
    if (currentNodes.length === 0) return;
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      currentNodes,
      currentEdges,
      layoutDirection,
      { compact: layoutCompact }
    );
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutCompact]);

  // Fit view after initial load and when ReactFlow instance is ready
  useEffect(() => {
    if (
      lastFitViewLayoutDirectionRef.current !== layoutDirection &&
      reactFlowInstance &&
      nodes.length > 0 &&
      !isUpdatingFromYaml.current
    ) {
      // Use requestAnimationFrame to ensure DOM is ready and layout is complete
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          try {
            reactFlowInstance.fitView({
              padding: 0.2,
              duration: 300,
            });
            lastFitViewLayoutDirectionRef.current = layoutDirection;
          } catch {
            // ignore errors
          }
        });
      });
    }
  }, [reactFlowInstance, nodes, layoutDirection]);

  // Update YAML when graph changes (with debounce to avoid overwriting user edits)
  useEffect(() => {
    if (isUpdatingFromYaml.current) return;
    if (nodes.length === 0) return;
    
    // Debounce the YAML update to avoid rapid updates while user is editing
    const timeoutId = setTimeout(() => {
      // Check again after debounce in case user started editing
      if (isUpdatingFromYaml.current) return;
      
      try {
        isUpdatingFromGraph.current = true;
        const newYaml = graphToYaml(nodes, edges);
        setYaml(newYaml);
      } catch (e) {
        console.error('Failed to generate YAML:', e);
      } finally {
        isUpdatingFromGraph.current = false;
      }
    }, 100);
    
    return () => clearTimeout(timeoutId);
  }, [nodes, edges]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => {
      // Prevent 1-to-n: only one edge per (source, sourceHandle)
      const sourceHandle = params.sourceHandle ?? null;
      const hasSameSource = eds.some(
        (e) => e.source === params.source && (e.sourceHandle ?? null) === sourceHandle
      );
      if (hasSameSource) return eds;

      // Prevent n-to-1: only one incoming edge per target node
      const hasIncoming = eds.some((e) => e.target === params.target);
      if (hasIncoming) return eds;

      return addEdge(params, eds);
    }),
    [setEdges]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      if (!reactFlowInstance) return;

      // Handle dragging an inner step out of a container onto the canvas
      const reorderData = event.dataTransfer.getData('application/nested-reorder');
      if (reorderData) {
        try {
          const { index: srcIndex, branch: srcBranch, parentNodeId, stepData } = JSON.parse(reorderData);
          if (!parentNodeId || !stepData) return;

          const position = reactFlowInstance.screenToFlowPosition({
            x: event.clientX,
            y: event.clientY,
          });

          const nodeType = stepData.nodeType || 'step';
          const newNode: FlowNode = {
            id: `${nodeType}_${Date.now()}`,
            type: nodeType,
            position,
            data: stepData as FlowNodeData,
          };

          // Remove step from parent container and add as standalone node
          setNodes((nds) => {
            const updated = nds.map((node) => {
              if (node.id !== parentNodeId) return node;
              const nodeData = node.data as Record<string, unknown>;
              const pathParts = srcBranch.split('.');
              return {
                ...node,
                data: updateNestedStructure(nodeData, pathParts, srcIndex, null),
              };
            });
            return updated.concat(newNode);
          });

          selectInnerStep(null);
        } catch (err) {
          console.error('Failed to extract inner step:', err);
        }
        return;
      }

      const type = event.dataTransfer.getData('application/reactflow') as NodeType;
      if (!type) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const config = NODE_CONFIGS[type];

      // Check if this is a module drag
      const moduleDataStr = event.dataTransfer.getData('application/module');
      let nodeData = {
        ...config.defaultData,
        label: config.label,
        nodeType: type,
      } as FlowNodeData;

      if (moduleDataStr && type === 'call') {
        try {
          const moduleData = JSON.parse(moduleDataStr);
          nodeData = {
            ...nodeData,
            label: `Call: ${moduleData.name}`,
            module: moduleData.path,
            parameters: moduleData.defaultParams || {},
          } as FlowNodeData;
        } catch (e) {
          console.error('Failed to parse module data:', e);
        }
      }

      const newNode: FlowNode = {
        id: `${type}_${Date.now()}`,
        type,
        position,
        data: nodeData,
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance, setNodes, selectInnerStep]
  );

  // Visual feedback: highlight the specific branch zone under the mouse
  const onNodeDrag = useCallback((event: React.MouseEvent, draggedNode: FlowNode) => {
    const containerTypes = new Set(['if', 'while', 'for_each', 'switch']);
    const draggedType = draggedNode.type || '';
    if (draggedType === 'start' || draggedType === 'end') {
      if (dragOverBranchRef.current) {
        dragOverBranchRef.current.classList.remove('drop-target-highlight');
        dragOverBranchRef.current = null;
      }
      return;
    }

    // Check if dragged node overlaps any container
    const dw = draggedNode.measured?.width || 0;
    const dh = draggedNode.measured?.height || 0;
    const cx = draggedNode.position.x + dw / 2;
    const cy = draggedNode.position.y + dh / 2;

    const container = nodesRef.current.find(n => {
      if (n.id === draggedNode.id) return false;
      if (!containerTypes.has(n.type || '')) return false;
      const w = n.measured?.width || 0;
      const h = n.measured?.height || 0;
      if (w === 0 || h === 0) return false;
      return cx >= n.position.x && cx <= n.position.x + w &&
             cy >= n.position.y && cy <= n.position.y + h;
    });

    // Find the specific branch drop zone under the mouse
    let targetBranch: HTMLElement | null = null;
    if (container) {
      const elements = document.elementsFromPoint(event.clientX, event.clientY);
      for (const el of elements) {
        if ((el as HTMLElement).dataset?.branch != null) {
          targetBranch = el as HTMLElement;
          break;
        }
      }
    }

    if (targetBranch !== dragOverBranchRef.current) {
      dragOverBranchRef.current?.classList.remove('drop-target-highlight');
      targetBranch?.classList.add('drop-target-highlight');
      dragOverBranchRef.current = targetBranch;
    }
  }, []);

  // Allow dragging a canvas node into a container node (if/while/for_each/switch)
  const onNodeDragStop = useCallback((event: React.MouseEvent, draggedNode: FlowNode) => {
    // Clear drop target highlight
    if (dragOverBranchRef.current) {
      dragOverBranchRef.current.classList.remove('drop-target-highlight');
      dragOverBranchRef.current = null;
    }

    const containerTypes = new Set(['if', 'while', 'for_each', 'switch']);
    const draggedType = draggedNode.type || '';

    // start/end nodes cannot be moved into containers
    if (draggedType === 'start' || draggedType === 'end') return;

    // Center of the dragged node
    const dw = draggedNode.measured?.width || 0;
    const dh = draggedNode.measured?.height || 0;
    const cx = draggedNode.position.x + dw / 2;
    const cy = draggedNode.position.y + dh / 2;

    // Find a container node whose bounds contain the dragged node's center
    const container = nodesRef.current.find(n => {
      if (n.id === draggedNode.id) return false;
      if (!containerTypes.has(n.type || '')) return false;
      const w = n.measured?.width || 0;
      const h = n.measured?.height || 0;
      if (w === 0 || h === 0) return false;
      return cx >= n.position.x && cx <= n.position.x + w &&
             cy >= n.position.y && cy <= n.position.y + h;
    });

    if (!container) return;

    const stepData = { ...draggedNode.data, nodeType: draggedType } as FlowNodeData;

    // Use DOM to determine which branch and insertion index the mouse is over
    const mouseX = event.clientX;
    const mouseY = event.clientY;
    const elements = document.elementsFromPoint(mouseX, mouseY);

    // Find the branch drop zone under the mouse
    let branch: string | null = null;
    for (const el of elements) {
      const b = (el as HTMLElement).dataset?.branch;
      if (b) { branch = b; break; }
    }

    // Find the step element under the mouse to determine insertion index
    let insertIndex = -1; // -1 means append
    for (const el of elements) {
      const si = (el as HTMLElement).dataset?.stepIndex;
      if (si != null) {
        const idx = parseInt(si, 10);
        const rect = (el as HTMLElement).getBoundingClientRect();
        const mid = rect.top + rect.height / 2;
        insertIndex = mouseY < mid ? idx : idx + 1;
        break;
      }
    }

    if (!branch) return;

    // Use insertNestedItem to handle both top-level and nested branch paths
    const pathParts = branch.split('.');
    // insertIndex -1 means append; use a large number so splice appends
    const idx = insertIndex >= 0 ? insertIndex : 999999;

    setNodes(nds =>
      nds
        .filter(n => n.id !== draggedNode.id)
        .map(n => {
          if (n.id !== container.id) return n;
          const d = n.data as Record<string, unknown>;
          return { ...n, data: insertNestedItem(d, pathParts, idx, stepData) };
        })
    );

    // Reconnect surrounding edges (A→dragged→B becomes A→B), then remove leftovers
    setEdges(eds => {
      const incoming = eds.filter(e => e.target === draggedNode.id);
      const outgoing = eds.filter(e => e.source === draggedNode.id);
      const remaining = eds.filter(e => e.source !== draggedNode.id && e.target !== draggedNode.id);

      const reconnections: typeof eds = [];
      for (const inc of incoming) {
        for (const out of outgoing) {
          reconnections.push({
            ...inc,
            id: `${inc.source}-${out.target}`,
            target: out.target,
            targetHandle: out.targetHandle,
          });
        }
      }
      return [...remaining, ...reconnections];
    });

    setSelectedNode(null);
  }, [setNodes, setEdges]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: FlowNode) => {
    setSelectedNode(node);
    setSelectedModule(null);
    setShowYamlEditor(false);
    selectInnerStep(null);
    selectSubmoduleStep(null);
  }, [selectInnerStep, selectSubmoduleStep]);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    selectInnerStep(null); // Clear inner step selection
    selectSubmoduleStep(null); // Clear submodule step selection
  }, [selectInnerStep, selectSubmoduleStep]);

  const onModuleSelect = useCallback((module: ModuleTemplate | null) => {
    setSelectedModule(module);
    if (module) {
      setSelectedNode(null);
      setShowYamlEditor(false);
    }
  }, []);

  const onNodeDataChange = useCallback(
    (nodeId: string, newData: Partial<FlowNodeData>) => {
      setNodes((nds) =>
        nds.map((node) => {
          if (node.id === nodeId) {
            return {
              ...node,
              data: { ...node.data, ...newData },
            };
          }
          return node;
        })
      );
      // Update selected node
      setSelectedNode((prev) =>
        prev?.id === nodeId
          ? { ...prev, data: { ...prev.data, ...newData } }
          : prev
      );
    },
    [setNodes]
  );

  const onDeleteNode = useCallback(
    (nodeId: string) => {
      // Prevent deletion of start/end nodes
      const node = nodes.find((n) => n.id === nodeId);
      if (node && (node.type === 'start' || node.type === 'end')) return;

      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) =>
        eds.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
      );
      if (selectedNode?.id === nodeId) {
        setSelectedNode(null);
      }
    },
    [setNodes, setEdges, selectedNode, nodes]
  );

  const applyYamlToGraph = useCallback((newYaml: string, opts?: { force?: boolean }) => {
    const force = opts?.force === true;
    if (!force && isUpdatingFromGraph.current) return;

    try {
      isUpdatingFromYaml.current = true;
      const { nodes: newNodes, edges: newEdges } = yamlToGraph(newYaml);
      
      // Update YAML only after successful parsing
      setYaml(newYaml);
      
      // For large graphs, defer layout to avoid blocking, but still show nodes immediately
      // Check if this is a large graph (more than 50 nodes)
      const isLargeGraph = newNodes.length > 50;
      
      if (isLargeGraph) {
        // For large graphs, show nodes immediately without layout, then layout async
        try {
          nodesRef.current = newNodes;
          edgesRef.current = newEdges;
          setNodes(newNodes);
          setEdges(newEdges);
          setYamlError(null);
        } catch (e) {
          console.error('Error setting nodes/edges:', e);
          isUpdatingFromYaml.current = false;
          return;
        }
        
        // Defer layout calculation to avoid blocking the UI
        requestAnimationFrame(() => {
          try {
            const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
              nodesRef.current,
              edgesRef.current,
              layoutDirection,
              { compact: layoutCompact }
            );
            nodesRef.current = layoutedNodes;
            edgesRef.current = layoutedEdges;
            setNodes(layoutedNodes);
            setEdges(layoutedEdges);

            // Second-pass layout
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                try {
                  const { nodes: layout2, edges: edges2 } = getLayoutedElements(
                    nodesRef.current,
                    edgesRef.current,
                    layoutDirection,
                    { compact: layoutCompact }
                  );
                  nodesRef.current = layout2;
                  edgesRef.current = edges2;
                  setNodes(layout2);
                  setEdges(edges2);
                  setTimeout(() => {
                    isUpdatingFromYaml.current = false;
                  }, 150);
                } catch (e) {
                  console.error('Error in second-pass layout:', e);
                  isUpdatingFromYaml.current = false;
                }
              });
            });
          } catch (e) {
            console.error('Error in layout calculation:', e);
            isUpdatingFromYaml.current = false;
          }
        });
      } else {
        // For small graphs, do layout synchronously (original behavior)
        try {
          const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
            newNodes,
            newEdges,
            layoutDirection,
            { compact: layoutCompact }
          );
          nodesRef.current = layoutedNodes;
          edgesRef.current = layoutedEdges;
          setNodes(layoutedNodes);
          setEdges(layoutedEdges);
          setYamlError(null);
        } catch (e) {
          console.error('Error in initial layout:', e);
          isUpdatingFromYaml.current = false;
          return;
        }

        // Multi-pass layout to ensure measured sizes + handle internals settle
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try {
              const { nodes: layout2, edges: edges2 } = getLayoutedElements(
                nodesRef.current,
                edgesRef.current,
                layoutDirection,
                { compact: layoutCompact }
              );
              nodesRef.current = layout2;
              edgesRef.current = edges2;
              setNodes(layout2);
              setEdges(edges2);
              setTimeout(() => {
                isUpdatingFromYaml.current = false;
              }, 150);
            } catch (e) {
              console.error('Error in second-pass layout:', e);
              isUpdatingFromYaml.current = false;
            }
          });
        });
      }
    } catch (e) {
      const error = e as Error;
      let errorMessage = error.message || 'Unknown error';
      const lineMatch = errorMessage.match(/at line (\d+)/i) || errorMessage.match(/line (\d+)/i);
      if (lineMatch) {
        errorMessage = `Line ${lineMatch[1]}: ${errorMessage}`;
      }
      try {
        setYamlError(errorMessage);
      } catch (setError) {
        console.error('Error setting YAML error:', setError);
      }
      isUpdatingFromYaml.current = false;
      // Don't update YAML if parsing failed
      console.error('Failed to parse YAML:', error);
    }
  }, [layoutDirection, layoutCompact, reactFlowInstance, setNodes, setEdges]);

  const onYamlChange = useCallback(
    (newYaml: string) => {
      applyYamlToGraph(newYaml, { force: false });
    },
    [applyYamlToGraph]
  );

  const onAutoLayout = useCallback((fitView: boolean = true) => {
    // Two-pass layout:
    // 1) Layout with current (possibly estimated) sizes
    // 2) After ReactFlow updates measured sizes, layout again to eliminate overlaps
    const apply = (dir: 'TB' | 'LR') => {
      const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
        nodesRef.current,
        edgesRef.current,
        dir,
        { compact: layoutCompact }
      );
      setNodes(layoutedNodes);
      setEdges(layoutedEdges);
    };
    apply(layoutDirection);
    // Next frames: measured sizes (node.measured) are more likely available, then optionally fit the whole graph
    requestAnimationFrame(() => {
      apply(layoutDirection);
      requestAnimationFrame(() => {
        if (!reactFlowInstance) return;
        if (fitView) {
          try {
            // Only fitView when explicitly requested (e.g., from toolbar), not automatically
            // This prevents unwanted zooming when submodules expand
            reactFlowInstance.fitView({
              padding: 0.2,
              duration: 300,
            });
          } catch {
            // best-effort; ignore centering errors
          }
        }
      });
    });
  }, [layoutDirection, layoutCompact, setNodes, setEdges, reactFlowInstance]);

  const onLayoutOnly = useCallback(() => {
    onAutoLayout(false);
  }, [onAutoLayout]);

  const applyFolderImportSelection = useCallback((mainPath?: string | null) => {
    const selectedMain = folderImportAllContents.find((c) => c.path === mainPath) ?? null;

    if (selectedMain) {
      requestAnimationFrame(() => {
        try {
          applyYamlToGraph(selectedMain.content, { force: true });
          setTimeout(() => onAutoLayout(true), 300);
        } catch (e) {
          console.error('Failed to apply main graph:', e);
        }
      });
    }

    const moduleContents = folderImportAllContents.filter((c) => !mainPath || c.path !== mainPath);
    queueUploadedModules(moduleContents);

    setFolderImportOpen(false);
    setFolderImportCandidates([]);
    setFolderImportSelectedPath('');
    setFolderImportAllContents([]);
  }, [applyYamlToGraph, folderImportAllContents, onAutoLayout, queueUploadedModules]);

  const onLayoutDirectionChange = useCallback(
    (dir: 'TB' | 'LR') => {
      setLayoutDirection(dir);
      // Re-layout immediately for better UX.
      const apply = () => {
        const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
          nodesRef.current,
          edgesRef.current,
          dir,
          { compact: layoutCompact }
        );
        setNodes(layoutedNodes);
        setEdges(layoutedEdges);
      };
      apply();

      // Next frames: allow React Flow to update node measurements, then fit the whole graph
      requestAnimationFrame(() => {
        apply();
        requestAnimationFrame(() => {
          if (!reactFlowInstance) return;
          try {
            reactFlowInstance.fitView({
              padding: 0.2,
              duration: 300,
            });
          } catch {
            // best-effort; ignore centering errors
          }
        });
      });
    },
    [setNodes, setEdges, reactFlowInstance]
  );

  const onExport = useCallback(() => {
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'workflow.yaml';
    a.click();
    URL.revokeObjectURL(url);
  }, [yaml]);

  const onExportFolder = useCallback(async () => {
    const JSZip = (await import('jszip')).default;
    const zip = new JSZip();

    // Extract task name from YAML for the folder name
    let taskName = 'workflow';
    try {
      const parsed = yamlLib.load(yaml) as Record<string, unknown> | null;
      if (parsed?.name && typeof parsed.name === 'string') {
        taskName = parsed.name.replace(/\s+/g, '_');
      }
    } catch { /* use default */ }

    const folder = zip.folder(taskName)!;
    folder.file('main.yaml', yaml);

    const modules = collectDependentModules(yaml, modulesByPath, nodesRef.current);
    for (const [modPath, content] of modules) {
      folder.file(modPath, content);
    }

    const blob = await zip.generateAsync({ type: 'blob' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${taskName}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }, [yaml, modulesByPath]);

  const onExportImage = useCallback((format: ImageFormat, scale: number) => {
    downloadImage(nodes, { format, scale });
  }, [nodes]);

  const onImport = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.yaml,.yml';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (event) => {
          const content = event.target?.result as string;
          applyYamlToGraph(content, { force: true });
          setTimeout(() => onAutoLayout(true), 300);
        };
        reader.readAsText(file);
      }
    };
    input.click();
  }, [applyYamlToGraph, onAutoLayout]);

  const onImportSubmodules = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.yaml,.yml';
    input.multiple = true;
    input.onchange = (e) => {
      const files = (e.target as HTMLInputElement).files;
      if (!files?.length) return;
      let processed = 0;
      const next = () => {
        if (processed >= files.length) return;
        const file = files[processed];
        processed += 1;
        const reader = new FileReader();
        reader.onload = (event) => {
          const content = event.target?.result as string;
          const path = `modules/${file.name}`;
          try {
            const template = parseModuleYaml(content, path);
            setUploadedModules((prev) => {
              const without = prev.filter((m) => m.path !== path);
              return [...without, { path, content, template }];
            });
          } catch (err) {
            console.error('Failed to parse submodule:', file.name, err);
          }
          next();
        };
        reader.readAsText(file);
      };
      next();
    };
    input.click();
  }, []);

  const onImportFolder = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    // Folder upload (Chrome/Edge): allow selecting a directory.
    // Don't overly-restrict accept here; we filter in code.
    input.multiple = true;
    (input as any).webkitdirectory = true;
    input.onchange = (e) => {
      try {
        const fileList = (e.target as HTMLInputElement).files;
        if (!fileList?.length) return;
        const entries: { path: string; file: File }[] = [];
        for (let i = 0; i < fileList.length; i++) {
          const file = fileList[i];
          const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
          if (/\.(yaml|yml)$/i.test(path)) entries.push({ path, file });
        }
        if (entries.length === 0) return;
        
        // Read files asynchronously in batches to avoid blocking UI
        const BATCH_SIZE = 10; // Process 10 files at a time
        const contents: Array<{ path: string; content: string }> = [];
        let readIndex = 0;
        let activeReads = 0;
        let hasError = false;
        
        const readNextBatch = () => {
          try {
            // Read up to BATCH_SIZE files concurrently
            while (readIndex < entries.length && activeReads < BATCH_SIZE) {
              const index = readIndex++;
              activeReads++;
              const { file } = entries[index];
              const reader = new FileReader();
              
              reader.onerror = () => {
                console.error(`Failed to read file: ${entries[index].path}`);
                activeReads--;
                if (readIndex >= entries.length && activeReads === 0) {
                  if (!hasError) processAllFiles();
                } else {
                  readNextBatch();
                }
              };
              
              reader.onload = (event) => {
                try {
                  const content = event.target?.result as string;
                  if (content) {
                    contents.push({ path: entries[index].path, content });
                  }
                } catch (e) {
                  console.error(`Error processing file ${entries[index].path}:`, e);
                }
                activeReads--;
                
                // Continue reading if there are more files
                if (readIndex < entries.length) {
                  readNextBatch();
                } else if (activeReads === 0) {
                  // All files read, process them
                  if (!hasError) processAllFiles();
                }
              };
              
              reader.readAsText(file);
            }
          } catch (e) {
            console.error('Error in readNextBatch:', e);
            hasError = true;
          }
        };
        
        const processAllFiles = () => {
          if (contents.length === 0) {
            console.warn('No valid YAML files found in folder');
            return;
          }
          
          // Process files asynchronously to avoid blocking UI
          const processAsync = () => {
            try {
              // Parse all files to find main candidate
              const parsedList: Array<{ path: string; content: string; parsed: { name?: string; workflow?: unknown[] } | null }> = [];
              
              const parseBatch = (startIndex: number) => {
                try {
                  const endIndex = Math.min(startIndex + BATCH_SIZE, contents.length);
                  const batch = contents.slice(startIndex, endIndex);
                  
                  // Parse this batch
                  batch.forEach((c) => {
                    try {
                      parsedList.push({
                        path: c.path,
                        content: c.content,
                        parsed: yamlLib.load(c.content) as { name?: string; workflow?: unknown[] } | null,
                      });
                    } catch (e) {
                      console.warn(`Failed to parse ${c.path}:`, e);
                      parsedList.push({
                        path: c.path,
                        content: c.content,
                        parsed: null,
                      });
                    }
                  });
                  
                  // Continue with next batch or finish
                  if (endIndex < contents.length) {
                    if (typeof requestIdleCallback !== 'undefined') {
                      requestIdleCallback(() => parseBatch(endIndex), { timeout: 100 });
                    } else {
                      setTimeout(() => parseBatch(endIndex), 0);
                    }
                  } else {
                    // All parsed, now find main candidate and process
                    findMainAndProcess();
                  }
                } catch (e) {
                  console.error('Error in parseBatch:', e);
                  // Still try to process what we have
                  if (parsedList.length > 0) {
                    findMainAndProcess();
                  }
                }
              };
              
              const findMainAndProcess = () => {
                try {
                  const withWorkflow = parsedList.filter(
                    (p) => p.parsed && typeof p.parsed === 'object' && Array.isArray(p.parsed.workflow) && p.parsed.workflow.length > 0
                  );
                  const notInModules = withWorkflow.filter(
                    (p) => !/[/\\]modules?[/\\]/i.test(p.path) && !p.path.startsWith('modules/')
                  );
                  const mainCandidate = notInModules.find((p) => looksLikeMainPlan(p.parsed!))
                    ?? notInModules[0]
                    ?? withWorkflow[0];
                  const mainPath = mainCandidate?.path;

                  if (withWorkflow.length > 1) {
                    setFolderImportAllContents(contents);
                    setFolderImportCandidates(withWorkflow.map((p) => ({ path: p.path, content: p.content })));
                    setFolderImportSelectedPath(mainPath || withWorkflow[0]?.path || '');
                    setFolderImportOpen(true);
                    return;
                  }

                  setFolderImportAllContents(contents);
                  applyFolderImportSelection(mainPath);
                } catch (e) {
                  console.error('Error in findMainAndProcess:', e);
                  // Still try to update modules even if main graph fails
                  try {
                    const newUploaded = contents.map((c) => {
                      try {
                        const template = parseModuleYaml(c.content, c.path);
                        return { path: c.path, content: c.content, template };
                      } catch {
                        return {
                          path: c.path,
                          content: c.content,
                          template: {
                            name: c.path.split('/').pop()?.replace(/\.(yaml|yml)$/i, '') || 'Module',
                            path: c.path,
                            description: 'Failed to parse',
                            goal: '',
                            defaultParams: {},
                            workflow: [],
                          },
                        };
                      }
                    });
                    setTimeout(() => {
                      try {
                        setUploadedModules((prev) => {
                          const byPath = new Map(prev.map((m) => [m.path, m]));
                          newUploaded.forEach((u) => byPath.set(u.path, u));
                          return Array.from(byPath.values());
                        });
                      } catch (e2) {
                        console.error('Failed to update modules after error:', e2);
                      }
                    }, 100);
                  } catch (e2) {
                    console.error('Failed to update modules after error:', e2);
                  }
                }
              };
              
              // Start parsing batches
              parseBatch(0);
            } catch (e) {
              console.error('Error in processAsync:', e);
            }
          };
          
          // Start processing asynchronously
          try {
            if (typeof requestIdleCallback !== 'undefined') {
              requestIdleCallback(processAsync, { timeout: 100 });
            } else {
              setTimeout(processAsync, 0);
            }
          } catch (e) {
            console.error('Error scheduling processAsync:', e);
          }
        };
        
        // Start reading files
        readNextBatch();
      } catch (e) {
        console.error('Error in folder upload handler:', e);
        alert(`Failed to upload folder: ${e instanceof Error ? e.message : String(e)}`);
      }
    };
    input.click();
  }, [applyFolderImportSelection, applyYamlToGraph, onAutoLayout]);

  const onClear = useCallback(() => {
    if (window.confirm('Clear all nodes? (Modules in the library will be kept.)')) {
      setNodes((nds) => nds.filter((n) => n.type === 'start' || n.type === 'end'));
      setEdges([]);
      setSelectedNode(null);
      clearHistory();
    }
  }, [setNodes, setEdges, clearHistory]);

  const onRemoveModule = useCallback((modulePath: string) => {
    setUploadedModules((prev) => prev.filter((m) => m.path !== modulePath));
  }, []);

  const onClearModules = useCallback(() => {
    if (window.confirm('Clear all modules from library?')) {
      setUploadedModules([]);
    }
  }, []);

  const appendRunLog = useCallback((chunk: string) => {
    setRunLog((prev) => {
      const next = prev + chunk;
      // keep last ~200KB to avoid UI getting slow
      if (next.length > 200_000) return next.slice(next.length - 200_000);
      return next;
    });
  }, []);

  const scrollRunLogToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const container = runLogContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior });
  }, []);

  const isRunLogNearBottom = useCallback(() => {
    const container = runLogContainerRef.current;
    if (!container) return true;
    const threshold = 32;
    return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
  }, []);

  const splitArgs = useCallback((input: string): string[] => {
    const s = input.trim();
    if (!s) return [];
    const out: string[] = [];
    let cur = '';
    let quote: '"' | "'" | null = null;
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (quote) {
        if (ch === quote) {
          quote = null;
        } else if (ch === '\\' && i + 1 < s.length) {
          cur += s[i + 1];
          i += 1;
        } else {
          cur += ch;
        }
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch as '"' | "'";
        continue;
      }
      if (/\s/.test(ch)) {
        if (cur) out.push(cur);
        cur = '';
        continue;
      }
      cur += ch;
    }
    if (cur) out.push(cur);
    return out;
  }, []);

  const cleanupEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      try {
        eventSourceRef.current.close();
      } catch {
        // ignore
      }
      eventSourceRef.current = null;
    }
  }, []);

  const onRun = useCallback(async () => {
    if (yamlError) {
      setIsFollowingRunLog(true);
      setRunPanelOpen(true);
      setRunLog('');
      appendRunLog(`YAML has syntax errors. Please fix them before running.\n\n${yamlError}\n`);
      return;
    }

    cleanupEventSource();
    setIsFollowingRunLog(true);
    setRunPanelOpen(true);
    setRunLog('');
    setRunExitCode(null);
    setRunState('running');
    setDashboardUrl(null);
    setDashboardOpen(false);

    try {
      const args: string[] = [];
      if (runOptions.resume) args.push('--resume');
      if (runOptions.mcpUrl.trim()) args.push('--mcp_url', runOptions.mcpUrl.trim());
      if (runOptions.outputDir.trim()) args.push('--output_dir', runOptions.outputDir.trim());
      if (runOptions.checkpointPath.trim()) args.push('--checkpoint_path', runOptions.checkpointPath.trim());
      if (runOptions.tracePath.trim()) args.push('--trace_path', runOptions.tracePath.trim());
      if (runOptions.replayTrace.trim()) args.push('--replay_trace', runOptions.replayTrace.trim());

      // IMPORTANT: run_agent.sh only forwards unknown flags (like --model) WITHOUT their values
      // unless you use the --flag=value form. So we always use equals for python flags here.
      if (runOptions.model.trim()) args.push(`--model=${runOptions.model.trim()}`);
      if (runOptions.maxTokensPerStep.trim()) args.push(`--max_tokens_per_step=${runOptions.maxTokensPerStep.trim()}`);
      if (runOptions.maxToolCallsPerStep.trim()) args.push(`--max_tool_calls_per_step=${runOptions.maxToolCallsPerStep.trim()}`);
      if (runOptions.planRevisionMaxSteps.trim()) args.push(`--plan_revision_max_steps=${runOptions.planRevisionMaxSteps.trim()}`);
      args.push(...splitArgs(runOptions.extraArgs));

      const modulesRecord = Object.fromEntries(
        collectDependentModules(yaml, modulesByPath, nodesRef.current)
      );
      const res = await fetch('/api/run-agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          yaml,
          args,
          dashboard: runOptions.dashboard,
          ...(Object.keys(modulesRecord).length > 0 ? { modules: modulesRecord } : {}),
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        setRunState('exited');
        appendRunLog(`Failed to start run (${res.status}).\n${text}\n`);
        return;
      }
      const payload = (await res.json()) as { id: string; planPath?: string };
      setRunId(payload.id);
      appendRunLog(`Run started. id=${payload.id}\n`);
      if (payload.planPath) appendRunLog(`Plan saved to: ${payload.planPath}\n\n`);

      const es = new EventSource(`/api/run-agent/${payload.id}/stream`);
      eventSourceRef.current = es;

      es.addEventListener('status', (evt) => {
        try {
          const data = JSON.parse((evt as MessageEvent).data);
          if (typeof data?.dashboardUrl === 'string') {
            setDashboardUrl(data.dashboardUrl);
          }
          if (data?.state === 'exited') {
            setRunState('exited');
            setRunExitCode(typeof data?.exitCode === 'number' ? data.exitCode : null);
            cleanupEventSource();
          } else if (data?.state === 'running' || data?.state === 'starting') {
            setRunState('running');
          }
        } catch {
          // ignore
        }
      });

      es.addEventListener('log', (evt) => {
        try {
          const data = JSON.parse((evt as MessageEvent).data);
          if (typeof data?.chunk === 'string') appendRunLog(data.chunk);
        } catch {
          // ignore
        }
      });

      es.addEventListener('input_request', (evt) => {
        try {
          const data = JSON.parse((evt as MessageEvent).data) as any;
          const stepId = typeof data?.step_id === 'string' ? data.step_id : typeof data?.stepId === 'string' ? data.stepId : '';
          const prompt = typeof data?.prompt === 'string' ? data.prompt : '';
          const def = typeof data?.default === 'string' ? data.default : '';
          const saveAs = typeof data?.save_as === 'string' ? data.save_as : typeof data?.saveAs === 'string' ? data.saveAs : '';
          if (!stepId) return;
          setPendingInput({ runId: payload.id, stepId, prompt, default: def, saveAs });
          setPendingInputValue('');
          setPendingInputOpen(true);
          appendRunLog(`\n[ui] Input requested for step ${stepId}. Please answer in the popup.\n`);
        } catch {
          // ignore
        }
      });

      es.onerror = () => {
        appendRunLog('\n[ui] Log stream disconnected.\n');
        cleanupEventSource();
      };
    } catch (e) {
      setRunState('exited');
      appendRunLog(`Failed to start run.\n${String(e)}\n`);
      cleanupEventSource();
    }
  }, [appendRunLog, cleanupEventSource, modulesByPath, runOptions.dashboard, runOptions.extraArgs, runOptions.resume, splitArgs, yaml, yamlError]);

  const onStopRun = useCallback(async () => {
    if (!runId) return;
    try {
      await fetch(`/api/run-agent/${runId}/stop`, { method: 'POST' });
      appendRunLog('\n[ui] Stop requested.\n');
    } catch (e) {
      appendRunLog(`\n[ui] Failed to request stop: ${String(e)}\n`);
    }
  }, [appendRunLog, runId]);

  const onSubmitPendingInput = useCallback(async () => {
    if (!pendingInput) return;
    try {
      const value = pendingInputValue.trim() ? pendingInputValue : pendingInput.default;
      await fetch(`/api/run-agent/${pendingInput.runId}/input`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stepId: pendingInput.stepId, value }),
      });
      appendRunLog(`\n[ui] Submitted input for step ${pendingInput.stepId}.\n`);
      setPendingInput(null);
      setPendingInputValue('');
      setPendingInputOpen(false);
    } catch (e) {
      appendRunLog(`\n[ui] Failed to submit input: ${String(e)}\n`);
    }
  }, [appendRunLog, pendingInput, pendingInputValue]);

  const runLogHtml = useMemo(() => {
    // Re-create output from the full buffer to keep it deterministic
    // even if converter is streaming.
    const converter = new AnsiToHtml({
      fg: UI_TERMINAL_FG,
      bg: UI_TERMINAL_BG,
      colors: UI_TERMINAL_ANSI_COLORS,
      newline: false,
      escapeXML: true,
      stream: false,
    });
    return converter.toHtml(runLog);
  }, [runLog]);

  useEffect(() => {
    return () => {
      cleanupEventSource();
    };
  }, [cleanupEventSource]);

  useEffect(() => {
    if (!runPanelOpen || !isFollowingRunLog) return;
    requestAnimationFrame(() => {
      scrollRunLogToBottom();
    });
  }, [runLog, runPanelOpen, isFollowingRunLog, scrollRunLogToBottom]);

  const handleUpdateModuleContent = useCallback(
    (path: string, newContent: string) => {
      setUploadedModules((prev) => {
        const next: typeof prev = [];
        for (const m of prev) {
          if (m.path === path) {
            let template = m.template;
            try {
              template = parseModuleYaml(newContent, path);
            } catch {
              // keep previous template on parse failure
            }
            next.push({ path, content: newContent, template });
          } else {
            next.push(m);
          }
        }
        return next;
      });
    },
    [],
  );

  /** Write per-node module YAML override into a specific node's data.moduleContents. */
  const updateNodeModuleContent = useCallback(
    (nodeId: string, modulePath: string, newContent: string) => {
      setNodes((nds) =>
        nds.map((node) => {
          if (node.id !== nodeId) return node;
          const prev = (node.data as Record<string, unknown>).moduleContents as Record<string, string> | undefined;
          return {
            ...node,
            data: {
              ...node.data,
              moduleContents: { ...prev, [modulePath]: newContent },
            },
          };
        }),
      );
    },
    [setNodes],
  );

  /** Add a new module (e.g. created from built-in template) so it becomes editable. */
  const addModuleFromTemplate = useCallback((path: string, content: string) => {
    let template: ModuleTemplate;
    try {
      template = parseModuleYaml(content, path);
    } catch {
      template = {
        name: path.replace(/^.*[/\\]/, '').replace(/\.(yaml|yml)$/i, '') || 'Module',
        path,
        workflow: [],
      };
    }
    setUploadedModules((prev) => {
      if (prev.some((m) => m.path === path)) return prev;
      return [...prev, { path, content, template }];
    });
  }, []);

  // Setup callback for submodule step updates (per-node editing)
  // NOTE: wrap in `() => fn` so React stores the function as state, not as a functional updater.
  // Use refs (nodesRef, selectedSubmoduleStepRef) to always read latest values without
  // needing them in the dependency array (avoids recreation on every node move / selection change).
  useEffect(() => {
    setOnUpdateCallback(() => (parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => {
      if (modulePath == null || typeof modulePath !== 'string') return;

      // Resolve source YAML: check node's per-node moduleContents first, then global
      let sourceContent: string | undefined;
      const currentNodes = nodesRef.current;
      const parentNode = currentNodes.find((n) => n.id === parentNodeId);
      const nodeModuleContents = parentNode ? (parentNode.data as Record<string, unknown>).moduleContents as Record<string, string> | undefined : undefined;
      if (nodeModuleContents?.[modulePath]) {
        sourceContent = nodeModuleContents[modulePath];
      }

      if (!sourceContent) {
        // Lookup with normalization (same logic as SubmoduleInlineViewer.findGlobal)
        let entry = modulesByPath[modulePath];
        if (!entry) {
          const normalized = modulePath.replace(/^(\.\/|workflows[\\/])/, '');
          const keys = Object.keys(modulesByPath);
          const direct = keys.find((k) => k === normalized);
          if (direct) {
            entry = modulesByPath[direct];
          } else {
            const suffixMatch = keys.find((k) => k.endsWith(`/${normalized}`) || k.endsWith(`\\${normalized}`));
            if (suffixMatch) entry = modulesByPath[suffixMatch];
          }
        }
        if (entry) {
          sourceContent = entry.content;
        }
      }

      if (!sourceContent) {
        // If module not imported, try creating from built-in template so edits can persist
        const normalized = modulePath.replace(/^(\.\/|workflows[\\/])/, '');
        const predefined = PREDEFINED_MODULES.find(
          (m) => m.path === modulePath || m.path === normalized || m.path.endsWith(normalized),
        );
        if (predefined?.workflow?.length) {
          try {
            const yamlWorkflow = predefined.workflow.map((s) => ({
              step: { name: s.name, instruction: s.description ?? '' },
            })) as WorkflowStep[];
            const steps = workflowStepsToFlowNodeData(yamlWorkflow);
            const updatedSteps = steps.map((s, i) => (i === stepIndex ? { ...s, ...updates } : s));
            const initialContent = yamlLib.dump({
              name: predefined.name,
              workflow: yamlWorkflow,
            });
            const { yaml: newYaml } = updateModuleWorkflowYaml(initialContent, updatedSteps);
            // Store in per-node content and also add to global modules for fallback
            updateNodeModuleContent(parentNodeId, modulePath, newYaml);
            addModuleFromTemplate(modulePath, initialContent);
            const sel = selectedSubmoduleStepRef.current;
            if (sel?.modulePath === modulePath && sel?.stepIndex === stepIndex) {
              selectSubmoduleStep({
                modulePath,
                stepIndex,
                stepData: updatedSteps[stepIndex],
                parentNodeId,
              });
            }
            return;
          } catch (e) {
            console.error('Failed to create module from template:', e);
          }
        }
        return;
      }

      try {
        const parsed = yamlLib.load(sourceContent) as { workflow?: WorkflowStep[] } | null;
        if (!parsed || !Array.isArray(parsed.workflow)) return;

        const steps = workflowStepsToFlowNodeData(parsed.workflow as WorkflowStep[]);
        const updatedSteps = steps.map((s, i) => (i === stepIndex ? { ...s, ...updates } : s));
        const { yaml: newYaml } = updateModuleWorkflowYaml(sourceContent, updatedSteps);
        updateNodeModuleContent(parentNodeId, modulePath, newYaml);

        // Always update selection so the right panel reflects changes (controlled inputs)
        selectSubmoduleStep({
          modulePath,
          stepIndex,
          stepData: updatedSteps[stepIndex],
          parentNodeId,
        });
      } catch (e) {
        console.error('Failed to update submodule step:', e);
      }
    });
  }, [
    modulesByPath,
    updateNodeModuleContent,
    addModuleFromTemplate,
    selectSubmoduleStep,
    setOnUpdateCallback,
  ]);

  return (
    <ModulesContext.Provider value={{ modulesByPath, updateModuleContent: handleUpdateModuleContent, updateNodeModuleContent }}>
      <LayoutProvider triggerLayout={onAutoLayout} triggerLayoutOnly={onLayoutOnly}>
        <div className="w-full h-full flex flex-col">
      <Toolbar
        onAutoLayout={onAutoLayout}
        layoutDirection={layoutDirection}
        onLayoutDirectionChange={onLayoutDirectionChange}
        layoutCompact={layoutCompact}
        onLayoutCompactChange={setLayoutCompact}
        onExport={onExport}
        onExportFolder={onExportFolder}
        onExportImage={onExportImage}
        onImport={onImport}
        onImportSubmodules={onImportSubmodules}
        onImportFolder={onImportFolder}
        onClear={onClear}
        showYamlEditor={showYamlEditor}
        onToggleYamlEditor={() => setShowYamlEditor(!showYamlEditor)}
        onUndo={handleUndo}
        onRedo={handleRedo}
        canUndo={canUndo}
        canRedo={canRedo}
        onRun={onRun}
        runDisabled={runState === 'running' || !!yamlError || !yaml.trim()}
        runLabel={runState === 'running' ? 'Running' : 'Run'}
        runOptions={runOptions}
        onRunOptionsChange={(patch) => setRunOptions((prev) => ({ ...prev, ...patch }))}
        dashboardAvailable={!!dashboardUrl}
        onOpenDashboard={() => setDashboardOpen(true)}
        outputAvailable={!!runId || !!runLog}
        onOpenOutput={() => setRunPanelOpen((prev) => !prev)}
      />
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left Sidebar */}
        <div 
          className="border-r border-slate-200 bg-gradient-to-b from-slate-50 to-slate-100/60 px-3 py-4 flex flex-col flex-shrink-0 shadow-[inset_-1px_0_0_rgba(15,23,42,0.03)]"
          style={{ width: sidebarWidth }}
        >
          <Sidebar
            customModules={uploadedModules.map((u) => u.template)}
            selectedModule={selectedModule}
            onModuleSelect={onModuleSelect}
            onRemoveModule={onRemoveModule}
            onClearModules={onClearModules}
          />
        </div>
        
        {/* Left Resizer */}
        <Resizer direction="horizontal" onResize={handleSidebarResize} />
        
        {/* Main Canvas */}
        <div className="flex-1 relative" ref={reactFlowWrapper}>
          <LayoutDirectionProvider value={layoutDirection}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onInit={setReactFlowInstance}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onNodeClick={onNodeClick}
              onNodeDrag={onNodeDrag}
              onNodeDragStop={onNodeDragStop}
              onPaneClick={onPaneClick}
              nodeTypes={nodeTypes}
              fitView={false}
              zoomOnScroll={true}
              autoPanOnConnect={false}
              autoPanOnNodeDrag={false}
              snapToGrid
              snapGrid={[15, 15]}
              deleteKeyCode={['Backspace', 'Delete']}
              proOptions={{ hideAttribution: true }}
              defaultEdgeOptions={{
                type: 'default',
                animated: false,
                style: { stroke: '#b1b1b7', strokeWidth: 2 },
                markerEnd: {
                  type: MarkerType.ArrowClosed,
                  color: '#b1b1b7',
                },
              } as DefaultEdgeOptions}
            >
              {/* Ensure edge routing updates when handle positions change (TB <-> LR). */}
              <HandleInternalsSync
                nodeIds={nodes.map((n) => n.id)}
                direction={layoutDirection}
                updateNodeInternals={updateNodeInternals}
              />
              <Controls />
              <MiniMap 
                position="top-right"
                nodeColor={(node) => {
                  const config = NODE_CONFIGS[node.data?.nodeType as NodeType];
                  return config?.color || '#eee';
                }}
                maskColor="rgba(255, 255, 255, 0.5)"
                bgColor="rgba(240, 240, 240, 0.6)"
                style={{ width: 120, height: 90 }}
                nodeStrokeWidth={3}
                pannable
                zoomable
              />
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            </ReactFlow>
          </LayoutDirectionProvider>
        </div>
        
        {/* Right Resizer */}
        <Resizer direction="horizontal" onResize={handleRightPanelResize} />
        
        {/* Right Panel */}
        <div 
          className="border-l border-slate-200 bg-slate-50/80 overflow-y-auto flex-shrink-0"
          style={{ width: rightPanelWidth }}
        >
          <div className="h-full p-3">
            <div className="h-full rounded-2xl bg-white shadow-sm border border-slate-200/80 overflow-hidden">
              {showYamlEditor ? (
                <YamlEditor value={yaml} onChange={onYamlChange} error={yamlError} />
              ) : selectedSubmoduleStep ? (
                <SubmoduleStepConfigPanel
                  step={selectedSubmoduleStep.stepData}
                  onChange={(nextStep) => {
                    updateSubmoduleStep(selectedSubmoduleStep.parentNodeId, selectedSubmoduleStep.modulePath, selectedSubmoduleStep.stepIndex, nextStep);
                  }}
                />
              ) : selectedInnerStep ? (
                <InnerStepConfigPanel />
              ) : selectedNode ? (
                <NodeConfigPanel
                  node={selectedNode}
                  onChange={onNodeDataChange}
                  onDelete={onDeleteNode}
                />
              ) : selectedModule ? (
                <ModuleDetailPanel 
                  module={selectedModule} 
                  onClose={() => setSelectedModule(null)}
                />
              ) : (
                <div className="p-4 text-gray-600 text-sm">
                  <p className="font-semibold mb-2">Getting Started</p>
                  <ul className="space-y-1.5 text-xs list-disc list-inside">
                    <li>Drag nodes from the left sidebar onto the canvas</li>
                    <li>Connect nodes by dragging from one handle to another</li>
                    <li>Click a node to edit its properties</li>
                    <li>Click a module to view its details</li>
                    <li>Use the YAML button to view or edit raw YAML</li>
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {runPanelOpen && (
        <>
          <Resizer
            direction="vertical"
            className="ui-terminal-resizer"
            onResize={(delta) => {
              const min = 120;
              const max = Math.max(200, Math.floor(window.innerHeight * 0.8));
              // Dragging down (delta>0) should shrink terminal since its top moves down.
              setTerminalHeight((prev) => Math.max(min, Math.min(max, prev - delta)));
            }}
          />
          <div
            className="ui-terminal border-t border-gray-200 bg-[#0b0f17] text-gray-100 flex flex-col"
            style={{ height: terminalHeight }}
          >
            <div className="px-3 py-2 border-b border-gray-700 flex items-center gap-2">
              <div className="text-xs font-medium text-slate-200">
                Output
                {runState === 'running' ? ' (running)' : runExitCode !== null ? ` (exit ${runExitCode})` : ''}
              </div>
              <div className="flex-1" />
              {pendingInput && (
                <button
                  onClick={() => setPendingInputOpen(true)}
                  className="px-2 py-1 rounded text-xs bg-green-700 hover:bg-green-600 text-white"
                  title="User input required to continue this run"
                >
                  Input required
                </button>
              )}
              <button
                onClick={onStopRun}
                disabled={runState !== 'running' || !runId}
                className={`px-2 py-1 rounded text-xs flex items-center gap-1 ${
                  runState === 'running' && runId
                    ? 'bg-red-600 hover:bg-red-500 text-white'
                    : 'bg-gray-800 text-gray-500 cursor-not-allowed'
                }`}
                title="Stop the running process"
              >
                <Square size={14} />
                Stop
              </button>
              <button
                onClick={() => {
                  setRunPanelOpen(false);
                  setDashboardOpen(false);
                }}
                className="p-1 rounded hover:bg-gray-800 text-gray-200"
                title="Close"
              >
                <X size={16} />
              </button>
            </div>
            <div
              ref={runLogContainerRef}
              className="flex-1 overflow-auto"
              onScroll={() => {
                const nearBottom = isRunLogNearBottom();
                setIsFollowingRunLog((prev) => (prev === nearBottom ? prev : nearBottom));
              }}
            >
              <pre
                className="p-3 text-xs whitespace-pre-wrap font-mono leading-5"
                dangerouslySetInnerHTML={{
                  __html: runLog ? runLogHtml : 'No output yet.',
                }}
              />
            </div>
          </div>
        </>
      )}

      {dashboardOpen && (
        <div className="fixed inset-0 z-50 bg-black/40">
          <div className="absolute inset-0 p-4 flex">
            <div className="bg-white rounded-lg shadow-xl overflow-hidden flex flex-col w-full">
              <div className="h-10 border-b border-gray-200 bg-white flex items-center px-3 gap-2">
                <div className="text-sm font-medium text-gray-800">Dashboard</div>
                <div className="flex-1" />
                {dashboardUrl && (
                  <a
                    href={dashboardUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2 py-1 rounded text-xs border border-gray-200 hover:bg-gray-100 text-gray-700"
                    title={dashboardUrl}
                  >
                    Open in new tab
                  </a>
                )}
                <button
                  onClick={() => setDashboardOpen(false)}
                  className="p-1 rounded hover:bg-gray-100 text-gray-700"
                  title="Close"
                >
                  <X size={16} />
                </button>
              </div>
              {dashboardUrl ? (
                <iframe className="w-full flex-1 min-h-0 border-0" src={dashboardUrl} title="Dashboard" />
              ) : (
                <div className="p-4 text-sm text-gray-600">
                  Dashboard is not available yet. Enable <b>Start Dashboard</b> in Run options and run the agent.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {pendingInput && pendingInputOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-xl bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <div className="text-sm font-medium text-gray-800">User input required</div>
              <button
                onClick={() => {
                  setPendingInputOpen(false);
                }}
                className="px-2 py-1 text-sm rounded hover:bg-gray-100 text-gray-700"
                title="Close (run will remain waiting)"
              >
                Close
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-xs text-gray-500">
                step=<code className="font-mono">{pendingInput.stepId}</code>
                {pendingInput.saveAs ? (
                  <>
                    {' '}save_as=<code className="font-mono">{pendingInput.saveAs}</code>
                  </>
                ) : null}
              </div>
              <div className="text-sm text-gray-800 whitespace-pre-wrap">{pendingInput.prompt || 'Enter input:'}</div>
              <input
                autoFocus
                value={pendingInputValue}
                onChange={(e) => setPendingInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSubmitPendingInput();
                }}
                placeholder={pendingInput.default ? `Press Enter to use default: ${pendingInput.default}` : 'Type your answer'}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => {
                    setPendingInputOpen(false);
                  }}
                  className="px-3 py-1.5 text-sm rounded border border-gray-200 hover:bg-gray-50 text-gray-700"
                >
                  Cancel
                </button>
                <button
                  onClick={onSubmitPendingInput}
                  className="px-3 py-1.5 text-sm rounded bg-green-600 hover:bg-green-700 text-white"
                >
                  Submit
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {folderImportOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <div className="text-sm font-medium text-gray-800">Choose main YAML</div>
              <button
                onClick={() => {
                  setFolderImportOpen(false);
                  setFolderImportCandidates([]);
                  setFolderImportSelectedPath('');
                  setFolderImportAllContents([]);
                }}
                className="px-2 py-1 text-sm rounded hover:bg-gray-100 text-gray-700"
                title="Cancel folder import"
              >
                Close
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-sm text-gray-700">
                Multiple workflow YAML files were found in this folder. Choose which one should be opened as the main workflow.
              </div>
              <div className="max-h-72 overflow-auto border border-gray-200 rounded-md divide-y divide-gray-100">
                {folderImportCandidates.map((candidate) => (
                  <label key={candidate.path} className="flex items-start gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50">
                    <input
                      type="radio"
                      name="main-yaml-candidate"
                      value={candidate.path}
                      checked={folderImportSelectedPath === candidate.path}
                      onChange={() => setFolderImportSelectedPath(candidate.path)}
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <div className="text-sm text-gray-800 break-all">{candidate.path}</div>
                    </div>
                  </label>
                ))}
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => {
                    setFolderImportOpen(false);
                    setFolderImportCandidates([]);
                    setFolderImportSelectedPath('');
                    setFolderImportAllContents([]);
                  }}
                  className="px-3 py-1.5 text-sm rounded border border-gray-200 hover:bg-gray-50 text-gray-700"
                >
                  Cancel
                </button>
                <button
                  onClick={() => applyFolderImportSelection(folderImportSelectedPath)}
                  disabled={!folderImportSelectedPath}
                  className={`px-3 py-1.5 text-sm rounded ${
                    folderImportSelectedPath
                      ? 'bg-blue-600 hover:bg-blue-700 text-white'
                      : 'bg-gray-200 text-gray-500 cursor-not-allowed'
                  }`}
                >
                  Import selected YAML
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
        </div>
      </LayoutProvider>
    </ModulesContext.Provider>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <InnerStepProvider>
        <SubmoduleStepProvider>
          <FlowEditor />
        </SubmoduleStepProvider>
      </InnerStepProvider>
    </ReactFlowProvider>
  );
}
