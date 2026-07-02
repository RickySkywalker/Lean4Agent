import yaml from 'js-yaml';
import {
  FlowNodeData,
  NODE_CONFIGS,
  StepNodeData,
  CallNodeData,
  InputNodeData,
  ReturnNodeData,
  IncrementNodeData,
  SetVariableNodeData,
  ParallelNodeData,
  GatherNodeData,
  GatherCall,
} from '../types';
import { Plus, X } from 'lucide-react';

interface Props {
  step: FlowNodeData;
  onChange: (next: FlowNodeData) => void;
}

export default function SubmoduleStepConfigPanel({ step, onChange }: Props) {
  const stepConfig = NODE_CONFIGS[step.nodeType];
  const stepData = step as StepNodeData;
  const callData = step as CallNodeData;
  const inputData = step as InputNodeData;
  const returnData = step as ReturnNodeData;
  const incrementData = step as IncrementNodeData;
  const setVariableData = step as SetVariableNodeData;
  const parallelData = step as ParallelNodeData;
  const gatherData = step as GatherNodeData;

  const updateStep = (patch: Partial<FlowNodeData>) => {
    onChange({ ...step, ...patch });
  };

  const toYamlString = (obj: Record<string, unknown> | undefined): string => {
    if (!obj || Object.keys(obj).length === 0) return '';
    try {
      return yaml
        .dump(obj, {
          flowLevel: -1,
          lineWidth: -1,
          quotingType: '"',
          forceQuotes: false,
        })
        .trim();
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
    <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2">
      <div className="mb-2 flex items-center gap-2">
        <div
          className="h-3 w-3 rounded-full"
          style={{ backgroundColor: stepConfig?.borderColor || '#666' }}
        />
        <div className="text-xs font-semibold text-slate-800">
          {step.nodeType === 'step'
            ? 'Step'
            : step.nodeType === 'call'
            ? 'Call Module'
            : step.nodeType === 'input'
            ? 'Input'
            : step.nodeType === 'return'
            ? 'Return'
            : step.nodeType === 'increment'
            ? 'Increment'
            : step.nodeType === 'set_variable'
            ? 'Set Variable'
            : step.nodeType === 'parallel'
            ? 'Parallel'
            : step.nodeType === 'gather'
            ? 'Gather'
            : step.nodeType}
        </div>
      </div>

      <div className="space-y-3">
        {/* Common: Label */}
        <div>
          <label className="mb-1 block text-[11px] font-medium text-slate-600">Label</label>
          <input
            type="text"
            value={step.label || ''}
            onChange={(e) => updateStep({ label: e.target.value })}
            className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
          />
        </div>

        {step.nodeType === 'step' && (
          <>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Name</label>
              <input
                type="text"
                value={stepData.name || ''}
                onChange={(e) =>
                  updateStep({ name: e.target.value })
                }
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Instruction
              </label>
              <textarea
                value={stepData.instruction || ''}
                onChange={(e) => updateStep({ instruction: e.target.value })}
                rows={3}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Save As</label>
              <input
                type="text"
                value={stepData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
          </>
        )}

        {step.nodeType === 'call' && (
          <>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Module Path
              </label>
              <input
                type="text"
                value={callData.module || ''}
                onChange={(e) =>
                  updateStep({ module: e.target.value })
                }
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="modules/your_module.yaml"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Parameters (YAML)
              </label>
              <textarea
                value={toYamlString(callData.parameters)}
                onChange={(e) => {
                  const parsed = parseYamlParams(e.target.value);
                  if (parsed !== null) {
                    updateStep({ parameters: parsed });
                  }
                }}
                rows={3}
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="key: value"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Save As</label>
              <input
                type="text"
                value={callData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
          </>
        )}

        {step.nodeType === 'input' && (
          <>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Prompt</label>
              <textarea
                value={inputData.prompt || ''}
                onChange={(e) =>
                  updateStep({ prompt: e.target.value })
                }
                rows={2}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Save As
              </label>
              <input
                type="text"
                value={inputData.save_as || ''}
                onChange={(e) => updateStep({ save_as: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Default
              </label>
              <input
                type="text"
                value={inputData.default || ''}
                onChange={(e) => updateStep({ default: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
          </>
        )}

        {step.nodeType === 'return' && (
          <div>
            <label className="mb-1 block text-[11px] font-medium text-slate-600">Variable</label>
            <input
              type="text"
              value={returnData.variable || ''}
              onChange={(e) =>
                updateStep({ variable: e.target.value })
              }
              className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
            />
          </div>
        )}

        {step.nodeType === 'increment' && (
          <div>
            <label className="mb-1 block text-[11px] font-medium text-slate-600">Variable</label>
            <input
              type="text"
              value={incrementData.variable || ''}
              onChange={(e) =>
                updateStep({ variable: e.target.value })
              }
              className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
            />
          </div>
        )}

        {step.nodeType === 'set_variable' && (
          <>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Name</label>
              <input
                type="text"
                value={setVariableData.name || ''}
                onChange={(e) =>
                  updateStep({ name: e.target.value })
                }
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">Value</label>
              <input
                type="text"
                value={
                  typeof setVariableData.value === 'string'
                    ? setVariableData.value
                    : String(setVariableData.value ?? '')
                }
                onChange={(e) => updateStep({ value: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
          </>
        )}

        {step.nodeType === 'parallel' && (
          <>
            <div className="text-[11px] text-slate-500">
              Run same module with different parameters.
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Module
              </label>
              <input
                type="text"
                value={parallelData.module || ''}
                onChange={(e) =>
                  updateStep({ module: e.target.value })
                }
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="modules/your_module.yaml"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Max Workers
              </label>
              <input
                type="number"
                value={parallelData.max_workers ?? ''}
                onChange={(e) =>
                  updateStep({
                    max_workers: e.target.value === '' ? undefined : Number(e.target.value),
                  })
                }
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Save Results As
              </label>
              <input
                type="text"
                value={parallelData.save_results_as || ''}
                onChange={(e) => updateStep({ save_results_as: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Parameters list (context variable or YAML array)
              </label>
              <textarea
                value={
                  typeof parallelData.parameters_list === 'string'
                    ? parallelData.parameters_list
                    : Array.isArray(parallelData.parameters_list)
                    ? yaml.dump(parallelData.parameters_list, {
                        indent: 2,
                        lineWidth: -1,
                      }).trim()
                    : ''
                }
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
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="user_query_params  or  - key: val"
              />
            </div>
          </>
        )}

        {step.nodeType === 'gather' && (
          <>
            <div className="text-[11px] text-slate-500">
              Run different modules or same module with different parameters.
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Module (Format 2)
              </label>
              <input
                type="text"
                value={gatherData.module || ''}
                onChange={(e) => updateStep({ module: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="modules/your_module.yaml or empty for calls[]"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Max Workers
              </label>
              <input
                type="number"
                value={gatherData.max_workers ?? ''}
                onChange={(e) =>
                  updateStep({
                    max_workers: e.target.value === '' ? undefined : Number(e.target.value),
                  })
                }
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Save Results As
              </label>
              <input
                type="text"
                value={gatherData.save_results_as || ''}
                onChange={(e) => updateStep({ save_results_as: e.target.value })}
                className="w-full rounded border px-2 py-1 text-xs focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Parameters list (Format 2)
              </label>
              <textarea
                value={
                  typeof gatherData.parameters_list === 'string'
                    ? gatherData.parameters_list
                    : gatherData.parameters_list && Array.isArray(gatherData.parameters_list)
                    ? yaml.dump(gatherData.parameters_list, {
                        indent: 2,
                        lineWidth: -1,
                      }).trim()
                    : ''
                }
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
                className="w-full rounded border px-2 py-1 text-xs font-mono focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-400"
                placeholder="serp_params or leave empty"
              />
            </div>
            <div className="border-t border-slate-100 pt-2">
              <label className="mb-1 block text-[11px] font-medium text-slate-600">
                Module Calls (Format 1)
              </label>
              <div className="space-y-2">
                {(gatherData.calls || []).map((call: GatherCall, index: number) => (
                  <div
                    key={index}
                    className="rounded border border-slate-200 bg-slate-50 p-2 text-[11px]"
                  >
                    <div className="mb-1 flex items-center justify-between text-slate-500">
                      <span>Call {index + 1}</span>
                      <button
                        type="button"
                        onClick={() =>
                          updateStep({
                            calls: (gatherData.calls || []).filter((_, i) => i !== index),
                          })
                        }
                        className="text-red-500 hover:text-red-700"
                      >
                        <X size={12} />
                      </button>
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
                      className="mb-1 w-full rounded border px-2 py-1 text-xs font-mono"
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
                      className="w-full rounded border px-2 py-1 text-xs"
                    />
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    updateStep({
                      calls: [...(gatherData.calls || []), { module: '', parameters: {}, save_as: '' }],
                    })
                  }
                  className="flex items-center gap-1 text-xs text-sky-600 hover:text-sky-800"
                >
                  <Plus size={12} /> Add Call
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

