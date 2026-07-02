import React, { useCallback, useState } from 'react';
import { NODE_CONFIGS, FlowNodeData, IfNodeData, WhileNodeData, ForEachNodeData, SwitchNodeData, GatherNodeData, ParallelNodeData, CallNodeData, GatherCall } from '../../types';
import { GitBranch, RefreshCw, List, ChevronDown, ChevronRight, Plus, GitMerge, Layers, GitFork, Trash2, ExternalLink } from 'lucide-react';
import SubmoduleInlineViewer from '../SubmoduleInlineViewer';

interface NestedStepRendererProps {
  steps: FlowNodeData[];
  parentNodeId: string;
  branch: string;
  onStepClick: (step: FlowNodeData, index: number, branch: string, e: React.MouseEvent) => void;
  onRemoveStep: (branch: string, index: number) => void;
  onUpdateStep: (branch: string, index: number, newStep: FlowNodeData) => void;
  onReorder?: (newSteps: FlowNodeData[]) => void;
  onMoveStep?: (sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, position: 'top' | 'bottom') => void;
  isStepSelected: (branch: string, index: number) => boolean;
  depth?: number;
}

interface NestedContainerProps {
  step: FlowNodeData;
  index: number;
  parentNodeId: string;
  branch: string;
  onRemoveStep: (branch: string, index: number) => void;
  onUpdateStep: (branch: string, index: number, newStep: FlowNodeData) => void;
  isStepSelected: (branch: string, index: number) => boolean;
  onStepClick: (step: FlowNodeData, index: number, branch: string, e: React.MouseEvent) => void;
  onMoveStep?: (sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, position: 'top' | 'bottom') => void;
  depth: number;
}

// Helper to handle drag/drop reordering
const ReorderWrapper = ({
  children,
  index,
  branch,
  steps,
  parentNodeId,
  onReorder,
  onMoveStep
}: {
  children: React.ReactNode;
  index: number;
  branch: string;
  steps: FlowNodeData[];
  parentNodeId: string;
  onReorder?: (newSteps: FlowNodeData[]) => void;
  onMoveStep?: (sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, position: 'top' | 'bottom') => void;
}) => {
  const [isDragOver, setIsDragOver] = useState<'top' | 'bottom' | null>(null);

  const handleDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData('application/nested-reorder', JSON.stringify({ index, branch, parentNodeId, stepData: steps[index] }));
    e.dataTransfer.effectAllowed = 'move';
    e.stopPropagation();
  };

  const handleDragOver = (e: React.DragEvent) => {
    // Only handle reordering if we have the callback
    if (!onReorder && !onMoveStep) return;
    
    // Check if we are dragging a reorder item
    if (!e.dataTransfer.types.includes('application/nested-reorder')) return;
    
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';
    
    // Determine if we are hovering top or bottom half
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const mid = rect.top + rect.height / 2;
    setIsDragOver(e.clientY < mid ? 'top' : 'bottom');
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.stopPropagation();
    setIsDragOver(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!onReorder && !onMoveStep) return;
    const data = e.dataTransfer.getData('application/nested-reorder');
    if (!data) return;

    try {
      const { index: srcIndex, branch: srcBranch } = JSON.parse(data);
      
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(null);

      // Case 1: Cross-branch move
      if (srcBranch !== branch) {
        if (onMoveStep) {
          const position = isDragOver === 'top' ? 'top' : 'bottom';
          onMoveStep(srcBranch, srcIndex, branch, index, position);
        }
        return;
      }

      // Case 2: Same-branch reorder
      if (srcIndex === index) return;

      // Fallback to onReorder for same-list reordering if available
      if (onReorder) {
        const newSteps = [...steps];
        const [movedStep] = newSteps.splice(srcIndex, 1);
        
        // Insert at target
        const insertIndex = isDragOver === 'top' ? index : index + 1;
        const finalIndex = srcIndex < insertIndex ? insertIndex - 1 : insertIndex;
        
        newSteps.splice(finalIndex, 0, movedStep);
        onReorder(newSteps);
      } else if (onMoveStep) {
        // Also use onMoveStep for same-branch if onReorder not provided (though currently we use onReorder)
        const position = isDragOver === 'top' ? 'top' : 'bottom';
        onMoveStep(srcBranch, srcIndex, branch, index, position);
      }
      
    } catch (err) {
      console.error('Reorder failed', err);
    }
  };

  return (
    <div
      data-step-index={index}
      draggable={!!(onReorder || onMoveStep)}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`relative transition-all nodrag ${
        isDragOver === 'top' ? 'border-t-2 border-blue-500 pt-1' :
        isDragOver === 'bottom' ? 'border-b-2 border-blue-500 pb-1' : ''
      }`}
    >
      {children}
    </div>
  );
};

// Render a nested IF container
function NestedIfContainer({ step, index, parentNodeId, branch, onRemoveStep, onUpdateStep, isStepSelected, onStepClick, onMoveStep, depth }: NestedContainerProps) {
  const ifData = step as IfNodeData & { thenSteps?: FlowNodeData[]; elseSteps?: FlowNodeData[] };
  const [expanded, setExpanded] = useState(true);
  const [isDragOverTrue, setIsDragOverTrue] = useState(false);
  const [isDragOverFalse, setIsDragOverFalse] = useState(false);
  const config = NODE_CONFIGS['if'];
  const condition = ifData.condition || 'condition';
  const displayCondition = condition.length > 15 ? condition.substring(0, 15) + '...' : condition;

  const handleNestedStepClick = useCallback((nestedStep: FlowNodeData, nestedIndex: number, nestedBranch: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Pass through directly — the inner NestedStepRenderer already provides the full branch path
    onStepClick(nestedStep, nestedIndex, nestedBranch, e);
  }, [onStepClick]);

  const handleNestedRemove = useCallback((nestedBranch: string, nestedIndex: number) => {
    // Extract the actual branch from nested path
    const actualBranch = nestedBranch.split('.').pop() || nestedBranch;
    const key = actualBranch === 'then' ? 'thenSteps' : 'elseSteps';
    const currentSteps = ifData[key] || [];
    const newSteps = currentSteps.filter((_, i) => i !== nestedIndex);
    onUpdateStep(branch, index, {
      ...step,
      [key]: newSteps,
    });
  }, [step, branch, index, ifData, onUpdateStep]);

  const handleNestedUpdate = useCallback((nestedBranch: string, nestedIndex: number, newStep: FlowNodeData) => {
    const actualBranch = nestedBranch.split('.').pop() || nestedBranch;
    const key = actualBranch === 'then' ? 'thenSteps' : 'elseSteps';
    const currentSteps = ifData[key] || [];
    const newSteps = [...currentSteps];
    newSteps[nestedIndex] = newStep;
    onUpdateStep(branch, index, {
      ...step,
      [key]: newSteps,
    });
  }, [step, branch, index, ifData, onUpdateStep]);

  const handleDrop = useCallback((e: React.DragEvent, targetBranch: 'then' | 'else') => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOverTrue(false);
    setIsDragOverFalse(false);

    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData && onMoveStep) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        // Target branch must include parent path
        const fullTargetBranch = `${branch}.${index}.${targetBranch}`;
        
        // If dragging to container, append to end
        const currentTargetSteps = targetBranch === 'then' 
          ? (ifData.thenSteps || []) 
          : (ifData.elseSteps || []);
        
        onMoveStep(srcBranch, srcIndex, fullTargetBranch, currentTargetSteps.length, 'top');
        return;
      } catch (err) {
        console.error(err);
      }
    }

    const type = e.dataTransfer.getData('application/reactflow');
    if (!type) return;

    let newStep: FlowNodeData;
    if (type === 'if') {
      newStep = { label: 'If', nodeType: 'if', condition: 'condition', thenSteps: [], elseSteps: [] } as FlowNodeData;
    } else if (type === 'while') {
      newStep = { label: 'While', nodeType: 'while', condition: 'condition', loopSteps: [] } as FlowNodeData;
    } else if (type === 'for_each') {
      newStep = { label: 'For Each', nodeType: 'for_each', variable: 'item', in: [], loopSteps: [] } as FlowNodeData;
    } else if (type === 'switch') {
      newStep = { label: 'Switch', nodeType: 'switch', variable: 'variable', cases: {}, defaultSteps: [] } as FlowNodeData;
    } else if (type === 'gather') {
      newStep = { label: 'Gather', nodeType: 'gather', calls: [] } as FlowNodeData;
    } else if (type === 'parallel') {
      newStep = { label: 'Parallel', nodeType: 'parallel', module: '', parameters_list: [] } as FlowNodeData;
    } else if (type === 'input') {
      newStep = { label: 'Input', nodeType: 'input', prompt: '', save_as: 'user_input' } as FlowNodeData;
    } else if (type === 'return') {
      newStep = { label: 'Return', nodeType: 'return', variable: 'prev_output' } as FlowNodeData;
    } else if (type === 'increment') {
      newStep = { label: 'Increment', nodeType: 'increment', variable: 'counter' } as FlowNodeData;
    } else if (type === 'set_variable') {
      newStep = { label: 'Set Variable', nodeType: 'set_variable', name: 'variable', value: '' } as FlowNodeData;
    } else {
      newStep = { label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type, nodeType: type, name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined } as FlowNodeData;
    }

    const key = targetBranch === 'then' ? 'thenSteps' : 'elseSteps';
    const currentSteps = ifData[key] || [];
    onUpdateStep(branch, index, {
      ...step,
      [key]: [...currentSteps, newStep],
    });
  }, [step, branch, index, ifData, onUpdateStep, onMoveStep]);

  const handleReorder = useCallback((newSteps: FlowNodeData[], targetBranch: 'then' | 'else') => {
    const key = targetBranch === 'then' ? 'thenSteps' : 'elseSteps';
    onUpdateStep(branch, index, {
      ...step,
      [key]: newSteps,
    });
  }, [step, branch, index, onUpdateStep]);

  const thenSteps = ifData.thenSteps || [];
  const elseSteps = ifData.elseSteps || [];
  const isSelected = isStepSelected(branch, index);

  return (
    <div 
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
    >
      {/* Header */}
      <div 
        className="flex items-center gap-1 px-2 py-1 cursor-pointer"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <GitBranch size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>IF</span>
        <span className="text-xs text-gray-600 truncate">{displayCondition}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>

      {/* Branches */}
      {expanded && (
        <div className="flex gap-1 p-1">
          {/* True Branch */}
          <div
            className={`flex-1 rounded border border-dashed min-h-[30px] p-1 transition-colors ${
              isDragOverTrue ? 'border-green-500 bg-green-50' : 'border-green-300 bg-green-50/50'
            }`}
            data-branch={`${branch}.${index}.then`}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOverTrue(true); }}
            onDragLeave={(e) => { e.stopPropagation(); setIsDragOverTrue(false); }}
            onDrop={(e) => handleDrop(e, 'then')}
          >
            <div className="text-[10px] font-semibold text-green-600 mb-0.5">✓ True ({thenSteps.length})</div>
            <NestedStepRenderer
              steps={thenSteps}
              parentNodeId={parentNodeId}
              branch={`${branch}.${index}.then`}
              onStepClick={handleNestedStepClick}
              onRemoveStep={handleNestedRemove}
              onUpdateStep={handleNestedUpdate}
              onReorder={(newSteps) => handleReorder(newSteps, 'then')}
              onMoveStep={onMoveStep}
              isStepSelected={(b, i) => isStepSelected(b, i)}
              depth={depth + 1}
            />
            {thenSteps.length === 0 && (
              <div className="text-[10px] text-green-400 flex items-center gap-0.5">
                <Plus size={10} /> Drop
              </div>
            )}
          </div>

          {/* False Branch */}
          <div
            className={`flex-1 rounded border border-dashed min-h-[30px] p-1 transition-colors ${
              isDragOverFalse ? 'border-red-500 bg-red-50' : 'border-red-300 bg-red-50/50'
            }`}
            data-branch={`${branch}.${index}.else`}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOverFalse(true); }}
            onDragLeave={(e) => { e.stopPropagation(); setIsDragOverFalse(false); }}
            onDrop={(e) => handleDrop(e, 'else')}
          >
            <div className="text-[10px] font-semibold text-red-500 mb-0.5">✗ False ({elseSteps.length})</div>
            <NestedStepRenderer
              steps={elseSteps}
              parentNodeId={parentNodeId}
              branch={`${branch}.${index}.else`}
              onStepClick={handleNestedStepClick}
              onRemoveStep={handleNestedRemove}
              onUpdateStep={handleNestedUpdate}
              onReorder={(newSteps) => handleReorder(newSteps, 'else')}
              onMoveStep={onMoveStep}
              isStepSelected={(b, i) => isStepSelected(b, i)}
              depth={depth + 1}
            />
            {elseSteps.length === 0 && (
              <div className="text-[10px] text-red-400 flex items-center gap-0.5">
                <Plus size={10} /> Drop
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Render a nested WHILE container
function NestedWhileContainer({ step, index, parentNodeId, branch, onRemoveStep, onUpdateStep, isStepSelected, onStepClick, onMoveStep, depth }: NestedContainerProps) {
  const whileData = step as WhileNodeData & { loopSteps?: FlowNodeData[] };
  const [expanded, setExpanded] = useState(true);
  const [isDragOver, setIsDragOver] = useState(false);
  const config = NODE_CONFIGS['while'];
  const condition = whileData.condition || 'condition';
  const displayCondition = condition.length > 15 ? condition.substring(0, 15) + '...' : condition;

  const handleNestedStepClick = useCallback((nestedStep: FlowNodeData, nestedIndex: number, nestedBranch: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Pass through directly — the inner NestedStepRenderer already provides the full branch path
    onStepClick(nestedStep, nestedIndex, nestedBranch, e);
  }, [onStepClick]);

  const handleNestedRemove = useCallback((_nestedBranch: string, nestedIndex: number) => {
    const currentSteps = whileData.loopSteps || [];
    const newSteps = currentSteps.filter((_, i) => i !== nestedIndex);
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, whileData, onUpdateStep]);

  const handleNestedUpdate = useCallback((_nestedBranch: string, nestedIndex: number, newStep: FlowNodeData) => {
    const currentSteps = whileData.loopSteps || [];
    const newSteps = [...currentSteps];
    newSteps[nestedIndex] = newStep;
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, whileData, onUpdateStep]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData && onMoveStep) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        const fullTargetBranch = `${branch}.${index}.loop`;
        const currentLoopSteps = whileData.loopSteps || [];
        onMoveStep(srcBranch, srcIndex, fullTargetBranch, currentLoopSteps.length, 'top');
        return;
      } catch (err) {
        console.error(err);
      }
    }

    const type = e.dataTransfer.getData('application/reactflow');
    if (!type) return;

    let newStep: FlowNodeData;
    if (type === 'if') {
      newStep = { label: 'If', nodeType: 'if', condition: 'condition', thenSteps: [], elseSteps: [] } as FlowNodeData;
    } else if (type === 'while') {
      newStep = { label: 'While', nodeType: 'while', condition: 'condition', loopSteps: [] } as FlowNodeData;
    } else if (type === 'for_each') {
      newStep = { label: 'For Each', nodeType: 'for_each', variable: 'item', in: [], loopSteps: [] } as FlowNodeData;
    } else if (type === 'switch') {
      newStep = { label: 'Switch', nodeType: 'switch', variable: 'variable', cases: {}, defaultSteps: [] } as FlowNodeData;
    } else if (type === 'gather') {
      newStep = { label: 'Gather', nodeType: 'gather', calls: [] } as FlowNodeData;
    } else if (type === 'parallel') {
      newStep = { label: 'Parallel', nodeType: 'parallel', module: '', parameters_list: [] } as FlowNodeData;
    } else if (type === 'input') {
      newStep = { label: 'Input', nodeType: 'input', prompt: '', save_as: 'user_input' } as FlowNodeData;
    } else if (type === 'return') {
      newStep = { label: 'Return', nodeType: 'return', variable: 'prev_output' } as FlowNodeData;
    } else if (type === 'increment') {
      newStep = { label: 'Increment', nodeType: 'increment', variable: 'counter' } as FlowNodeData;
    } else if (type === 'set_variable') {
      newStep = { label: 'Set Variable', nodeType: 'set_variable', name: 'variable', value: '' } as FlowNodeData;
    } else {
      newStep = { label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type, nodeType: type, name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined } as FlowNodeData;
    }

    const currentSteps = whileData.loopSteps || [];
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: [...currentSteps, newStep],
    });
  }, [step, branch, index, whileData, onUpdateStep, onMoveStep]);

  const handleReorder = useCallback((newSteps: FlowNodeData[]) => {
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, onUpdateStep]);

  const loopSteps = whileData.loopSteps || [];
  const isSelected = isStepSelected(branch, index);

  return (
    <div 
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
    >
      {/* Header */}
      <div 
        className="flex items-center gap-1 px-2 py-1 cursor-pointer"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <RefreshCw size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>WHILE</span>
        <span className="text-xs text-gray-600 truncate">{displayCondition}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>

      {/* Loop Body */}
      {expanded && (
        <div
          className={`m-1 rounded border border-dashed min-h-[30px] p-1 transition-colors ${
            isDragOver ? 'border-purple-500 bg-purple-50' : 'border-purple-300 bg-purple-50/50'
          }`}
          data-branch={`${branch}.${index}.loop`}
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
          onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
          onDrop={handleDrop}
        >
          <div className="text-[10px] font-semibold text-purple-600 mb-0.5 flex items-center gap-0.5">
            <RefreshCw size={10} /> Loop ({loopSteps.length})
          </div>
          <NestedStepRenderer
            steps={loopSteps}
            parentNodeId={parentNodeId}
            branch={`${branch}.${index}.loop`}
            onStepClick={handleNestedStepClick}
            onRemoveStep={handleNestedRemove}
            onUpdateStep={handleNestedUpdate}
            onReorder={handleReorder}
            onMoveStep={onMoveStep}
            isStepSelected={(b, i) => isStepSelected(b, i)}
            depth={depth + 1}
          />
          {loopSteps.length === 0 && (
            <div className="text-[10px] text-purple-400 flex items-center gap-0.5">
              <Plus size={10} /> Drop steps
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Render a nested FOR_EACH container
function NestedForEachContainer({ step, index, parentNodeId, branch, onRemoveStep, onUpdateStep, isStepSelected, onStepClick, onMoveStep, depth }: NestedContainerProps) {
  const forEachData = step as ForEachNodeData & { loopSteps?: FlowNodeData[] };
  const [expanded, setExpanded] = useState(true);
  const [isDragOver, setIsDragOver] = useState(false);
  const config = NODE_CONFIGS['for_each'];
  const variable = forEachData.variable || 'item';

  const handleNestedStepClick = useCallback((nestedStep: FlowNodeData, nestedIndex: number, nestedBranch: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Pass through directly — the inner NestedStepRenderer already provides the full branch path
    onStepClick(nestedStep, nestedIndex, nestedBranch, e);
  }, [onStepClick]);

  const handleNestedRemove = useCallback((_nestedBranch: string, nestedIndex: number) => {
    const currentSteps = forEachData.loopSteps || [];
    const newSteps = currentSteps.filter((_, i) => i !== nestedIndex);
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, forEachData, onUpdateStep]);

  const handleNestedUpdate = useCallback((_nestedBranch: string, nestedIndex: number, newStep: FlowNodeData) => {
    const currentSteps = forEachData.loopSteps || [];
    const newSteps = [...currentSteps];
    newSteps[nestedIndex] = newStep;
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, forEachData, onUpdateStep]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData && onMoveStep) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        const fullTargetBranch = `${branch}.${index}.loop`;
        const currentLoopSteps = forEachData.loopSteps || [];
        onMoveStep(srcBranch, srcIndex, fullTargetBranch, currentLoopSteps.length, 'top');
        return;
      } catch (err) {
        console.error(err);
      }
    }

    const type = e.dataTransfer.getData('application/reactflow');
    if (!type) return;

    let newStep: FlowNodeData;
    if (type === 'if') {
      newStep = { label: 'If', nodeType: 'if', condition: 'condition', thenSteps: [], elseSteps: [] } as FlowNodeData;
    } else if (type === 'while') {
      newStep = { label: 'While', nodeType: 'while', condition: 'condition', loopSteps: [] } as FlowNodeData;
    } else if (type === 'for_each') {
      newStep = { label: 'For Each', nodeType: 'for_each', variable: 'item', in: [], loopSteps: [] } as FlowNodeData;
    } else if (type === 'switch') {
      newStep = { label: 'Switch', nodeType: 'switch', variable: 'variable', cases: {}, defaultSteps: [] } as FlowNodeData;
    } else if (type === 'gather') {
      newStep = { label: 'Gather', nodeType: 'gather', calls: [] } as FlowNodeData;
    } else if (type === 'parallel') {
      newStep = { label: 'Parallel', nodeType: 'parallel', module: '', parameters_list: [] } as FlowNodeData;
    } else if (type === 'input') {
      newStep = { label: 'Input', nodeType: 'input', prompt: '', save_as: 'user_input' } as FlowNodeData;
    } else if (type === 'return') {
      newStep = { label: 'Return', nodeType: 'return', variable: 'prev_output' } as FlowNodeData;
    } else if (type === 'increment') {
      newStep = { label: 'Increment', nodeType: 'increment', variable: 'counter' } as FlowNodeData;
    } else if (type === 'set_variable') {
      newStep = { label: 'Set Variable', nodeType: 'set_variable', name: 'variable', value: '' } as FlowNodeData;
    } else {
      newStep = { label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type, nodeType: type, name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined } as FlowNodeData;
    }

    const currentSteps = forEachData.loopSteps || [];
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: [...currentSteps, newStep],
    });
  }, [step, branch, index, forEachData, onUpdateStep, onMoveStep]);

  const handleReorder = useCallback((newSteps: FlowNodeData[]) => {
    onUpdateStep(branch, index, {
      ...step,
      loopSteps: newSteps,
    });
  }, [step, branch, index, onUpdateStep]);

  const loopSteps = forEachData.loopSteps || [];
  const isSelected = isStepSelected(branch, index);

  return (
    <div 
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
    >
      {/* Header */}
      <div 
        className="flex items-center gap-1 px-2 py-1 cursor-pointer"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <List size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>FOR</span>
        <span className="text-xs text-gray-600 truncate">{variable}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>

      {/* Loop Body */}
      {expanded && (
        <div
          className={`m-1 rounded border border-dashed min-h-[30px] p-1 transition-colors ${
            isDragOver ? 'border-orange-500 bg-orange-50' : 'border-orange-300 bg-orange-50/50'
          }`}
          data-branch={`${branch}.${index}.loop`}
          onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
          onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
          onDrop={handleDrop}
        >
          <div className="text-[10px] font-semibold text-orange-600 mb-0.5 flex items-center gap-0.5">
            <List size={10} /> Loop ({loopSteps.length})
          </div>
          <NestedStepRenderer
            steps={loopSteps}
            parentNodeId={parentNodeId}
            branch={`${branch}.${index}.loop`}
            onStepClick={handleNestedStepClick}
            onRemoveStep={handleNestedRemove}
            onUpdateStep={handleNestedUpdate}
            onReorder={handleReorder}
            onMoveStep={onMoveStep}
            isStepSelected={(b, i) => isStepSelected(b, i)}
            depth={depth + 1}
          />
          {loopSteps.length === 0 && (
            <div className="text-[10px] text-orange-400 flex items-center gap-0.5">
              <Plus size={10} /> Drop steps
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Render a nested SWITCH container
function NestedSwitchContainer({ step, index, parentNodeId, branch, onRemoveStep, onUpdateStep, isStepSelected, onStepClick, onMoveStep, depth }: NestedContainerProps) {
  const switchData = step as SwitchNodeData & { cases?: Record<string, FlowNodeData[]>; defaultSteps?: FlowNodeData[] };
  const [expanded, setExpanded] = useState(true);
  const [dragOverCase, setDragOverCase] = useState<string | null>(null);
  const [newCaseValue, setNewCaseValue] = useState('');
  const config = NODE_CONFIGS['switch'];
  const variable = switchData.variable || 'variable';
  
  const cases = switchData.cases || {};
  const defaultSteps = switchData.defaultSteps || [];
  const caseKeys = Object.keys(cases);

  const handleNestedStepClick = useCallback((nestedStep: FlowNodeData, nestedIndex: number, nestedBranch: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Pass through directly — the inner NestedStepRenderer already provides the full branch path
    onStepClick(nestedStep, nestedIndex, nestedBranch, e);
  }, [onStepClick]);

  const handleNestedRemove = useCallback((nestedBranch: string, nestedIndex: number) => {
    const actualBranch = nestedBranch.split('.').pop() || nestedBranch;

    if (actualBranch === '__default__') {
      const currentSteps = defaultSteps;
      const newSteps = currentSteps.filter((_, i) => i !== nestedIndex);
      onUpdateStep(branch, index, {
        ...step,
        defaultSteps: newSteps,
      });
    } else {
      const currentSteps = cases[actualBranch] || [];
      const newSteps = currentSteps.filter((_, i) => i !== nestedIndex);
      onUpdateStep(branch, index, {
        ...step,
        cases: {
          ...cases,
          [actualBranch]: newSteps,
        },
      });
    }
  }, [step, branch, index, cases, defaultSteps, onUpdateStep]);

  const handleNestedUpdate = useCallback((nestedBranch: string, nestedIndex: number, newStep: FlowNodeData) => {
    const actualBranch = nestedBranch.split('.').pop() || nestedBranch;
    
    if (actualBranch === '__default__') {
      const newSteps = [...defaultSteps];
      newSteps[nestedIndex] = newStep;
      onUpdateStep(branch, index, {
        ...step,
        defaultSteps: newSteps,
      });
    } else {
      const currentSteps = cases[actualBranch] || [];
      const newSteps = [...currentSteps];
      newSteps[nestedIndex] = newStep;
      onUpdateStep(branch, index, {
        ...step,
        cases: {
          ...cases,
          [actualBranch]: newSteps,
        },
      });
    }
  }, [step, branch, index, cases, defaultSteps, onUpdateStep]);

  const handleDrop = useCallback((e: React.DragEvent, targetCase: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverCase(null);

    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData && onMoveStep) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        const fullTargetBranch = `${branch}.${index}.${targetCase}`;
        const currentDefaultSteps = switchData.defaultSteps || [];
        const currentCases = switchData.cases || {};
        const targetSteps = targetCase === '__default__' ? currentDefaultSteps : (currentCases[targetCase] || []);
        onMoveStep(srcBranch, srcIndex, fullTargetBranch, targetSteps.length, 'top');
        return;
      } catch (err) {
        console.error(err);
      }
    }

    const type = e.dataTransfer.getData('application/reactflow');
    if (!type) return;

    let newStep: FlowNodeData;
    if (type === 'if') {
      newStep = { label: 'If', nodeType: 'if', condition: 'condition', thenSteps: [], elseSteps: [] } as FlowNodeData;
    } else if (type === 'while') {
      newStep = { label: 'While', nodeType: 'while', condition: 'condition', loopSteps: [] } as FlowNodeData;
    } else if (type === 'for_each') {
      newStep = { label: 'For Each', nodeType: 'for_each', variable: 'item', in: [], loopSteps: [] } as FlowNodeData;
    } else if (type === 'switch') {
      newStep = { label: 'Switch', nodeType: 'switch', variable: 'variable', cases: {}, defaultSteps: [] } as FlowNodeData;
    } else if (type === 'gather') {
      newStep = { label: 'Gather', nodeType: 'gather', calls: [] } as FlowNodeData;
    } else if (type === 'parallel') {
      newStep = { label: 'Parallel', nodeType: 'parallel', module: '', parameters_list: [] } as FlowNodeData;
    } else if (type === 'input') {
      newStep = { label: 'Input', nodeType: 'input', prompt: '', save_as: 'user_input' } as FlowNodeData;
    } else if (type === 'return') {
      newStep = { label: 'Return', nodeType: 'return', variable: 'prev_output' } as FlowNodeData;
    } else if (type === 'increment') {
      newStep = { label: 'Increment', nodeType: 'increment', variable: 'counter' } as FlowNodeData;
    } else if (type === 'set_variable') {
      newStep = { label: 'Set Variable', nodeType: 'set_variable', name: 'variable', value: '' } as FlowNodeData;
    } else {
      newStep = { label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type, nodeType: type, name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined } as FlowNodeData;
    }

    if (targetCase === '__default__') {
      onUpdateStep(branch, index, {
        ...step,
        defaultSteps: [...defaultSteps, newStep],
      });
    } else {
      const currentSteps = cases[targetCase] || [];
      onUpdateStep(branch, index, {
        ...step,
        cases: {
          ...cases,
          [targetCase]: [...currentSteps, newStep],
        },
      });
    }
  }, [step, branch, index, cases, defaultSteps, onUpdateStep, onMoveStep, switchData]);

  const addCase = useCallback(() => {
    if (!newCaseValue.trim()) return;
    onUpdateStep(branch, index, {
      ...step,
      cases: {
        ...cases,
        [newCaseValue.trim()]: [],
      },
    });
    setNewCaseValue('');
  }, [step, branch, index, cases, onUpdateStep, newCaseValue]);

  const removeCase = useCallback((caseKey: string) => {
    const newCases = { ...cases };
    delete newCases[caseKey];
    onUpdateStep(branch, index, {
      ...step,
      cases: newCases,
    });
  }, [step, branch, index, cases, onUpdateStep]);

  const handleReorder = useCallback((newSteps: FlowNodeData[], branchKey: string) => {
    if (branchKey === '__default__') {
      onUpdateStep(branch, index, {
        ...step,
        defaultSteps: newSteps,
      });
    } else {
      onUpdateStep(branch, index, {
        ...step,
        cases: {
          ...cases,
          [branchKey]: newSteps,
        },
      });
    }
  }, [step, branch, index, cases, onUpdateStep]);

  const isSelected = isStepSelected(branch, index);

  return (
    <div 
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
    >
      {/* Header */}
      <div 
        className="flex items-center gap-1 px-2 py-1 cursor-pointer"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <GitMerge size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>SWITCH</span>
        <span className="text-xs text-gray-600 truncate">{variable}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>

      {/* Body */}
      {expanded && (
        <div className="p-1 space-y-1">
          {/* Add Case */}
          <div className="flex gap-1 px-1">
            <input
              type="text"
              value={newCaseValue}
              onChange={(e) => setNewCaseValue(e.target.value)}
              placeholder="Case..."
              className="flex-1 text-[10px] px-1 py-0.5 border rounded"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.key === 'Enter' && addCase()}
            />
            <button
              onClick={(e) => { e.stopPropagation(); addCase(); }}
              className="px-1.5 py-0.5 text-[10px] bg-orange-500 text-white rounded hover:bg-orange-600"
            >
              <Plus size={10} />
            </button>
          </div>

          {/* Cases */}
          {caseKeys.map((caseKey) => (
            <div
              key={caseKey}
              className={`rounded border border-dashed min-h-[30px] p-1 transition-colors ${
                dragOverCase === caseKey ? 'border-orange-500 bg-orange-50' : 'border-orange-300 bg-orange-50/50'
              }`}
              data-branch={`${branch}.${index}.${caseKey}`}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragOverCase(caseKey); }}
              onDragLeave={(e) => { e.stopPropagation(); setDragOverCase(null); }}
              onDrop={(e) => handleDrop(e, caseKey)}
            >
              <div className="flex items-center justify-between mb-0.5">
                <div className="text-[10px] font-semibold text-orange-600">
                  case "{caseKey}" ({(cases[caseKey] || []).length})
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); removeCase(caseKey); }}
                  className="text-red-400 hover:text-red-600"
                >
                  <Trash2 size={10} />
                </button>
              </div>
              <NestedStepRenderer
                steps={cases[caseKey] || []}
                parentNodeId={parentNodeId}
                branch={`${branch}.${index}.${caseKey}`}
                onStepClick={handleNestedStepClick}
                onRemoveStep={handleNestedRemove}
                onUpdateStep={handleNestedUpdate}
                onReorder={(newSteps) => handleReorder(newSteps, caseKey)}
                onMoveStep={onMoveStep}
                isStepSelected={(b, i) => isStepSelected(b, i)}
                depth={depth + 1}
              />
              {(cases[caseKey] || []).length === 0 && (
                <div className="text-[10px] text-orange-400 flex items-center gap-0.5">
                  <Plus size={10} /> Drop
                </div>
              )}
            </div>
          ))}

          {/* Default */}
          <div
            className={`rounded border border-dashed min-h-[30px] p-1 transition-colors ${
              dragOverCase === '__default__' ? 'border-gray-500 bg-gray-100' : 'border-gray-300 bg-gray-50/50'
            }`}
            data-branch={`${branch}.${index}.__default__`}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragOverCase('__default__'); }}
            onDragLeave={(e) => { e.stopPropagation(); setDragOverCase(null); }}
            onDrop={(e) => handleDrop(e, '__default__')}
          >
            <div className="text-[10px] font-semibold text-gray-600 mb-0.5">default ({defaultSteps.length})</div>
            <NestedStepRenderer
              steps={defaultSteps}
              parentNodeId={parentNodeId}
              branch={`${branch}.${index}.__default__`}
              onStepClick={handleNestedStepClick}
              onRemoveStep={handleNestedRemove}
              onUpdateStep={handleNestedUpdate}
              onReorder={(newSteps) => handleReorder(newSteps, '__default__')}
              onMoveStep={onMoveStep}
              isStepSelected={(b, i) => isStepSelected(b, i)}
              depth={depth + 1}
            />
            {defaultSteps.length === 0 && (
              <div className="text-[10px] text-gray-400 flex items-center gap-0.5">
                <Plus size={10} /> Drop
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Render a nested GATHER container
function NestedGatherContainer({ step, index, parentNodeId, branch, onRemoveStep, onUpdateStep, isStepSelected, onStepClick }: NestedContainerProps) {
  const gatherData = step as GatherNodeData;
  const [expanded, setExpanded] = useState(true);
  const [isDragOver, setIsDragOver] = useState(false);
  const config = NODE_CONFIGS['gather'];
  const workers = gatherData.max_workers || 4;
  const calls = gatherData.calls || [];

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const moduleData = e.dataTransfer.getData('application/module');
    if (!moduleData) return;

    try {
      const module = JSON.parse(moduleData);
      const newCall: GatherCall = {
        module: module.path,
        parameters: module.defaultParams || {},
        save_as: `${module.name.toLowerCase().replace(/\s+/g, '_')}_result_${calls.length + 1}`,
      };
      
      onUpdateStep(branch, index, {
        ...step,
        calls: [...calls, newCall],
      });
    } catch (err) {
      console.error('Failed to parse module data:', err);
    }
  }, [step, branch, index, calls, onUpdateStep]);

  const removeCall = useCallback((callIndex: number) => {
    const newCalls = calls.filter((_, i) => i !== callIndex);
    onUpdateStep(branch, index, {
      ...step,
      calls: newCalls,
    });
  }, [step, branch, index, calls, onUpdateStep]);

  const isSelected = isStepSelected(branch, index);

  return (
    <div 
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
    >
      {/* Header */}
      <div 
        className="flex items-center gap-1 px-2 py-1 cursor-pointer"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Layers size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>GATHER</span>
        <span className="text-xs text-gray-600 truncate">{workers} workers</span>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>

      {/* Body */}
      {expanded && (
        <>
          <div 
            className={`m-1 rounded border border-dashed min-h-[30px] p-1 transition-colors ${
              isDragOver ? 'border-green-500 bg-green-50' : 'border-green-300 bg-green-50/50'
            }`}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
            onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
            onDrop={handleDrop}
          >
            <div className="text-[10px] font-semibold text-green-600 mb-0.5 flex items-center gap-0.5">
              <Layers size={10} /> Modules ({calls.length})
            </div>
            
            <div className="space-y-1">
              {calls.map((call, i) => (
                <div 
                  key={i} 
                  className="flex items-center gap-1 px-2 py-1 bg-white/50 rounded text-[10px] border border-green-200"
                >
                  <span className="truncate flex-1 font-medium">{call.module.split('/').pop()}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); removeCall(i); }}
                    className="text-red-400 hover:text-red-600"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))}
            </div>

            <div className="text-[10px] text-green-500 flex items-center gap-0.5 mt-1">
              <Plus size={10} /> Drop modules here
            </div>
          </div>
          {/* Format 2: same module + parameters_list */}
          {gatherData.module && (
            <div className="m-1">
              <SubmoduleInlineViewer modulePath={gatherData.module} parentNodeId={parentNodeId} depth={1} />
            </div>
          )}
          {/* Format 1: one submodule viewer per call for view/edit */}
          {calls.length > 0 && (
            <div className="m-1 space-y-2">
              {calls.map((call, i) => (
                <div key={i} className="rounded border border-slate-200 bg-slate-50/50 p-1.5">
                  <div className="text-[10px] font-medium text-slate-500 mb-1">
                    Worker {i + 1}: {call.module.split('/').pop() || call.module}
                  </div>
                  <SubmoduleInlineViewer
                    modulePath={call.module}
                    parentNodeId={parentNodeId}
                    depth={1}
                  />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Render a nested CALL container (view/edit called module)
function NestedCallContainer({
  step,
  index,
  parentNodeId,
  branch,
  onRemoveStep,
  onUpdateStep,
  isStepSelected,
  onStepClick,
  depth: _depth,
}: NestedContainerProps) {
  const callData = step as CallNodeData;
  const [isDragOver, setIsDragOver] = useState(false);
  const config = NODE_CONFIGS['call'];
  const modulePath = callData.module || '';

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const moduleData = e.dataTransfer.getData('application/module');
    if (!moduleData) return;

    try {
      const module = JSON.parse(moduleData);
      onUpdateStep(branch, index, {
        ...step,
        module: module.path,
        label: `Call: ${module.name}`,
        parameters: module.defaultParams || {},
      });
    } catch (err) {
      console.error('Failed to parse module data:', err);
    }
  }, [step, branch, index, onUpdateStep]);

  const isSelected = isStepSelected(branch, index);

  return (
    <div
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
      onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
      onDrop={handleDrop}
    >
      <div className="flex items-center gap-1 px-2 py-1 cursor-pointer">
        <ExternalLink size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>CALL</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-800 truncate font-medium">
            {modulePath ? modulePath.split('/').pop() : 'No module'}
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>
      {isDragOver && (
        <div className="text-[10px] text-sky-600 px-2 pb-1">Drop to set module</div>
      )}
      {modulePath && (
        <div className="px-2 pb-2">
          <SubmoduleInlineViewer modulePath={modulePath} parentNodeId={parentNodeId} depth={1} />
        </div>
      )}
    </div>
  );
}

// Render a nested PARALLEL container (Format 1: inline steps, Format 2: module+params)
function NestedParallelContainer({
  step,
  index,
  parentNodeId,
  branch,
  onRemoveStep,
  onUpdateStep,
  isStepSelected,
  onStepClick,
  onMoveStep,
  depth = 0,
}: NestedContainerProps) {
  const parallelData = step as ParallelNodeData & { parallelSteps?: FlowNodeData[] };
  const [isDragOver, setIsDragOver] = useState(false);
  const config = NODE_CONFIGS['parallel'];
  const isFormat1 = parallelData.parallelSteps && parallelData.parallelSteps.length > 0;
  const isSelected = isStepSelected(branch, index);

  // ── Format 2: module drop handler ────────────────────────────────
  const handleModuleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const moduleData = e.dataTransfer.getData('application/module');
    if (!moduleData) return;

    try {
      const moduleObj = JSON.parse(moduleData);
      const currentParams = parallelData.parameters_list || [];
      const newParams = currentParams.length === 0
        ? [moduleObj.defaultParams || {}]
        : currentParams;

      onUpdateStep(branch, index, {
        ...step,
        module: moduleObj.path,
        label: `Parallel: ${moduleObj.name}`,
        parameters_list: newParams,
      });
    } catch (err) {
      console.error('Failed to parse module data:', err);
    }
  }, [step, branch, index, parallelData, onUpdateStep]);

  // ── Format 1: inline steps ───────────────────────────────────────
  if (isFormat1) {
    const innerBranch = `${branch}.${index}.parallelSteps`;
    const pSteps = parallelData.parallelSteps!;

    return (
      <div
        className={`rounded-lg bg-white border shadow-sm ${
          isSelected ? 'ring-2 ring-blue-500 ring-offset-1' : ''
        }`}
        style={{ borderColor: config.borderColor }}
        onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
      >
        <div className="flex items-center gap-1 px-2 py-1 cursor-pointer">
          <GitFork size={12} style={{ color: config.borderColor }} />
          <span className="text-xs font-semibold" style={{ color: config.borderColor }}>PARALLEL</span>
          <span className="text-[10px] text-gray-500 ml-1">{pSteps.length} steps</span>
          <button
            onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
            className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
          >
            ×
          </button>
        </div>
        <div className="px-2 pb-2" data-branch={innerBranch}>
          <NestedStepRenderer
            steps={pSteps}
            parentNodeId={parentNodeId}
            branch={innerBranch}
            onStepClick={onStepClick}
            onRemoveStep={onRemoveStep}
            onUpdateStep={onUpdateStep}
            onReorder={() => {}}
            onMoveStep={onMoveStep || (() => {})}
            isStepSelected={isStepSelected}
            depth={(depth || 0) + 1}
          />
        </div>
      </div>
    );
  }

  // ── Format 2: module + parameter sets ────────────────────────────
  const module = parallelData.module;
  const paramsCount = Array.isArray(parallelData.parameters_list) ? parallelData.parameters_list.length : 0;

  return (
    <div
      className={`rounded-lg bg-white border shadow-sm transition-shadow ${
        isSelected ? 'ring-2 ring-blue-500 ring-offset-1 ring-offset-slate-50' : ''
      }`}
      style={{ borderColor: config.borderColor }}
      onClick={(e) => { e.stopPropagation(); onStepClick(step, index, branch, e); }}
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }}
      onDragLeave={(e) => { e.stopPropagation(); setIsDragOver(false); }}
      onDrop={handleModuleDrop}
    >
      <div className="flex items-center gap-1 px-2 py-1 cursor-pointer">
        <GitFork size={12} style={{ color: config.borderColor }} />
        <span className="text-xs font-semibold" style={{ color: config.borderColor }}>PARALLEL</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-800 truncate font-medium">{module ? module.split('/').pop() : 'No module'}</div>
          <div className="text-[10px] text-gray-500 truncate">{paramsCount} param sets</div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, index); }}
          className="ml-auto opacity-0 group-hover:opacity-100 hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
        >
          ×
        </button>
      </div>
      {isDragOver && (
        <div className="text-[10px] text-cyan-600 px-2 pb-1">Drop to set module</div>
      )}
      {module && (
        <div className="px-2 pb-2">
          <SubmoduleInlineViewer modulePath={module} parentNodeId={parentNodeId} depth={1} />
        </div>
      )}
    </div>
  );
}

// Main renderer for nested steps
export function NestedStepRenderer({
  steps,
  parentNodeId,
  branch,
  onStepClick,
  onRemoveStep,
  onUpdateStep,
  onReorder,
  onMoveStep,
  isStepSelected,
  depth = 0,
}: NestedStepRendererProps) {
  // Limit nesting depth to prevent infinite recursion
  if (depth > 5) {
    return <div className="text-[10px] text-gray-400">Max depth reached</div>;
  }

  return (
    <div className="space-y-1">
      {steps.map((step, i) => {
        const nodeType = step.nodeType;
        let content: React.ReactNode;

        // Render nested control flow containers
        if (nodeType === 'if') {
          content = (
            <NestedIfContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'while') {
          content = (
            <NestedWhileContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'for_each') {
          content = (
            <NestedForEachContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'switch') {
          content = (
            <NestedSwitchContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'gather') {
          content = (
            <NestedGatherContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'parallel') {
          content = (
            <NestedParallelContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              onMoveStep={onMoveStep}
              depth={depth}
            />
          );
        } else if (nodeType === 'call') {
          content = (
            <NestedCallContainer
              step={step}
              index={i}
              parentNodeId={parentNodeId}
              branch={branch}
              onRemoveStep={onRemoveStep}
              onUpdateStep={onUpdateStep}
              isStepSelected={isStepSelected}
              onStepClick={onStepClick}
              depth={depth}
            />
          );
        } else {
          // Render simple steps
          const stepConfig = NODE_CONFIGS[nodeType];
          const isSelected = isStepSelected(branch, i);
          
          content = (
            <div 
              onClick={(e) => onStepClick(step, i, branch, e)}
              className={`flex items-center gap-1 px-2 py-1.5 rounded text-xs group cursor-pointer transition-all ${
                isSelected ? 'ring-2 ring-blue-500 ring-offset-1' : 'hover:ring-1 hover:ring-gray-400'
              }`}
              style={{ backgroundColor: stepConfig?.color || '#f0f0f0' }}
            >
              <span className="truncate flex-1 font-medium" style={{ color: stepConfig?.borderColor }}>
                {step.label || nodeType}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onRemoveStep(branch, i); }}
                className="opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-700 text-sm font-bold"
              >
                ×
              </button>
            </div>
          );
        }

        return (
          <ReorderWrapper
            key={i}
            index={i}
            branch={branch}
            steps={steps}
            parentNodeId={parentNodeId}
            onReorder={onReorder}
            onMoveStep={onMoveStep}
          >
            {content}
          </ReorderWrapper>
        );
      })}
    </div>
  );
}

export default NestedStepRenderer;

