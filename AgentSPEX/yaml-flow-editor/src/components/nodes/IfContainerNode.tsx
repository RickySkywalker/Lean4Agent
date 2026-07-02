import { memo, useState, useCallback } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from '@xyflow/react';
import { NODE_CONFIGS, IfNodeData, FlowNodeData } from '../../types';
import { GitBranch, Plus } from 'lucide-react';
import { useInnerStep } from '../../contexts/InnerStepContext';
import { NestedStepRenderer } from './NestedStepRenderer';
import { getNestedItem, insertNestedItem, updateNestedStructure, adjustTargetPath } from '../../utils/flow-utils';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';

function IfContainerNode({ data, selected, id }: NodeProps) {
  const nodeData = data as IfNodeData;
  const config = NODE_CONFIGS['if'];
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;
  const condition = nodeData.condition || 'condition';
  const displayCondition = condition.length > 25 ? condition.substring(0, 25) + '...' : condition;
  
  const { setNodes } = useReactFlow();
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  const [isDragOverTrue, setIsDragOverTrue] = useState(false);
  const [isDragOverFalse, setIsDragOverFalse] = useState(false);

  const thenSteps = nodeData.thenSteps || [];
  const elseSteps = nodeData.elseSteps || [];

  const handleDragOver = useCallback((e: React.DragEvent, branch: 'then' | 'else') => {
    e.preventDefault();
    e.stopPropagation();
    if (branch === 'then') {
      setIsDragOverTrue(true);
    } else {
      setIsDragOverFalse(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent, branch: 'then' | 'else') => {
    e.stopPropagation();
    if (branch === 'then') {
      setIsDragOverTrue(false);
    } else {
      setIsDragOverFalse(false);
    }
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

          // 2. Remove from source (by updating with null)
          const dataWithoutItem = updateNestedStructure(nodeData, sourcePath, sourceIndex, null);
          
          // 3. Calculate target index
          let actualTargetIndex = targetIndex;
          
          if (sourceBranch === targetBranch && sourceIndex < targetIndex) {
            actualTargetIndex -= 1;
          }
          
          if (position === 'bottom') {
            actualTargetIndex += 1;
          }
          
          // 4. Insert at target (with potentially adjusted path)
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

  const handleDrop = useCallback((e: React.DragEvent, branch: 'then' | 'else') => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOverTrue(false);
    setIsDragOverFalse(false);

    // Handle reordering/moving existing steps
    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        const targetSteps = branch === 'then' ? thenSteps : elseSteps;
        // Move to end of the target branch
        handleMoveStep(srcBranch, srcIndex, branch, targetSteps.length, 'top');
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
          const currentSteps = branch === 'then' 
            ? (node.data as typeof nodeData).thenSteps || []
            : (node.data as typeof nodeData).elseSteps || [];
          return {
            ...node,
            data: {
              ...node.data,
              [branch === 'then' ? 'thenSteps' : 'elseSteps']: [...currentSteps, newStep],
            },
          };
        }
        return node;
      })
    );
  }, [id, setNodes, thenSteps, elseSteps, handleMoveStep]);

  const removeStep = useCallback((branch: string, index: number) => {
    // Clear selection if removing selected step
    if (selectedInnerStep?.parentNodeId === id && 
        selectedInnerStep?.branch === branch && 
        selectedInnerStep?.stepIndex === index) {
      selectInnerStep(null);
    }
    
    // Handle nested branch paths like "then.0.loop"
    const parts = branch.split('.');
    const topBranch = parts[0] as 'then' | 'else';
    
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const key = topBranch === 'then' ? 'thenSteps' : 'elseSteps';
          const currentSteps = (node.data as typeof nodeData)[key] || [];
          
          if (parts.length === 1) {
            // Direct child removal
            return {
              ...node,
              data: {
                ...node.data,
                [key]: currentSteps.filter((_, i) => i !== index),
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

  const updateStep = useCallback((branch: string, index: number, newStep: FlowNodeData) => {
    const parts = branch.split('.');
    const topBranch = parts[0] as 'then' | 'else';
    
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const key = topBranch === 'then' ? 'thenSteps' : 'elseSteps';
          const currentSteps = [...((node.data as typeof nodeData)[key] || [])];
          currentSteps[index] = newStep;
          return {
            ...node,
            data: {
              ...node.data,
              [key]: currentSteps,
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

  const handleReorder = useCallback((newSteps: FlowNodeData[], branch: 'then' | 'else') => {
    const key = branch === 'then' ? 'thenSteps' : 'elseSteps';
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          return {
            ...node,
            data: {
              ...node.data,
              [key]: newSteps,
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
        minWidth: 320,
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
            <GitBranch size={14} style={{ color: config.borderColor }} />
          </div>
          <div>
            <div className="text-xs font-semibold" style={{ color: config.borderColor }}>IF</div>
            <div className="text-xs text-gray-600">{displayCondition}</div>
          </div>
        </div>
      </div>

      {/* Branches Container */}
      <div className="flex gap-2 p-2">
        {/* True Branch */}
        <div 
          className={`flex-1 rounded border-2 border-dashed min-h-[60px] p-2 transition-colors ${
            isDragOverTrue ? 'border-green-500 bg-green-50' : 'border-green-300 bg-green-50/50'
          }`}
          data-branch="then"
          onDragOver={(e) => handleDragOver(e, 'then')}
          onDragLeave={(e) => handleDragLeave(e, 'then')}
          onDrop={(e) => handleDrop(e, 'then')}
        >
          <div className="text-xs font-semibold text-green-600 mb-1 flex items-center gap-1">
            <span>✓ True</span>
            {thenSteps.length > 0 && <span className="text-green-400">({thenSteps.length})</span>}
          </div>
          <NestedStepRenderer
            steps={thenSteps}
            parentNodeId={id}
            branch="then"
            onStepClick={handleStepClick}
            onRemoveStep={removeStep}
            onUpdateStep={updateStep}
            onReorder={(newSteps) => handleReorder(newSteps, 'then')}
            onMoveStep={handleMoveStep}
            isStepSelected={isStepSelected}
          />
          {thenSteps.length === 0 && (
            <div className="text-xs text-green-400 flex items-center gap-1">
              <Plus size={12} /> Drop steps here
            </div>
          )}
        </div>

        {/* False Branch */}
        <div 
          className={`flex-1 rounded border-2 border-dashed min-h-[60px] p-2 transition-colors ${
            isDragOverFalse ? 'border-red-500 bg-red-50' : 'border-red-300 bg-red-50/50'
          }`}
          data-branch="else"
          onDragOver={(e) => handleDragOver(e, 'else')}
          onDragLeave={(e) => handleDragLeave(e, 'else')}
          onDrop={(e) => handleDrop(e, 'else')}
        >
          <div className="text-xs font-semibold text-red-500 mb-1 flex items-center gap-1">
            <span>✗ False</span>
            {elseSteps.length > 0 && <span className="text-red-400">({elseSteps.length})</span>}
          </div>
          <NestedStepRenderer
            steps={elseSteps}
            parentNodeId={id}
            branch="else"
            onStepClick={handleStepClick}
            onRemoveStep={removeStep}
            onUpdateStep={updateStep}
            onReorder={(newSteps) => handleReorder(newSteps, 'else')}
            onMoveStep={handleMoveStep}
            isStepSelected={isStepSelected}
          />
          {elseSteps.length === 0 && (
            <div className="text-xs text-red-400 flex items-center gap-1">
              <Plus size={12} /> Drop steps here
            </div>
          )}
        </div>
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

export default memo(IfContainerNode);
