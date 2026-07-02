import { useEffect, useMemo, useState, useRef } from 'react';
import { useUpdateNodeInternals, useReactFlow, useNodesData } from '@xyflow/react';
import yaml from 'js-yaml';
import type { Workflow, FlowNodeData, ParallelNodeData, GatherNodeData, CallNodeData } from '../types';
import { useModules, UploadedModuleEntry } from '../contexts/ModulesContext';
import { updateModuleWorkflowYaml } from '../utils/moduleYaml';
import { workflowStepsToFlowNodeData } from '../utils/workflowStepConverters';
import { PREDEFINED_MODULES, ModuleTemplate, WorkflowStep as TemplateWorkflowStep } from './Sidebar';
import { useSubmoduleStep } from '../contexts/SubmoduleStepContext';
import { useLayout } from '../contexts/LayoutContext';
import { resolveOverlapsForNode, getNodeDimensions } from '../utils/layout';

/** Convert a template workflow step (from PREDEFINED_MODULES) to FlowNodeData for selection and config panel. */
function templateStepToFlowNodeData(s: TemplateWorkflowStep): FlowNodeData {
  const label = s.name || 'step';
  const nodeType = s.type as FlowNodeData['nodeType'];
  const base = { label, nodeType };
  if (s.type === 'step') {
    return { ...base, name: s.name || 'step', instruction: s.description ?? '' } as FlowNodeData;
  }
  if (s.type === 'if') return { ...base, condition: 'condition' } as FlowNodeData;
  if (s.type === 'while') return { ...base, condition: 'condition', max_iterations: 10 } as FlowNodeData;
  if (s.type === 'for_each') return { ...base, variable: 'item', in: '[]' } as FlowNodeData;
  if (s.type === 'switch') return { ...base, variable: 'variable' } as FlowNodeData;
  if (s.type === 'parallel') return { ...base, module: '', parameters_list: [] } as FlowNodeData;
  if (s.type === 'gather') return { ...base, calls: [], max_workers: 4 } as FlowNodeData;
  return base as FlowNodeData;
}

interface SubmoduleInlineViewerProps {
  modulePath: string;
  depth?: number; // Track nesting depth to prevent infinite recursion
  parentNodeId?: string; // ID of the parent node containing this submodule (for layout updates)
  nodeModuleContents?: Record<string, string>; // Per-node module YAML overrides
}

export default function SubmoduleInlineViewer({ modulePath, depth = 0, parentNodeId, nodeModuleContents }: SubmoduleInlineViewerProps) {
  // Prevent infinite recursion
  const MAX_DEPTH = 5;
  if (depth > MAX_DEPTH) {
    return (
      <div className="mt-2 rounded border border-slate-300 bg-slate-50 px-2 py-1 text-[10px] text-slate-500">
        Max nesting depth reached
      </div>
    );
  }
  const { modulesByPath, updateNodeModuleContent } = useModules();
  const { selectedSubmoduleStep, selectSubmoduleStep } = useSubmoduleStep();
  const { triggerLayout } = useLayout();
  const updateNodeInternals = useUpdateNodeInternals();
  const { getNodes, getEdges, setNodes } = useReactFlow();

  // Read parent node's moduleContents reactively from the store.
  // This handles the case where the prop isn't passed (e.g. SubmoduleInlineViewer
  // rendered inside NestedStepRenderer for container nodes).
  const storeNodeData = useNodesData(parentNodeId ?? '');
  const storeModuleContents = parentNodeId
    ? (storeNodeData as { data?: Record<string, unknown> } | null)?.data?.moduleContents as Record<string, string> | undefined
    : undefined;

  // Explicit prop takes priority; fall back to store-derived value
  const effectiveModuleContents = nodeModuleContents ?? storeModuleContents;

  const entry = useMemo(() => {
    // Helper to find global entry by path (exact, normalized, or suffix match)
    const findGlobal = (): UploadedModuleEntry | undefined => {
      if (modulesByPath[modulePath]) return modulesByPath[modulePath];
      const normalized = modulePath.replace(/^(\.\/|workflows[\\/])/, '');
      const keys = Object.keys(modulesByPath);
      const direct = keys.find((k) => k === normalized);
      if (direct) return modulesByPath[direct];
      const suffixMatch = keys.find((k) => k.endsWith(`/${normalized}`) || k.endsWith(`\\${normalized}`));
      return suffixMatch ? modulesByPath[suffixMatch] : undefined;
    };

    // Per-node override takes priority
    if (effectiveModuleContents?.[modulePath]) {
      const globalEntry = findGlobal();
      return {
        path: modulePath,
        content: effectiveModuleContents[modulePath],
        template: globalEntry?.template ?? { name: modulePath.split('/').pop() || modulePath, path: modulePath, workflow: [] },
      } as UploadedModuleEntry;
    }

    return findGlobal();
  }, [modulesByPath, modulePath, effectiveModuleContents]);

  const predefinedTemplate: ModuleTemplate | undefined = useMemo(
    () => PREDEFINED_MODULES.find((m) => m.path === modulePath),
    [modulePath],
  );
  const [collapsed, setCollapsed] = useState(true);
  const [steps, setSteps] = useState<FlowNodeData[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Track collapsed state to detect expansion/collapse transitions
  const prevCollapsedRef = useRef(collapsed);
  const overlapTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    // Cancel any pending overlap/layout timers from previous transitions
    overlapTimersRef.current.forEach(clearTimeout);
    overlapTimersRef.current = [];

    // For graph nodes (depth >= 1), update node internals and resolve overlaps when expanding
    // Only move overlapping nodes, not the expanded node itself
    if (depth >= 1) {
      const wasCollapsed = prevCollapsedRef.current;
      const isExpanding = wasCollapsed && !collapsed;

      // When expanding, update node internals and resolve overlaps
      if (isExpanding && parentNodeId) {
        // Use requestAnimationFrame to ensure DOM has updated
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            // Update node internals to measure new size
            updateNodeInternals(parentNodeId);

            // Run overlap resolution only for nodes in the same connected task flow
            const runOverlapResolution = () => {
              const allNodes = getNodes();
              const allEdges = getEdges();
              if (!allNodes || allNodes.length === 0) return;

              const nodeDimensions = new Map<string, { width: number; height: number }>();
              allNodes.forEach((node) => {
                const dim = getNodeDimensions(node as unknown as import('../types').FlowNode);
                nodeDimensions.set(node.id, dim);
              });

              const updatedNodes = resolveOverlapsForNode(
                allNodes as unknown as import('../types').FlowNode[],
                allEdges,
                parentNodeId,
                nodeDimensions
              );

              const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
              const hasChanges = updatedNodes.some((node) => {
                const original = nodeMap.get(node.id);
                if (!original) return false;
                return (
                  original.position.x !== node.position.x ||
                  original.position.y !== node.position.y
                );
              });

              if (hasChanges) {
                setNodes(updatedNodes);
              }
            };

            // Single pass after ReactFlow has updated measured dimensions
            const t = setTimeout(runOverlapResolution, 400);
            overlapTimersRef.current.push(t);
          });
        });
      }

      prevCollapsedRef.current = collapsed;
      return;
    }

    // Only trigger when transitioning from collapsed to expanded (for nested submodules with depth === 0)
    const wasCollapsed = prevCollapsedRef.current;
    const isExpanded = !collapsed;

    // Only do anything when transitioning from collapsed to expanded
    if (wasCollapsed && isExpanded) {
      // Update node internals to measure new size when expanded
      if (parentNodeId) {
        updateNodeInternals(parentNodeId);
      }
      // Trigger global layout for nested submodules (depth === 0)
      // Delay to allow DOM to update and ReactFlow to measure new size
      const timeoutId = setTimeout(() => {
        triggerLayout();
      }, 150);
      overlapTimersRef.current.push(timeoutId);
      prevCollapsedRef.current = collapsed;
      return;
    }

    // Update ref for next comparison
    prevCollapsedRef.current = collapsed;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsed]); // Only depend on collapsed, not on triggerLayout/updateNodeInternals to avoid unnecessary re-runs

  // Cleanup all pending timers on unmount
  useEffect(() => {
    return () => {
      overlapTimersRef.current.forEach(clearTimeout);
    };
  }, []);

  // Parse module workflow whenever the YAML content string changes.
  // Depend on the content string (not the entry object reference) so that
  // re-renders caused by a new moduleContents object with the same YAML text
  // (e.g. inline label edits which don't change the serialised YAML) don't
  // trigger a re-parse that would overwrite local-only state like labels.
  const entryContent = entry?.content;
  useEffect(() => {
    if (!entryContent) {
      // No uploaded YAML for this module – fall back to template-only (read-only) mode.
      setSteps([]);
      setError(null);
      return;
    }
    // Defer parsing to avoid blocking when many modules are loaded simultaneously
    const timeoutId = setTimeout(() => {
      try {
        const parsed = yaml.load(entryContent) as Workflow | null;
        if (!parsed || !Array.isArray(parsed.workflow)) {
          setSteps([]);
          setError('No workflow in submodule');
          return;
        }
        const flowSteps = workflowStepsToFlowNodeData(parsed.workflow);
        // Preserve UI-only labels from the current state: labels are not
        // serialised to YAML so a re-parse would overwrite any inline edits
        // with the name-derived default.  Only merge when the step count and
        // types still match (otherwise it's a structural change).
        setSteps((prev) => {
          if (prev.length === flowSteps.length) {
            return flowSteps.map((s, i) =>
              prev[i].nodeType === s.nodeType ? { ...s, label: prev[i].label } : s,
            );
          }
          return flowSteps;
        });
        setError(null);
        // Do NOT clear the current submodule-step selection here.
        // The selection is kept in sync by FlowEditor via updateSubmoduleStep.
      } catch (e) {
        setSteps([]);
        setError('Failed to parse submodule YAML');
      }
    }, 0);
    return () => clearTimeout(timeoutId);
  }, [entryContent, modulePath]);

  // Sync right-panel edits (including UI-only fields like label) back into
  // the local steps state.  The content-based re-parse effect above only
  // fires when the YAML string changes, but label is not serialised to YAML,
  // so right-panel label edits would otherwise be silently lost.
  useEffect(() => {
    if (
      !selectedSubmoduleStep ||
      selectedSubmoduleStep.modulePath !== modulePath ||
      selectedSubmoduleStep.parentNodeId !== parentNodeId
    ) return;

    const { stepIndex, stepData } = selectedSubmoduleStep;
    setSteps((prev) => {
      if (stepIndex >= prev.length) return prev;
      // Same reference → nothing to sync (avoids render loop)
      if (prev[stepIndex] === stepData) return prev;
      const next = [...prev];
      next[stepIndex] = stepData;
      return next;
    });
  }, [selectedSubmoduleStep, modulePath, parentNodeId]);

  void useMemo(() => {
    if (!steps.length) return 'No steps';
    if (steps.length === 1) return `1 step: ${steps[0].label || steps[0].nodeType}`;
    return `${steps.length} steps from submodule`;
  }, [steps]);

  const handleLabelChange = (index: number, label: string) => {
    if (!entry || !parentNodeId) return;
    const nextSteps = steps.map((s, i) => (i === index ? { ...s, label } : s));
    setSteps(nextSteps);

    // Push change into per-node module content (copy-on-write)
    const { yaml: newYaml } = updateModuleWorkflowYaml(entry.content, nextSteps);
    updateNodeModuleContent(parentNodeId, modulePath, newYaml);

    // Sync to right panel if this step is currently selected
    if (selectedSubmoduleStep?.modulePath === modulePath && selectedSubmoduleStep?.stepIndex === index) {
      selectSubmoduleStep({
        modulePath,
        stepIndex: index,
        stepData: nextSteps[index],
        parentNodeId,
      });
    }
  };

  const headerTitle = entry
    ? entry.template.name
    : predefinedTemplate
    ? predefinedTemplate.name
    : modulePath.split('/').pop() || modulePath;

  const templateSteps = predefinedTemplate?.workflow ?? [];

  return (
    <div 
      className="mt-2 rounded-lg border border-slate-200 bg-slate-50/80 p-2 nowheel"
      onClick={(e) => e.stopPropagation()} // Prevent clicks from bubbling to parent containers
    >
      <button
        type="button"
        className="flex w-full items-center gap-1 text-[11px] font-medium text-slate-600"
        onClick={(e) => {
          e.stopPropagation();
          setCollapsed((c) => !c);
        }}
      >
        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[9px] text-slate-700">
          {collapsed ? '▸' : '▾'}
        </span>
        <span className="truncate">Submodule: {headerTitle}</span>
      </button>
      {!collapsed && (
        <div className="mt-2 space-y-1 max-h-60 overflow-y-auto nowheel">
          {entry && error && (
            <div className="text-[10px] text-red-500">
              {error}
            </div>
          )}
          {entry && !error &&
            (steps.length ? (
              steps.map((step, idx) => {
                const parallelData = step.nodeType === 'parallel' ? (step as ParallelNodeData) : null;
                const gatherData = step.nodeType === 'gather' ? (step as GatherNodeData) : null;
                const callData = step.nodeType === 'call' ? (step as CallNodeData) : null;
                // Single-module nesting: parallel, gather (Format 2), or call
                const nestedModulePath = parallelData?.module || gatherData?.module || callData?.module || null;

                return (
                  <div key={idx} className="space-y-1">
                    <div
                      className={`flex items-center gap-2 rounded border bg-white px-2 py-1 text-[11px] cursor-pointer ${
                        selectedSubmoduleStep?.modulePath === modulePath && selectedSubmoduleStep?.stepIndex === idx
                          ? 'border-sky-400 ring-1 ring-sky-300'
                          : 'border-slate-200 hover:border-sky-300'
                      }`}
                      onClick={(e) => {
                        e.stopPropagation(); // Prevent event bubbling to parent containers
                        selectSubmoduleStep({
                          modulePath,
                          stepIndex: idx,
                          stepData: step,
                          parentNodeId: parentNodeId || '',
                        });
                      }}
                    >
                      <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-slate-100 text-[10px] text-slate-500">
                        {idx + 1}
                      </span>
                      <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-mono text-slate-600">
                        {step.nodeType}
                      </span>
                      <input
                        className="flex-1 rounded border border-slate-200 px-1 py-0.5 text-[11px] text-slate-800 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300"
                        value={step.label || ''}
                        onChange={(e) => handleLabelChange(idx, e.target.value)}
                        placeholder="Step label"
                        onClick={(e) => {
                          e.stopPropagation(); // Prevent event bubbling
                          selectSubmoduleStep({
                            modulePath,
                            stepIndex: idx,
                            stepData: step,
                            parentNodeId: parentNodeId || '',
                          });
                        }}
                        onFocus={(e) => {
                          e.stopPropagation(); // Prevent event bubbling when focusing input
                        }}
                      />
                    </div>
                    {/* Recursively render nested submodule: parallel / gather (Format 2) / call */}
                    {nestedModulePath && (
                      <div className="ml-4">
                        <SubmoduleInlineViewer modulePath={nestedModulePath} depth={depth + 1} parentNodeId={parentNodeId} nodeModuleContents={nodeModuleContents} />
                      </div>
                    )}
                    {/* Gather Format 1: one submodule viewer per call (worker) */}
                    {gatherData?.calls?.length ? (
                      <div className="ml-4 space-y-2">
                        {gatherData.calls.map((call, callIdx) => (
                          <div key={callIdx} className="rounded border border-slate-200 bg-slate-50/50 p-1.5">
                            <div className="text-[10px] font-medium text-slate-500 mb-1">
                              Worker {callIdx + 1}: {call.module.split('/').pop() || call.module}
                            </div>
                            <SubmoduleInlineViewer
                              modulePath={call.module}
                              depth={depth + 1}
                              parentNodeId={parentNodeId}
                              nodeModuleContents={nodeModuleContents}
                            />
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })
            ) : (
              <div className="text-[10px] text-slate-500">Submodule has no workflow steps.</div>
            ))}
          {!entry && templateSteps.length > 0 && (
            <div className="space-y-1">
              {templateSteps.map((s, idx) => {
                const stepData = templateStepToFlowNodeData(s);
                const isSelected =
                  selectedSubmoduleStep?.modulePath === modulePath && selectedSubmoduleStep?.stepIndex === idx;
                return (
                  <div
                    key={s.name ?? idx}
                    role="button"
                    tabIndex={0}
                    className={`flex items-center gap-2 rounded border bg-white px-2 py-1 text-[11px] cursor-pointer ${
                      isSelected ? 'border-sky-400 ring-1 ring-sky-300' : 'border-slate-200 hover:border-sky-300'
                    }`}
                    onClick={(e) => {
                      e.stopPropagation();
                      selectSubmoduleStep({
                        modulePath,
                        stepIndex: idx,
                        stepData,
                        parentNodeId: parentNodeId || '',
                      });
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        e.stopPropagation();
                        selectSubmoduleStep({ modulePath, stepIndex: idx, stepData, parentNodeId: parentNodeId || '' });
                      }
                    }}
                  >
                    <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-slate-100 text-[10px] text-slate-500">
                      {idx + 1}
                    </span>
                    <span className="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-mono text-slate-600">
                      {s.type}
                    </span>
                    <span className="flex-1 truncate text-[11px] text-slate-800">{s.name}</span>
                  </div>
                );
              })}
              <div className="pt-1 text-[10px] text-slate-400">
                This preview is based on the built-in module template. Import the module YAML or edit below to enable
                in-place editing.
              </div>
            </div>
          )}
          {!entry && !templateSteps.length && (
            <div className="text-[10px] text-slate-500">
              Submodule not found: <span className="font-mono">{modulePath}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

