import { useState, useEffect, useCallback } from 'react';
import { useReactFlow } from '@xyflow/react';
import { useInnerStep } from '../contexts/InnerStepContext';
import { FlowNodeData, NODE_CONFIGS, StepNodeData, CallNodeData, IfNodeData, WhileNodeData, ForEachNodeData, SwitchNodeData, IncrementNodeData, SetVariableNodeData, TaskNodeData, ParallelNodeData, GatherNodeData, GatherCall } from '../types';
import { Trash2, X, Plus } from 'lucide-react';
import yaml from 'js-yaml';
import { updateNestedStructure } from '../utils/flow-utils';

export default function InnerStepConfigPanel() {
  const { selectedInnerStep, selectInnerStep } = useInnerStep();
  const { setNodes } = useReactFlow();
  
  const [localData, setLocalData] = useState<FlowNodeData | null>(null);

  // Sync local data when selection changes
  useEffect(() => {
    if (selectedInnerStep) {
      setLocalData({ ...selectedInnerStep.stepData });
    } else {
      setLocalData(null);
    }
  }, [selectedInnerStep]);

  const updateStep = useCallback((updates: Partial<FlowNodeData>) => {
    if (!selectedInnerStep || !localData) return;

    const newData = { ...localData, ...updates };
    setLocalData(newData);

    // Update the parent node's data
    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === selectedInnerStep.parentNodeId) {
          const nodeData = node.data as Record<string, unknown>;
          const pathParts = selectedInnerStep.branch.split('.');
          
          // Use recursive helper to update deeply nested data
          const updatedNodeData = updateNestedStructure(
            nodeData,
            pathParts,
            selectedInnerStep.stepIndex,
            newData
          );
          
          return {
            ...node,
            data: updatedNodeData,
          };
        }
        return node;
      })
    );
  }, [selectedInnerStep, localData, setNodes]);

  const handleDelete = useCallback(() => {
    if (!selectedInnerStep) return;

    setNodes((nodes) =>
      nodes.map((node) => {
        if (node.id === selectedInnerStep.parentNodeId) {
          const nodeData = node.data as Record<string, unknown>;
          const pathParts = selectedInnerStep.branch.split('.');
          
          // Use recursive helper with null to trigger deletion
          const updatedNodeData = updateNestedStructure(
            nodeData,
            pathParts,
            selectedInnerStep.stepIndex,
            null
          );
          
          return {
            ...node,
            data: updatedNodeData,
          };
        }
        return node;
      })
    );
    
    selectInnerStep(null);
  }, [selectedInnerStep, setNodes, selectInnerStep]);

  if (!selectedInnerStep || !localData) {
    return null;
  }

  const stepConfig = NODE_CONFIGS[localData.nodeType as keyof typeof NODE_CONFIGS];
  const stepData = localData as StepNodeData;
  const callData = localData as CallNodeData;
  const ifData = localData as IfNodeData;
  const whileData = localData as WhileNodeData;
  const forEachData = localData as ForEachNodeData;
  const switchData = localData as SwitchNodeData;
  const inputData = localData as unknown as { prompt?: string; save_as?: string; default?: string };
  const returnData = localData as unknown as { variable?: string };
  const incrementData = localData as IncrementNodeData;
  const setVariableData = localData as SetVariableNodeData;
  const taskData = localData as TaskNodeData;
  const parallelData = localData as ParallelNodeData;
  const gatherData = localData as GatherNodeData;

  const toYamlString = (obj: Record<string, unknown>): string => {
    if (!obj || Object.keys(obj).length === 0) return '';
    try {
      return yaml.dump(obj, { 
        flowLevel: -1, 
        lineWidth: -1,
        quotingType: '"',
        forceQuotes: false,
      }).trim();
    } catch {
      return '';
    }
  };

  const parseYamlParams = (str: string): Record<string, unknown> | null => {
    if (!str.trim()) return {};
    try {
      const parsed = yaml.load(str);
      if (typeof parsed === 'object' && parsed !== null) {
        return parsed as Record<string, unknown>;
      }
      return null;
    } catch {
      return null;
    }
  };

  return (
    <div className="p-4 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div 
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: stepConfig?.borderColor || '#666' }}
          />
          <h3 className="font-semibold text-gray-800">
            {localData.nodeType === 'step' ? 'Step' : 
             localData.nodeType === 'call' ? 'Call Module' :
             localData.nodeType === 'input' ? 'Input' :
             localData.nodeType === 'return' ? 'Return' :
             localData.nodeType === 'increment' ? 'Increment' :
             localData.nodeType === 'set_variable' ? 'Set Variable' :
             localData.nodeType === 'parallel' ? 'Parallel' :
             localData.nodeType === 'gather' ? 'Gather' :
             localData.nodeType === 'task' ? 'Task' :
             localData.nodeType.charAt(0).toUpperCase() + localData.nodeType.slice(1)}
          </h3>
        </div>
        <button
          onClick={handleDelete}
          className="p-1.5 text-red-500 hover:bg-red-50 rounded"
          title="Delete step"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="space-y-4">
        {/* Common: Label */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Label</label>
          <input
            type="text"
            value={localData.label || ''}
            onChange={(e) => updateStep({ label: e.target.value })}
            className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Step-specific fields */}
        {localData.nodeType === 'step' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={stepData.name || ''}
                onChange={(e) => updateStep({ name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Instruction</label>
              <textarea
                value={stepData.instruction || ''}
                onChange={(e) => updateStep({ instruction: e.target.value })}
                rows={3}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save As</label>
              <input
                type="text"
                value={stepData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </>
        )}

        {/* Task-specific fields */}
        {localData.nodeType === 'task' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={taskData.name || ''}
                onChange={(e) => updateStep({ name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="task_name"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Instruction</label>
              <textarea
                value={taskData.instruction || ''}
                onChange={(e) => updateStep({ instruction: e.target.value })}
                rows={3}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Stateless instruction (fresh conversation each time)"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save As</label>
              <input
                type="text"
                value={taskData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="variable_name"
              />
            </div>
          </>
        )}

        {/* Call-specific fields */}
        {localData.nodeType === 'call' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Module Path</label>
              <input
                type="text"
                value={callData.module || ''}
                onChange={(e) => updateStep({ module: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="@modules/module_name.yaml"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Parameters (YAML)</label>
              <textarea
                value={toYamlString(callData.parameters || {})}
                onChange={(e) => {
                  const parsed = parseYamlParams(e.target.value);
                  if (parsed !== null) {
                    updateStep({ parameters: parsed });
                  }
                }}
                rows={4}
                className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="key: value"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save As</label>
              <input
                type="text"
                value={callData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </>
        )}

        {/* Input-specific fields */}
        {localData.nodeType === 'input' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Prompt</label>
              <textarea
                value={inputData.prompt || ''}
                onChange={(e) => updateStep({ prompt: e.target.value })}
                rows={2}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Question or prompt for the user"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save As</label>
              <input
                type="text"
                value={inputData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="user_input"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Default</label>
              <input
                type="text"
                value={inputData.default || ''}
                onChange={(e) => updateStep({ default: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="Default if non-interactive"
              />
            </div>
          </>
        )}

        {/* Return-specific fields */}
        {localData.nodeType === 'return' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Variable</label>
            <input
              type="text"
              value={returnData.variable || ''}
              onChange={(e) => updateStep({ variable: e.target.value })}
              className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              placeholder="prev_output"
            />
          </div>
        )}

        {/* Increment-specific fields */}
        {localData.nodeType === 'increment' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Variable</label>
            <input
              type="text"
              value={incrementData.variable || ''}
              onChange={(e) => updateStep({ variable: e.target.value })}
              className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              placeholder="counter"
            />
          </div>
        )}

        {/* Set Variable-specific fields */}
        {localData.nodeType === 'set_variable' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={setVariableData.name || ''}
                onChange={(e) => updateStep({ name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="variable"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Value</label>
              <input
                type="text"
                value={typeof setVariableData.value === 'string' ? setVariableData.value : String(setVariableData.value ?? '')}
                onChange={(e) => updateStep({ value: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="value or {{context_var}}"
              />
            </div>
          </>
        )}

        {/* If-specific fields */}
        {localData.nodeType === 'if' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Condition</label>
            <textarea
              value={ifData.condition || ''}
              onChange={(e) => updateStep({ condition: e.target.value })}
              rows={2}
              className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              placeholder="condition expression"
            />
          </div>
        )}

        {/* While-specific fields */}
        {localData.nodeType === 'while' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Condition</label>
              <textarea
                value={whileData.condition || ''}
                onChange={(e) => updateStep({ condition: e.target.value })}
                rows={2}
                className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="condition expression"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Iterations</label>
              <input
                type="number"
                value={whileData.max_iterations ?? ''}
                onChange={(e) => updateStep({ max_iterations: e.target.value === '' ? undefined : Number(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </>
        )}

        {/* ForEach-specific fields */}
        {localData.nodeType === 'for_each' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Variable</label>
              <input
                type="text"
                value={forEachData.variable || ''}
                onChange={(e) => updateStep({ variable: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="item"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">In (collection)</label>
              <input
                type="text"
                value={typeof forEachData.in === 'string' ? forEachData.in : JSON.stringify(forEachData.in || [])}
                onChange={(e) => updateStep({ in: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="collection_variable"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Iterations</label>
              <input
                type="number"
                value={forEachData.max_iterations ?? ''}
                onChange={(e) => updateStep({ max_iterations: e.target.value === '' ? undefined : Number(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </>
        )}

        {/* Switch-specific fields */}
        {localData.nodeType === 'switch' && (
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Variable</label>
            <input
              type="text"
              value={switchData.variable || ''}
              onChange={(e) => updateStep({ variable: e.target.value })}
              className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              placeholder="variable"
            />
          </div>
        )}

        {/* Parallel-specific fields (submodule info same as top-level node) */}
        {localData.nodeType === 'parallel' && (
          <>
            <div className="text-xs text-gray-500 mb-2">Run same module with different parameters</div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Module</label>
              <input
                type="text"
                value={parallelData.module || ''}
                onChange={(e) => updateStep({ module: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="path/to/module.yaml"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Workers</label>
              <input
                type="number"
                value={parallelData.max_workers ?? ''}
                onChange={(e) => updateStep({ max_workers: e.target.value === '' ? undefined : Number(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="4"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save Results As</label>
              <input
                type="text"
                value={parallelData.save_results_as || ''}
                onChange={(e) => updateStep({ save_results_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="results"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Parameters list (context variable or YAML array)</label>
              <textarea
                value={typeof parallelData.parameters_list === 'string'
                  ? parallelData.parameters_list
                  : (Array.isArray(parallelData.parameters_list) ? yaml.dump(parallelData.parameters_list, { indent: 2, lineWidth: -1 }).trim() : '')}
                onChange={(e) => {
                  const raw = e.target.value.trim();
                  if (!raw) {
                    updateStep({ parameters_list: [] });
                    return;
                  }
                  const parsed = yaml.load(raw);
                  if (Array.isArray(parsed)) {
                    updateStep({ parameters_list: parsed as Record<string, unknown>[] });
                  } else if (typeof parsed === 'string') {
                    updateStep({ parameters_list: parsed });
                  } else if (parsed && typeof parsed === 'object') {
                    updateStep({ parameters_list: [parsed as Record<string, unknown>] });
                  } else {
                    updateStep({ parameters_list: raw });
                  }
                }}
                rows={3}
                className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="user_query_params  or  - key: val"
              />
            </div>
          </>
        )}

        {/* Gather-specific fields (submodule info same as top-level node) */}
        {localData.nodeType === 'gather' && (
          <>
            <div className="text-xs text-gray-500 mb-2">Run different modules or same module with different parameters</div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Module (Format 2: same module)</label>
              <input
                type="text"
                value={gatherData.module || ''}
                onChange={(e) => updateStep({ module: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="path/to/module.yaml or leave empty for Format 1"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Max Workers</label>
              <input
                type="number"
                value={gatherData.max_workers ?? ''}
                onChange={(e) => updateStep({ max_workers: e.target.value === '' ? undefined : Number(e.target.value) })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="4"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Save Results As</label>
              <input
                type="text"
                value={gatherData.save_results_as || ''}
                onChange={(e) => updateStep({ save_results_as: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border rounded focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="results"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Parameters list (Format 2: context variable or YAML)</label>
              <textarea
                value={typeof gatherData.parameters_list === 'string'
                  ? gatherData.parameters_list
                  : (gatherData.parameters_list && Array.isArray(gatherData.parameters_list) ? yaml.dump(gatherData.parameters_list, { indent: 2, lineWidth: -1 }).trim() : '')}
                onChange={(e) => {
                  const raw = e.target.value.trim();
                  if (!raw) {
                    updateStep({ parameters_list: undefined });
                    return;
                  }
                  const parsed = yaml.load(raw);
                  if (Array.isArray(parsed)) {
                    updateStep({ parameters_list: parsed as Record<string, unknown>[] });
                  } else if (typeof parsed === 'string') {
                    updateStep({ parameters_list: parsed });
                  } else {
                    updateStep({ parameters_list: raw });
                  }
                }}
                rows={2}
                className="w-full px-2 py-1.5 text-sm border rounded font-mono focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                placeholder="serp_params or leave empty"
              />
            </div>
            <div className="pt-2 border-t border-gray-100">
              <label className="block text-xs font-medium text-gray-600 mb-1">Module Calls (Format 1)</label>
              <div className="space-y-2">
                {(gatherData.calls || []).map((call: GatherCall, index: number) => (
                  <div key={index} className="p-2 bg-white border border-gray-200 rounded text-xs">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-gray-500">Call {index + 1}</span>
                      <button type="button" onClick={() => updateStep({ calls: (gatherData.calls || []).filter((_, i) => i !== index) })} className="text-red-500 hover:text-red-700"><X size={12} /></button>
                    </div>
                    <input
                      type="text"
                      value={call.module || ''}
                      onChange={(e) => {
                        const next = [...(gatherData.calls || [])];
                        next[index] = { ...next[index], module: e.target.value };
                        updateStep({ calls: next });
                      }}
                      placeholder="module.yaml"
                      className="w-full px-2 py-1 border rounded mb-1"
                    />
                    <input
                      type="text"
                      value={call.save_as || ''}
                      onChange={(e) => {
                        const next = [...(gatherData.calls || [])];
                        next[index] = { ...next[index], save_as: e.target.value };
                        updateStep({ calls: next });
                      }}
                      placeholder="save_as"
                      className="w-full px-2 py-1 border rounded"
                    />
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => updateStep({ calls: [...(gatherData.calls || []), { module: '', parameters: {}, save_as: '' }] })}
                  className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-xs"
                >
                  <Plus size={12} /> Add Call
                </button>
              </div>
            </div>
          </>
        )}

        {/* Location Info */}
        <div className="pt-2 border-t">
          <p className="text-xs text-gray-400">
            In: {selectedInnerStep.branch === 'then' ? 'True Branch' : 
                 selectedInnerStep.branch === 'else' ? 'False Branch' : 
                 'Loop Body'} (#{selectedInnerStep.stepIndex + 1})
          </p>
          <p className="text-xs text-gray-400">
            Parent: {selectedInnerStep.parentNodeId}
          </p>
        </div>
      </div>
    </div>
  );
}

