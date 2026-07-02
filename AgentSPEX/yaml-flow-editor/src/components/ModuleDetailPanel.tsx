import { useState, useEffect } from 'react';
import { Package, Plus, ArrowRight } from 'lucide-react';
import { ModuleTemplate, WorkflowStep } from './Sidebar';

interface ModuleDetailPanelProps {
  module: ModuleTemplate;
  onClose?: () => void;
  onAddToCanvas?: (module: ModuleTemplate, params: Record<string, string>) => void;
}

const stepTypeColors: Record<string, { bg: string; border: string; text: string }> = {
  step: { bg: '#DBEAFE', border: '#3B82F6', text: '#1D4ED8' },
  if: { bg: '#FEF3C7', border: '#F59E0B', text: '#B45309' },
  while: { bg: '#EDE9FE', border: '#8B5CF6', text: '#6D28D9' },
  for_each: { bg: '#D1FAE5', border: '#10B981', text: '#047857' },
  switch: { bg: '#FEE2E2', border: '#EF4444', text: '#B91C1C' },
  parallel: { bg: '#CFFAFE', border: '#06B6D4', text: '#0E7490' },
  gather: { bg: '#DCFCE7', border: '#22C55E', text: '#15803D' },
};

function WorkflowStepCard({ step, index }: { step: WorkflowStep; index: number }) {
  const colors = stepTypeColors[step.type] || { bg: '#F3F4F6', border: '#6B7280', text: '#374151' };

  return (
    <div 
      className="p-3 rounded-lg border-l-4"
      style={{ 
        backgroundColor: colors.bg, 
        borderLeftColor: colors.border,
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        <span 
          className="text-xs font-bold px-1.5 py-0.5 rounded"
          style={{ backgroundColor: colors.border, color: 'white' }}
        >
          {index + 1}
        </span>
        <span className="font-semibold" style={{ color: colors.text }}>
          {step.name}
        </span>
        <span 
          className="text-[10px] px-1.5 py-0.5 rounded uppercase"
          style={{ backgroundColor: 'rgba(0,0,0,0.1)', color: colors.text }}
        >
          {step.type}
        </span>
      </div>
      {step.description && (
        <p className="text-sm text-gray-600 ml-7">{step.description}</p>
      )}
    </div>
  );
}

export default function ModuleDetailPanel({ module, onClose, onAddToCanvas }: ModuleDetailPanelProps) {
  const [params, setParams] = useState<Record<string, string>>({});

  // Initialize params when module changes
  useEffect(() => {
    if (module.defaultParams) {
      setParams({ ...module.defaultParams });
    } else {
      setParams({});
    }
  }, [module]);

  const handleParamChange = (key: string, value: string) => {
    setParams((prev) => ({ ...prev, [key]: value }));
  };

  const handleAddToCanvas = () => {
    onAddToCanvas?.(module, params);
  };

  return (
    <div className="p-4 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-blue-100 rounded-lg">
            <Package size={20} className="text-blue-600" />
          </div>
          <div>
            <h2 className="font-bold text-lg text-gray-800">{module.name}</h2>
            <p className="text-xs text-gray-500">{module.path}</p>
          </div>
        </div>
        {onClose && (
          <button 
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1"
          >
            ✕
          </button>
        )}
      </div>

      {/* Goal */}
      {module.goal && (
        <div className="mb-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
          <div className="text-xs font-semibold text-gray-500 uppercase mb-1">Goal</div>
          <p className="text-sm text-gray-700">{module.goal}</p>
        </div>
      )}

      {/* Parameters - Editable */}
      {module.defaultParams && Object.keys(module.defaultParams).length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-semibold text-gray-500 uppercase mb-2">Parameters</div>
          <div className="space-y-3">
            {Object.entries(module.defaultParams).map(([key, defaultValue]) => (
              <div key={key}>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {key}
                  {!defaultValue && <span className="text-red-500 ml-1">*</span>}
                </label>
                <input
                  type="text"
                  value={params[key] || ''}
                  onChange={(e) => handleParamChange(key, e.target.value)}
                  placeholder={defaultValue ? `default: ${defaultValue}` : 'required'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add to Canvas Button */}
      {onAddToCanvas && (
        <button
          onClick={handleAddToCanvas}
          className="w-full mb-4 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
        >
          <Plus size={18} />
          Add to Canvas
        </button>
      )}

      {/* Workflow */}
      {module.workflow && module.workflow.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-gray-500 uppercase mb-2">
            Workflow ({module.workflow.length} steps)
          </div>
          <div className="space-y-2">
            {module.workflow.map((step, index) => (
              <div key={step.name}>
                <WorkflowStepCard step={step} index={index} />
                {index < module.workflow!.length - 1 && (
                  <div className="flex justify-center py-1">
                    <ArrowRight size={16} className="text-gray-300 rotate-90" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hint */}
      <div className="mt-6 p-3 bg-gray-50 border border-gray-200 rounded-lg">
        <p className="text-xs text-gray-500">
          💡 Fill in the parameters above and click "Add to Canvas", or drag the module from the sidebar.
        </p>
      </div>
    </div>
  );
}

