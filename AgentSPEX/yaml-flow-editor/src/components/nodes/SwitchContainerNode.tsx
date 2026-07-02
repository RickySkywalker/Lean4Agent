import { memo, useState, useCallback } from 'react';
import { Handle, Position, NodeProps, useReactFlow } from '@xyflow/react';
import { NODE_CONFIGS, SwitchNodeData, FlowNodeData } from '../../types';
import { GitMerge, Plus, Trash2 } from 'lucide-react';
import { useInnerStep } from '../../contexts/InnerStepContext';
import { NestedStepRenderer } from './NestedStepRenderer';
import { getNestedItem, insertNestedItem, updateNestedStructure, adjustTargetPath } from '../../utils/flow-utils';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';

function SwitchContainerNode({ data, selected, id }: NodeProps) {
  const nodeData = data as SwitchNodeData & { 
    cases?: Record<string, FlowNodeData[]>;
    defaultSteps?: FlowNodeData[];
  };
  const config = NODE_CONFIGS['switch'];
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;
  const variable = nodeData.variable || 'variable';
  
  const { setNodes } = useReactFlow();
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  const [dragOverCase, setDragOverCase] = useState<string | null>(null);
  const [newCaseValue, setNewCaseValue] = useState('');

  const cases = nodeData.cases || {};
  const defaultSteps = nodeData.defaultSteps || [];
  const caseKeys = Object.keys(cases);

  const handleDragOver = useCallback((e: React.DragEvent, caseKey: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverCase(caseKey);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setDragOverCase(null);
  }, []);

  const handleMoveStep = useCallback((sourceBranch: string, sourceIndex: number, targetBranch: string, targetIndex: number, position: 'top' | 'bottom') => {
    // Clear stale selection — the step's branch/index is about to change
    selectInnerStep(null);
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const nodeData = node.data as Record<string, unknown>;

          const sourcePath = sourceBranch.split('.');
          const itemToMove = getNestedItem(nodeData, sourcePath, sourceIndex);
          if (!itemToMove) return node;

          // Guard: don't allow moving a step into its own subtree
          if (targetBranch.startsWith(`${sourceBranch}.${sourceIndex}.`)) {
            return node;
          }

          const dataWithoutItem = updateNestedStructure(nodeData, sourcePath, sourceIndex, null);

          let actualTargetIndex = targetIndex;
          if (sourceBranch === targetBranch && sourceIndex < targetIndex) {
            actualTargetIndex -= 1;
          }
          if (position === 'bottom') {
            actualTargetIndex += 1;
          }

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

  const handleDrop = useCallback((e: React.DragEvent, caseKey: string) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverCase(null);

    // Handle reordering/moving existing steps
    const reorderData = e.dataTransfer.getData('application/nested-reorder');
    if (reorderData) {
      try {
        const { index: srcIndex, branch: srcBranch } = JSON.parse(reorderData);
        const targetSteps = caseKey === '__default__' ? defaultSteps : (cases[caseKey] || []);
        // Move to end of the target case
        handleMoveStep(srcBranch, srcIndex, caseKey, targetSteps.length, 'top');
        return;
      } catch (err) {
        console.error('Move failed:', err);
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
    } else {
      newStep = { label: type === 'step' ? 'New Step' : type === 'task' ? 'New Task' : type, nodeType: type, name: type === 'step' ? 'new_step' : type === 'task' ? 'new_task' : undefined } as FlowNodeData;
    }

    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentData = node.data as typeof nodeData;
          if (caseKey === '__default__') {
            return {
              ...node,
              data: {
                ...node.data,
                defaultSteps: [...(currentData.defaultSteps || []), newStep],
              },
            };
          } else {
            const currentCases = currentData.cases || {};
            return {
              ...node,
              data: {
                ...node.data,
                cases: {
                  ...currentCases,
                  [caseKey]: [...(currentCases[caseKey] || []), newStep],
                },
              },
            };
          }
        }
        return node;
      })
    );
  }, [id, setNodes, cases, defaultSteps, handleMoveStep]);

  const addCase = useCallback(() => {
    if (!newCaseValue.trim()) return;
    
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentCases = (node.data as typeof nodeData).cases || {};
          return {
            ...node,
            data: {
              ...node.data,
              cases: {
                ...currentCases,
                [newCaseValue.trim()]: [],
              },
            },
          };
        }
        return node;
      })
    );
    setNewCaseValue('');
  }, [id, setNodes, newCaseValue]);

  const removeCase = useCallback((caseKey: string) => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentCases = { ...(node.data as typeof nodeData).cases };
          delete currentCases[caseKey];
          return {
            ...node,
            data: {
              ...node.data,
              cases: currentCases,
            },
          };
        }
        return node;
      })
    );
  }, [id, setNodes]);

  const removeStep = useCallback((caseKey: string, index: number) => {
    if (selectedInnerStep?.parentNodeId === id && 
        selectedInnerStep?.branch === caseKey && 
        selectedInnerStep?.stepIndex === index) {
      selectInnerStep(null);
    }
    
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentData = node.data as typeof nodeData;
          if (caseKey === '__default__') {
            return {
              ...node,
              data: {
                ...node.data,
                defaultSteps: (currentData.defaultSteps || []).filter((_, i) => i !== index),
              },
            };
          } else {
            const currentCases = currentData.cases || {};
            return {
              ...node,
              data: {
                ...node.data,
                cases: {
                  ...currentCases,
                  [caseKey]: (currentCases[caseKey] || []).filter((_, i) => i !== index),
                },
              },
            };
          }
        }
        return node;
      })
    );
  }, [id, setNodes, selectedInnerStep, selectInnerStep]);

  const updateStep = useCallback((caseKey: string, index: number, newStep: FlowNodeData) => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          const currentData = node.data as typeof nodeData;
          if (caseKey === '__default__') {
            const currentSteps = [...(currentData.defaultSteps || [])];
            currentSteps[index] = newStep;
            return {
              ...node,
              data: {
                ...node.data,
                defaultSteps: currentSteps,
              },
            };
          } else {
            const currentCases = currentData.cases || {};
            const currentSteps = [...(currentCases[caseKey] || [])];
            currentSteps[index] = newStep;
            return {
              ...node,
              data: {
                ...node.data,
                cases: {
                  ...currentCases,
                  [caseKey]: currentSteps,
                },
              },
            };
          }
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

  const handleReorder = useCallback((newSteps: FlowNodeData[], branchKey: string) => {
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === id) {
          if (branchKey === '__default__') {
            return {
              ...node,
              data: {
                ...node.data,
                defaultSteps: newSteps,
              },
            };
          } else {
            const currentCases = (node.data as typeof nodeData).cases || {};
            return {
              ...node,
              data: {
                ...node.data,
                cases: {
                  ...currentCases,
                  [branchKey]: newSteps,
                },
              },
            };
          }
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
        minWidth: 350,
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
            <GitMerge size={14} style={{ color: config.borderColor }} />
          </div>
          <div>
            <div className="text-xs font-semibold" style={{ color: config.borderColor }}>SWITCH</div>
            <div className="text-xs text-gray-600">on: {variable}</div>
          </div>
        </div>
      </div>

      {/* Add Case Input */}
      <div className="px-2 py-2 border-b flex gap-1" style={{ borderColor: config.borderColor + '20' }}>
        <input
          type="text"
          value={newCaseValue}
          onChange={(e) => setNewCaseValue(e.target.value)}
          placeholder="Add case value..."
          className="flex-1 text-xs px-2 py-1 border rounded"
          onKeyDown={(e) => e.key === 'Enter' && addCase()}
        />
        <button
          onClick={addCase}
          className="px-2 py-1 text-xs bg-orange-500 text-white rounded hover:bg-orange-600"
        >
          <Plus size={12} />
        </button>
      </div>

      {/* Cases */}
      <div className="p-2 space-y-2">
        {caseKeys.map((caseKey) => (
          <div
            key={caseKey}
            className={`rounded border-2 border-dashed min-h-[50px] p-2 transition-colors ${
              dragOverCase === caseKey ? 'border-orange-500 bg-orange-50' : 'border-orange-300 bg-orange-50/50'
            }`}
            data-branch={caseKey}
            onDragOver={(e) => handleDragOver(e, caseKey)}
            onDragLeave={handleDragLeave}
            onDrop={(e) => handleDrop(e, caseKey)}
          >
            <div className="flex items-center justify-between mb-1">
              <div className="text-xs font-semibold text-orange-600">
                case "{caseKey}" ({(cases[caseKey] || []).length})
              </div>
              <button
                onClick={() => removeCase(caseKey)}
                className="text-red-400 hover:text-red-600"
              >
                <Trash2 size={12} />
              </button>
            </div>
            <NestedStepRenderer
              steps={cases[caseKey] || []}
              parentNodeId={id}
              branch={caseKey}
              onStepClick={handleStepClick}
              onRemoveStep={removeStep}
              onUpdateStep={updateStep}
              onReorder={(newSteps) => handleReorder(newSteps, caseKey)}
              onMoveStep={handleMoveStep}
              isStepSelected={isStepSelected}
            />
            {(cases[caseKey] || []).length === 0 && (
              <div className="text-xs text-orange-400 flex items-center gap-1">
                <Plus size={10} /> Drop steps
              </div>
            )}
          </div>
        ))}

        {/* Default Case */}
        <div
          className={`rounded border-2 border-dashed min-h-[50px] p-2 transition-colors ${
            dragOverCase === '__default__' ? 'border-gray-500 bg-gray-100' : 'border-gray-300 bg-gray-50/50'
          }`}
          data-branch="__default__"
          onDragOver={(e) => handleDragOver(e, '__default__')}
          onDragLeave={handleDragLeave}
          onDrop={(e) => handleDrop(e, '__default__')}
        >
          <div className="text-xs font-semibold text-gray-600 mb-1">
            default ({defaultSteps.length})
          </div>
          <NestedStepRenderer
            steps={defaultSteps}
            parentNodeId={id}
            branch="__default__"
            onStepClick={handleStepClick}
            onRemoveStep={removeStep}
            onUpdateStep={updateStep}
            onReorder={(newSteps) => handleReorder(newSteps, '__default__')}
            onMoveStep={handleMoveStep}
            isStepSelected={isStepSelected}
          />
          {defaultSteps.length === 0 && (
            <div className="text-xs text-gray-400 flex items-center gap-1">
              <Plus size={10} /> Drop steps
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

export default memo(SwitchContainerNode);

