import { useState, useEffect, useCallback } from 'react';
import yaml from 'js-yaml';
import { FlowNode, FlowNodeData, NODE_CONFIGS, NodeType, GatherCall, GatherNodeData, ParallelNodeData } from '../types';
import { Trash2, Plus, X } from 'lucide-react';

// Helper to convert object to YAML string (for display)
const toYamlString = (obj: unknown): string => {
  if (obj === null || obj === undefined) {
    return '';
  }
  if (typeof obj === 'object' && Object.keys(obj).length === 0) {
    return '';
  }
  try {
    // Convert null/undefined values to empty strings to preserve keys
    const normalized = Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([key, value]) => [
        key,
        value === null || value === undefined ? '' : value
      ])
    );
    return yaml.dump(normalized, { 
      indent: 2, 
      lineWidth: -1,
      skipInvalid: false,
      forceQuotes: true,  // Force quotes to preserve empty strings
    }).trim();
  } catch {
    return '';
  }
};

// Helper to parse YAML string to object
const parseYamlParams = (str: string): Record<string, unknown> | null => {
  if (!str.trim()) return {};
  try {
    const parsed = yaml.load(str);
    if (typeof parsed === 'object' && parsed !== null) {
      // Convert null values to empty strings to preserve keys
      const result: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        result[key] = value === null || value === undefined ? '' : value;
      }
      return result;
    }
    return null;
  } catch {
    return null;
  }
};

// YAML Parameters Editor with local state for smooth editing
function YamlParamsEditor({
  value,
  onChange,
  placeholder,
  label = 'Parameters (YAML)',
}: {
  value: Record<string, unknown> | undefined;
  onChange: (params: Record<string, unknown>) => void;
  placeholder?: string;
  label?: string;
}) {
  const [localValue, setLocalValue] = useState(() => toYamlString(value));
  const [isValid, setIsValid] = useState(true);

  // Sync local state when external value changes (e.g., node selection change)
  useEffect(() => {
    setLocalValue(toYamlString(value));
    setIsValid(true);
  }, [value]);

  const handleChange = useCallback((text: string) => {
    setLocalValue(text);
    // Validate but don't save yet
    const parsed = parseYamlParams(text);
    setIsValid(parsed !== null);
  }, []);

  const handleBlur = useCallback(() => {
    // Only save when valid
    const parsed = parseYamlParams(localValue);
    if (parsed !== null) {
      onChange(parsed);
    }
  }, [localValue, onChange]);

  return (
    <div className="mb-4">
      <label className="block text-xs font-medium text-gray-600 mb-1">
        {label}
      </label>
      <textarea
        value={localValue}
        onChange={(e) => handleChange(e.target.value)}
        onBlur={handleBlur}
        placeholder={placeholder}
        className={`w-full px-3 py-2 border rounded-md text-sm font-mono resize-y min-h-[100px] focus:outline-none focus:ring-2 focus:border-transparent ${
          isValid 
            ? 'border-gray-200 focus:ring-blue-500' 
            : 'border-red-300 focus:ring-red-500 bg-red-50'
        }`}
      />
      <div className="text-xs mt-1 flex justify-between">
        <span className="text-gray-400">Enter parameters in YAML format</span>
        {!isValid && <span className="text-red-500">Invalid YAML</span>}
      </div>
    </div>
  );
}

interface NodeConfigPanelProps {
  node: FlowNode;
  onChange: (nodeId: string, data: Partial<FlowNodeData>) => void;
  onDelete: (nodeId: string) => void;
}

export default function NodeConfigPanel({
  node,
  onChange,
  onDelete,
}: NodeConfigPanelProps) {
  const config = NODE_CONFIGS[node.data.nodeType as NodeType];
  const isProtected = node.type === 'start' || node.type === 'end';

  /** Typed accessor for node data fields. */
  const d = node.data as Record<string, unknown>;

  const handleChange = (field: string, value: unknown) => {
    onChange(node.id, { [field]: value } as Partial<FlowNodeData>);
  };

  const renderField = (
    label: string,
    field: string,
    type: 'text' | 'textarea' | 'number' = 'text',
    placeholder?: string
  ) => {
    const value = d[field] ?? '';

    if (type === 'textarea') {
      return (
        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {label}
          </label>
          <textarea
            value={String(value)}
            onChange={(e) => handleChange(field, e.target.value)}
            placeholder={placeholder}
            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm resize-y min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      );
    }

    return (
      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {label}
        </label>
        <input
          type={type}
          value={type === 'number' ? Number(value) || 0 : String(value)}
          onChange={(e) =>
            handleChange(
              field,
              type === 'number' ? Number(e.target.value) : e.target.value
            )
          }
          placeholder={placeholder}
          className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
    );
  };

  // Render a comma-separated string array field (e.g. enabled_tools)
  const renderStringArrayField = (
    label: string,
    field: string,
    placeholder?: string
  ) => {
    const value = d[field] as string[] | undefined;
    return (
      <div className="mb-4">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          {label}
        </label>
        <input
          type="text"
          value={(value || []).join(', ')}
          onChange={(e) => {
            const arr = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
            handleChange(field, arr.length > 0 ? arr : undefined);
          }}
          placeholder={placeholder}
          className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <div className="text-xs text-gray-400 mt-1">Comma-separated list</div>
      </div>
    );
  };

  // Gather calls editor (Format 1: different modules)
  const renderGatherCalls = () => {
    const gatherData = node.data as GatherNodeData;
    const calls = gatherData.calls || [];

    const addCall = () => {
      const newCall: GatherCall = { module: '', parameters: {}, save_as: '' };
      handleChange('calls', [...calls, newCall]);
    };

    const updateCall = (index: number, field: keyof GatherCall, value: unknown) => {
      const updated = [...calls];
      updated[index] = { ...updated[index], [field]: value };
      handleChange('calls', updated);
    };

    const removeCall = (index: number) => {
      const updated = calls.filter((_, i) => i !== index);
      handleChange('calls', updated);
    };

    return (
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-xs font-medium text-gray-600">
            Module Calls ({calls.length})
          </label>
          <button
            onClick={addCall}
            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
          >
            <Plus size={12} /> Add Call
          </button>
        </div>
        <div className="space-y-3">
          {calls.map((call, index) => (
            <div key={index} className="p-3 bg-white border border-gray-200 rounded-md">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-500">Call {index + 1}</span>
                <button
                  onClick={() => removeCall(index)}
                  className="text-red-400 hover:text-red-600"
                >
                  <X size={14} />
                </button>
              </div>
              <input
                type="text"
                value={call.module || ''}
                onChange={(e) => updateCall(index, 'module', e.target.value)}
                placeholder="path/to/module.yaml"
                className="w-full px-2 py-1.5 mb-2 border border-gray-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <input
                type="text"
                value={call.save_as || ''}
                onChange={(e) => updateCall(index, 'save_as', e.target.value)}
                placeholder="save_as (optional)"
                className="w-full px-2 py-1.5 mb-2 border border-gray-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <div className="text-xs text-gray-400 mb-1">Parameters (YAML):</div>
              <textarea
                value={toYamlString(call.parameters)}
                onChange={(e) => {
                  const params = parseYamlParams(e.target.value);
                  if (params !== null) {
                    updateCall(index, 'parameters', params);
                  }
                }}
                placeholder="search_query: Python&#10;max_results: '2'"
                className="w-full px-2 py-1.5 border border-gray-200 rounded text-xs font-mono resize-y min-h-[50px] focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          ))}
          {calls.length === 0 && (
            <div className="text-xs text-gray-400 text-center py-2">
              No calls yet. Click "Add Call" to add one.
            </div>
          )}
        </div>
      </div>
    );
  };

  // Parallel parameters list editor
  const renderParallelParams = () => {
    const parallelData = node.data as ParallelNodeData;
    const paramsList = Array.isArray(parallelData.parameters_list) ? parallelData.parameters_list : [];

    const addParams = () => {
      handleChange('parameters_list', [...paramsList, {}]);
    };

    const updateParams = (index: number, value: string) => {
      const params = parseYamlParams(value);
      if (params !== null) {
        const updated = [...paramsList];
        updated[index] = params;
        handleChange('parameters_list', updated);
      }
    };

    const removeParams = (index: number) => {
      const updated = paramsList.filter((_, i) => i !== index);
      handleChange('parameters_list', updated);
    };

    return (
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-xs font-medium text-gray-600">
            Parameter Sets ({paramsList.length})
          </label>
          <button
            onClick={addParams}
            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
          >
            <Plus size={12} /> Add Params
          </button>
        </div>
        <div className="space-y-3">
          {paramsList.map((params, index) => (
            <div key={index} className="p-3 bg-white border border-gray-200 rounded-md">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-500">Params {index + 1}</span>
                <button
                  onClick={() => removeParams(index)}
                  className="text-red-400 hover:text-red-600"
                >
                  <X size={14} />
                </button>
              </div>
              <textarea
                value={toYamlString(params)}
                onChange={(e) => updateParams(index, e.target.value)}
                placeholder="param1: value1&#10;param2: value2"
                className="w-full px-2 py-1.5 border border-gray-200 rounded text-xs font-mono resize-y min-h-[50px] focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          ))}
          {paramsList.length === 0 && (
            <div className="text-xs text-gray-400 text-center py-2">
              No parameter sets. Click "Add Params" to add one.
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderNodeSpecificFields = () => {
    switch (node.data.nodeType) {
      case 'step':
        return (
          <>
            {renderField('Name', 'name', 'text', 'step_name')}
            {renderField('Instruction', 'instruction', 'textarea', 'Conversation-aware instruction (history preserved across steps)')}
            {renderField('Save As', 'save_as', 'text', 'variable_name')}
            {renderField('Output File', 'output_file', 'text', 'output.txt')}
            {renderStringArrayField('Enabled Tools', 'enabled_tools', 'tool1, tool2, ...')}
          </>
        );

      case 'task':
        return (
          <>
            {renderField('Name', 'name', 'text', 'task_name')}
            {renderField('Instruction', 'instruction', 'textarea', 'Stateless instruction (fresh conversation each time)')}
            {renderField('Save As', 'save_as', 'text', 'variable_name')}
            {renderField('System Prompt', 'system_prompt', 'textarea', 'Override default system prompt for this task')}
            {renderStringArrayField('Enabled Tools', 'enabled_tools', 'tool1, tool2, ...')}
          </>
        );

      case 'if':
        return (
          <>
            {renderField('Condition', 'condition', 'textarea', 'e.g., result == "success"')}
          </>
        );

      case 'while':
        return (
          <>
            {renderField('Condition', 'condition', 'textarea', 'e.g., counter < 10')}
            {renderField('Max Iterations', 'max_iterations', 'number')}
          </>
        );

      case 'for_each':
        return (
          <>
            {renderField('Variable', 'variable', 'text', 'item')}
            {renderField('In (source)', 'in', 'text', '["a", "b", "c"] or variable_name')}
            {renderField('Max Iterations', 'max_iterations', 'number')}
            {renderField('Limit', 'limit', 'number')}
          </>
        );

      case 'switch':
        return (
          <>
            {renderField('Variable', 'variable', 'text', 'variable_to_switch_on')}
          </>
        );

      case 'gather':
        return (
          <>
            <div className="mb-2 text-xs text-gray-500">
              Run different modules in parallel (calls format)
            </div>
            {renderField('Max Workers', 'max_workers', 'number')}
            {renderField('Save Results As', 'save_results_as', 'text', 'results')}
            {renderGatherCalls()}
            <YamlParamsEditor
              value={d.config as Record<string, unknown> | undefined}
              onChange={(params) => handleChange('config', params)}
              placeholder="model: gpt-4o&#10;max_tokens_per_step: 50000"
              label="Config Override (YAML)"
            />
          </>
        );

      case 'parallel': {
        const pSteps = d.parallelSteps as unknown[] | undefined;
        if (pSteps && pSteps.length > 0) {
          return (
            <>
              <div className="mb-2 text-xs text-gray-500">
                Parallel execution of inline steps (edit steps in visual graph)
              </div>
              {renderField('Max Workers', 'max_workers', 'number')}
            </>
          );
        }
        return (
          <>
            <div className="mb-2 text-xs text-gray-500">
              Run same module with different parameters
            </div>
            {renderField('Module', 'module', 'text', 'path/to/module.yaml')}
            {renderField('Max Workers', 'max_workers', 'number')}
            {renderField('Save Results As', 'save_results_as', 'text', 'results')}
            {renderParallelParams()}
          </>
        );
      }

      case 'input':
        return (
          <>
            {renderField('Prompt', 'prompt', 'textarea', 'Question or prompt for the user')}
            {renderField('Save As', 'save_as', 'text', 'user_input')}
            {renderField('Default', 'default', 'text', 'Default value if non-interactive')}
          </>
        );

      case 'return':
        return (
          <>
            {renderField('Variable', 'variable', 'text', 'prev_output')}
          </>
        );

      case 'increment':
        return (
          <>
            {renderField('Variable', 'variable', 'text', 'counter')}
          </>
        );

      case 'set_variable':
        return (
          <>
            {renderField('Name', 'name', 'text', 'variable')}
            {renderField('Value', 'value', 'text', 'value or {{context_var}}')}
          </>
        );

      case 'call':
        return (
          <>
            {renderField('Module', 'module', 'text', 'path/to/module.yaml')}
            {renderField('Save As', 'save_as', 'text', 'result')}
            {renderField('Return Variable', 'return', 'text', 'prev_output')}
            <YamlParamsEditor
              value={d.parameters as Record<string, unknown> | undefined}
              onChange={(params) => handleChange('parameters', params)}
              placeholder="search_query: Python&#10;max_results: 3"
            />
            <YamlParamsEditor
              value={d.config as Record<string, unknown> | undefined}
              onChange={(params) => handleChange('config', params)}
              placeholder="model: gpt-4o&#10;max_tokens_per_step: 50000"
              label="Config Override (YAML)"
            />
          </>
        );

      default:
        // Start node: edit workflow-level metadata preserved across graph<->yaml round-trips
        if (node.data.nodeType === 'start') {
          return (
            <>
              <div className="mb-2 text-xs text-gray-500">
                Workflow-level settings for the current YAML file.
              </div>
              {renderField('Workflow Name', 'label', 'text', 'my_workflow')}
              {renderField('Goal', 'goal', 'textarea', 'High-level goal for this workflow')}
              <YamlParamsEditor
                value={d.parameters as Record<string, unknown> | undefined}
                onChange={(params) => handleChange('parameters', params)}
                placeholder="domain: biology&#10;topic: flow matching"
                label="Parameters (YAML)"
              />
              <YamlParamsEditor
                value={d.config as Record<string, unknown> | undefined}
                onChange={(params) => handleChange('config', params)}
                placeholder="model: gpt-4.1-mini&#10;max_tokens_per_step: 50000"
                label="Config (YAML)"
              />
              {renderField('System Prompt', 'system_prompt', 'textarea', 'Default system prompt for all steps')}
            </>
          );
        }
        return null;
    }
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: config?.borderColor }}
          />
          <span className="font-semibold text-gray-800">{config?.label}</span>
        </div>
        {!isProtected && (
          <button
            onClick={() => onDelete(node.id)}
            className="p-1.5 rounded hover:bg-red-50 text-red-500"
            title="Delete Node"
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>

      {node.data.nodeType !== 'start' && (
        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Label
          </label>
          <input
            type="text"
            value={node.data.label || ''}
            onChange={(e) => handleChange('label', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      )}

      {renderNodeSpecificFields()}

      <div className="mt-6 pt-4 border-t border-gray-200">
        <div className="text-xs text-gray-400">
          Node ID: <code className="text-gray-500">{node.id}</code>
        </div>
      </div>
    </div>
  );
}