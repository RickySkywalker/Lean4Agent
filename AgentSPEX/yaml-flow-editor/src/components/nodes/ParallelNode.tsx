import { memo, useState, useCallback } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from '@xyflow/react';
import { GitFork, Plus } from 'lucide-react';
import { NODE_CONFIGS, ParallelNodeData, FlowNodeData } from '../../types';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';
import { useInnerStep } from '../../contexts/InnerStepContext';
import { NestedStepRenderer } from './NestedStepRenderer';
import { getNestedItem, insertNestedItem, updateNestedStructure, adjustTargetPath } from '../../utils/flow-utils';
import SubmoduleInlineViewer from '../SubmoduleInlineViewer';

/**
 * ParallelNode renders two formats:
 *  - Format 1 (inline steps):  parallelSteps[] displayed as a container with NestedStepRenderer
 *  - Format 2 (module+params): module name + SubmoduleInlineViewer (original behaviour)
 */
function ParallelNode({ data, selected, id }: NodeProps) {
  const parallelData = data as ParallelNodeData;
  const config = NODE_CONFIGS.parallel;
  const isFormat1 = parallelData.parallelSteps && parallelData.parallelSteps.length > 0;
  const paramsCount = Array.isArray(parallelData.parameters_list) ? parallelData.parameters_list.length : 0;

  const [isDragOver, setIsDragOver] = useState(false);
  const { setNodes } = useReactFlow();
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;

  const parallelSteps = parallelData.parallelSteps || [];

  // ── Drag-drop for Format 2 (module) ──────────────────────────────
  const handleModuleDragOver = useCallback((e: React.DragEvent) => {
    const moduleData = e.dataTransfer.getData('application/module');
    if (moduleData) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(true);
    }
  }, []);

  const handleModuleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleModuleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const moduleData = e.dataTransfer.getData('application/module');
    if (!moduleData) return;

    try {
      const module = JSON.parse(moduleData);
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id === id) {
            const currentParams = (node.data as ParallelNodeData).parameters_list || [];
            const newParams = currentParams.length === 0
              ? [module.defaultParams || {}]
              : currentParams;
            return {
              ...node,
              data: {
                ...node.data,
                module: module.path,
                label: `Parallel: ${module.name}`,
                parameters_list: newParams,
                parallelSteps: undefined, // switch to Format 2
                moduleContents: undefined,
              },
            };
          }
          return node;
        })
      );
    } catch (err) {
      console.error('Failed to parse module data:', err);
    }
  }, [id, setNodes]);

  // ── Container callbacks for Format 1 ─────────────────────────────
  const handleStepClick = useCallback(
    (step: FlowNodeData, index: number, branch: string, e: React.MouseEvent) => {
      e.stopPropagation();
      selectInnerStep({ parentNodeId: id, branch, stepIndex: index, stepData: step });
    },
    [id, selectInnerStep],
  );

  const handleRemoveStep = useCallback(
    (branch: string, index: number) => {
      selectInnerStep(null);
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== id) return node;
          const updated = updateNestedStructure(node.data as Record<string, unknown>, branch.split('.'), index, null);
          return { ...node, data: { ...node.data, ...updated } };
        }),
      );
    },
    [id, setNodes, selectInnerStep],
  );

  const handleUpdateStep = useCallback(
    (branch: string, index: number, newStep: FlowNodeData) => {
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== id) return node;
          const updated = updateNestedStructure(node.data as Record<string, unknown>, branch.split('.'), index, newStep);
          return { ...node, data: { ...node.data, ...updated } };
        }),
      );
    },
    [id, setNodes],
  );

  const handleReorder = useCallback(
    (newSteps: FlowNodeData[]) => {
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== id) return node;
          return { ...node, data: { ...node.data, parallelSteps: newSteps } };
        }),
      );
    },
    [id, setNodes],
  );

  const handleMoveStep = useCallback(
    (sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, _position: 'top' | 'bottom') => {
      selectInnerStep(null);
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== id) return node;
          const nd = node.data as Record<string, unknown>;
          const item = getNestedItem(nd, sourceBranch.split('.'), sourceIndex);
          if (!item) return node;
          if (targetBranch.startsWith(`${sourceBranch}.${sourceIndex}.`)) return node;
          const without = updateNestedStructure(nd, sourceBranch.split('.'), sourceIndex, null);
          let adjusted = targetIndex;
          if (sourceBranch === targetBranch && sourceIndex < targetIndex) adjusted -= 1;
          else {
            const adj = adjustTargetPath(sourceBranch, sourceIndex, targetBranch);
            if (typeof adj === 'number' && adj >= 0) adjusted = adj;
          }
          const withInsert = insertNestedItem(without, targetBranch.split('.'), adjusted, item);
          return { ...node, data: { ...node.data, ...withInsert } };
        }),
      );
    },
    [id, setNodes, selectInnerStep],
  );

  const isStepSelected = useCallback(
    (branch: string, index: number) =>
      selectedInnerStep?.parentNodeId === id &&
      selectedInnerStep?.branch === branch &&
      selectedInnerStep?.stepIndex === index,
    [id, selectedInnerStep],
  );

  const addStep = useCallback(() => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id !== id) return node;
        const current = ((node.data as ParallelNodeData).parallelSteps || []) as FlowNodeData[];
        const newStep: FlowNodeData = { label: 'New Task', nodeType: 'task', instruction: '' } as FlowNodeData;
        return { ...node, data: { ...node.data, parallelSteps: [...current, newStep] } };
      }),
    );
  }, [id, setNodes]);

  const handleContainerDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      const nodeType = e.dataTransfer.getData('application/reactflow');
      if (!nodeType || nodeType === 'start' || nodeType === 'end') return;

      const cfg = NODE_CONFIGS[nodeType as keyof typeof NODE_CONFIGS];
      if (!cfg) return;

      const newStep = { ...cfg.defaultData, label: cfg.defaultData.label || cfg.label } as FlowNodeData;
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id !== id) return node;
          const current = ((node.data as ParallelNodeData).parallelSteps || []) as FlowNodeData[];
          return { ...node, data: { ...node.data, parallelSteps: [...current, newStep] } };
        }),
      );
    },
    [id, setNodes],
  );

  // ── Format 1: container node with inline steps ───────────────────
  if (isFormat1) {
    return (
      <div>
        <div
          className={`rounded-xl overflow-hidden ${selected ? 'ring-2 ring-blue-500' : ''}`}
          style={{
            backgroundColor: '#ffffff',
            border: `2px solid ${config.borderColor}`,
            boxShadow: `0 8px 20px rgba(15,23,42,0.06)`,
            minWidth: 260,
          }}
        >
          <Handle type="target" position={targetPos} />

          {/* Header */}
          <div className="flex items-center gap-2 px-3 py-2" style={{ backgroundColor: config.color }}>
            <GitFork size={14} style={{ color: config.borderColor }} />
            <span className="text-xs font-bold" style={{ color: config.borderColor }}>PARALLEL</span>
            <span className="text-xs text-gray-600 ml-auto">{parallelSteps.length} steps</span>
          </div>

          {/* Body — steps branch */}
          <div
            className={`p-2 min-h-[40px] ${isDragOver ? 'bg-teal-50' : 'bg-gray-50'}`}
            data-branch="parallelSteps"
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
            onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
            onDrop={handleContainerDrop}
          >
            {parallelSteps.length > 0 ? (
              <NestedStepRenderer
                steps={parallelSteps}
                parentNodeId={id}
                branch="parallelSteps"
                onStepClick={handleStepClick}
                onRemoveStep={handleRemoveStep}
                onUpdateStep={handleUpdateStep}
                onReorder={handleReorder}
                onMoveStep={handleMoveStep}
                isStepSelected={isStepSelected}
                depth={0}
              />
            ) : (
              <div className="text-xs text-gray-400 text-center py-2">
                {isDragOver ? 'Drop step here' : 'Drag steps here or click + below'}
              </div>
            )}
          </div>

          {/* Add step button */}
          <div className="border-t px-2 py-1 flex justify-center">
            <button
              onClick={addStep}
              className="flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800"
            >
              <Plus size={12} /> Add Step
            </button>
          </div>

          <Handle type="source" position={sourcePos} />
        </div>
      </div>
    );
  }

  // ── Format 2: module + parameter sets (original) ─────────────────
  return (
    <div
      onDragOver={handleModuleDragOver}
      onDragLeave={handleModuleDragLeave}
      onDrop={handleModuleDrop}
      className={isDragOver ? 'ring-2 ring-cyan-500 ring-offset-2 rounded-lg' : ''}
    >
      <div
        className={`custom-node ${selected ? 'selected' : ''}`}
        style={{
          backgroundColor: '#ffffff',
          borderColor: config.borderColor,
          border: `1px solid ${config.borderColor}`,
          boxShadow: `0 8px 20px rgba(15,23,42,0.06), inset 0 3px 0 ${config.color}`,
        }}
      >
        <Handle type="target" position={targetPos} />
        <div className="flex items-center gap-2">
          <GitFork size={16} style={{ color: config.borderColor }} />
          <div>
            <div className="node-header">parallel</div>
            <div className="node-title">{parallelData.module || 'Drop module here'}</div>
            {paramsCount > 0 && (
              <div className="node-subtitle">{paramsCount} parameter sets</div>
            )}
            {isDragOver && (
              <div className="text-xs text-cyan-600 mt-1">Drop to set module</div>
            )}
          </div>
        </div>
        <Handle type="source" position={sourcePos} />
      </div>
      {parallelData.module && (
        <SubmoduleInlineViewer modulePath={parallelData.module} parentNodeId={id} depth={1} nodeModuleContents={parallelData.moduleContents} />
      )}
    </div>
  );
}

export default memo(ParallelNode);
