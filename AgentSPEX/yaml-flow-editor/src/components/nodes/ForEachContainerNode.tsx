import { memo, useState, useCallback } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from '@xyflow/react';
import { NODE_CONFIGS, ForEachNodeData, FlowNodeData } from '../../types';
import { List, Plus } from 'lucide-react';
import { useInnerStep } from '../../contexts/InnerStepContext';
import { NestedStepRenderer } from './NestedStepRenderer';
import { getNestedItem, insertNestedItem, updateNestedStructure, adjustTargetPath } from '../../utils/flow-utils';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';

function ForEachContainerNode({ data, selected, id }: NodeProps) {
  const nodeData = data as ForEachNodeData;
  const config = NODE_CONFIGS['for_each'];
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;
  const variable = nodeData.variable || 'item';
  const inSource = Array.isArray(nodeData.in) 
    ? `[${nodeData.in.length} items]` 
    : (nodeData.in || 'items');
  
  const { setNodes } = useReactFlow();
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  const [isDragOver, setIsDragOver] = useState(false);

  const loopSteps = nodeData.loopSteps || [];

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleMoveStep = useCallback((sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, position: 'top' | 'bottom') => {
    // Clear stale selection — the step's branch/index is about to change
    selectInnerStep(null);
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const nodeData = node.data as Record<string, unknown>;

          // 1. Get item
          const sourcePath = sourceBranch.split('.');
          const itemToMove = getNestedItem(nodeData, sourcePath, sourceIndex);

          if (!itemToMove) return node;

          // Guard: don't allow moving a step into its own subtree
          if (targetBranch.startsWith(`${sourceBranch}.${sourceIndex}.`)) {
            return node;
          }

          // 2. Remove from source
          const dataWithoutItem = updateNestedStructure(nodeData, sourcePath, sourceIndex, null);

          // 3. Calculate target index
          let actualTargetIndex = targetIndex;
          if (sourceBranch === targetBranch && sourceIndex < targetIndex) {
            actualTargetIndex -= 1;
          }
          if (position === 'bottom') {
            actualTargetIndex += 1;
          }

          // 4. Insert at target
          const adjustedTargetBranch = adjustTargetPath(sourceBranch, sourceIndex, targetBranch);
          const targetPath = adjustedTargetBranch.split('.');

          const finalData = insertNestedItem(dataWithoutItem, targetPath, actualTargetIndex, itemToMove);

          return {
            ...node,
            data: finalData,
          };
        }
        return node;
      })
    );
  }, [id, setNodes, selectInnerStep]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    // Handle reordering/moving existing steps
    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        // Move to end of loop
        handleMoveStep(srcBranch, srcIndex, 'loop', loopSteps.length, 'top');
        return;
      } catch (err) {
        console.error('Move failed:', err);
      }
    }

    const type = e.dataTransfer.getData('application/reactflow');
    if (!type) return;

    const moduleData = e.dataTransfer.getData('application/module');
    
    let newStep: FlowNodeData;
    if (moduleData) {
      const module = JSON.parse(moduleData);
      newStep = {
        label: `Call: ${module.name}`,
        nodeType: 'call',
        module: module.path,
        parameters: module.defaultParams || {},
      } as FlowNodeData;
    } else if (type === 'if') {
      newStep = {
        label: 'If',
        nodeType: 'if',
        condition: 'condition',
        thenSteps: [],
        elseSteps: [],
      } as FlowNodeData;
    } else if (type === 'while') {
      newStep = {
        label: 'While',
        nodeType: 'while',
        condition: 'condition',
        loopSteps: [],
      } as FlowNodeData;
    } else if (type === 'for_each') {
      newStep = {
        label: 'For Each',
        nodeType: 'for_each',
        variable: 'item',
        in: [],
        loopSteps: [],
      } as FlowNodeData;
    } else {
      newStep = {
        label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type,
        nodeType: type,
        name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined,
      } as FlowNodeData;
    }

    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentSteps = (node.data as typeof nodeData).loopSteps || [];
          return {
            ...node,
            data: {
              ...node.data,
              loopSteps: [...currentSteps, newStep],
            },
          };
        }
        return node;
      })
    );
  }, [id, setNodes, loopSteps, handleMoveStep]);

  const removeStep = useCallback((branch: string, index: number) => {
    if (selectedInnerStep?.parentNodeId === id && 
        selectedInnerStep?.branch === branch && 
        selectedInnerStep?.stepIndex === index) {
      selectInnerStep(null);
    }
    
    // Handle nested branch paths
    const parts = branch.split('.');
    if (parts[0] !== 'loop') return;
    
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentSteps = (node.data as typeof nodeData).loopSteps || [];
          
          if (parts.length === 1) {
            // Direct child removal
            return {
              ...node,
              data: {
                ...node.data,
                loopSteps: currentSteps.filter((_, i) => i !== index),
              },
            };
          }
          // For nested removals, the NestedStepRenderer handles it via onUpdateStep
          return node;
        }
        return node;
      })
    );
  }, [id, setNodes, selectedInnerStep, selectInnerStep]);

  const updateStep = useCallback((_branch: string, index: number, newStep: FlowNodeData) => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentSteps = [...((node.data as typeof nodeData).loopSteps || [])];
          currentSteps[index] = newStep;
          return {
            ...node,
            data: {
              ...node.data,
              loopSteps: currentSteps,
            },
          };
        }
        return node;
      })
    );
  }, [id, setNodes]);

  const handleStepClick = useCallback((step: FlowNodeData, index: number, branch: string, e: React.MouseEvent) => {
    e.stopPropagation();
    selectInnerStep({
      parentNodeId: id,
      branch,
      stepIndex: index,
      stepData: step,
    });
  }, [id, selectInnerStep]);

  const handleReorder = useCallback((newSteps: FlowNodeData[]) => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          return {
            ...node,
            data: {
              ...node.data,
              loopSteps: newSteps,
            },
          };
        }
        return node;
      })
    );
  }, [id, setNodes]);

  const isStepSelected = (branch: string, index: number) => {
    return selectedInnerStep?.parentNodeId === id && 
           selectedInnerStep?.branch === branch && 
           selectedInnerStep?.stepIndex === index;
  };

  return (
    <div
      className={`rounded-xl bg-white border shadow-sm hover:shadow-md transition-shadow ${
        selected ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-slate-50' : ''
      }`}
      style={{
        borderWidth: 1,
        borderStyle: 'solid',
        borderColor: config.borderColor,
        minWidth: 200,
        boxShadow: '0 10px 24px rgba(15,23,42,0.08)',
      }}
    >
      {/* Input Handle */}
      <Handle
        type="target"
        position={targetPos}
        className="!bg-gray-400 !w-2 !h-2"
      />

      {/* Header */}
      <div className="px-3 py-2 border-b" style={{ borderColor: config.borderColor + '40' }}>
        <div className="flex items-center gap-2">
          <div className="p-1 rounded" style={{ backgroundColor: `${config.borderColor}20` }}>
            <List size={14} style={{ color: config.borderColor }} />
          </div>
          <div>
            <div className="text-xs font-semibold" style={{ color: config.borderColor }}>FOR EACH</div>
            <div className="text-xs text-gray-600">
              <span className="font-mono">{variable}</span> in {inSource}
            </div>
            {nodeData.max_iterations && (
              <div className="text-xs text-gray-400">Max: {nodeData.max_iterations}</div>
            )}
          </div>
        </div>
      </div>

      {/* Loop Body */}
      <div
        className={`m-2 rounded border-2 border-dashed min-h-[60px] p-2 transition-colors ${
          isDragOver ? 'border-orange-500 bg-orange-50' : 'border-orange-300 bg-orange-50/50'
        }`}
        data-branch="loop"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="text-xs font-semibold text-orange-600 mb-1 flex items-center gap-1">
          <List size={12} />
          <span>Loop Body</span>
          {loopSteps.length > 0 && <span className="text-orange-400">({loopSteps.length})</span>}
        </div>
        <NestedStepRenderer
          steps={loopSteps}
          parentNodeId={id}
          branch="loop"
          onStepClick={handleStepClick}
          onRemoveStep={removeStep}
          onUpdateStep={updateStep}
          onReorder={handleReorder}
          onMoveStep={handleMoveStep}
          isStepSelected={isStepSelected}
        />
        {loopSteps.length === 0 && (
          <div className="text-xs text-orange-400 flex items-center gap-1">
            <Plus size={12} /> Drop steps here
          </div>
        )}
      </div>

      {/* Next Handle */}
      <div className="flex justify-center py-2">
        <span className="text-xs text-gray-500">Next →</span>
      </div>
      
      <Handle
        type="source"
        position={sourcePos}
        id="next"
        className="!bg-gray-400 !w-3 !h-3"
      />
    </div>
  );
}

export default memo(ForEachContainerNode);
