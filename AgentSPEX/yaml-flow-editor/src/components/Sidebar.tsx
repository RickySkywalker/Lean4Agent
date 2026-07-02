import { DragEvent, useState } from 'react';
import { DRAGGABLE_NODES, NODE_CONFIGS, NodeType } from '../types';
import {
  FileText,
  GitBranch,
  RefreshCw,
  List,
  GitMerge,
  Layers,
  ExternalLink,
  GitFork,
  Package,
  MessageCircle,
  MessageSquare,
  ArrowRight,
  Variable,
  Plus,
  ChevronDown,
  ChevronRight,
  LucideIcon,
  X,
  Trash2,
} from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  FileText,
  GitBranch,
  RefreshCw,
  List,
  GitMerge,
  Layers,
  ExternalLink,
  GitFork,
  MessageCircle,
  MessageSquare,
  ArrowRight,
  Variable,
  Plus,
};

// Predefined module templates
export interface WorkflowStep {
  name: string;
  type: 'step' | 'if' | 'while' | 'for_each' | 'switch' | 'parallel' | 'gather';
  description?: string;
}

export interface ModuleTemplate {
  name: string;
  path: string;
  description?: string;
  goal?: string;
  defaultParams?: Record<string, string>;
  workflow?: WorkflowStep[];
}

export const PREDEFINED_MODULES: ModuleTemplate[] = [
  {
    name: 'Web Search',
    path: 'workflows/modules/web_search.yaml',
    description: 'Search the web and return relevant results',
    goal: 'Search the web and return relevant results',
    defaultParams: { search_query: '${SEARCH_QUERY}', max_results: '3' },
    workflow: [
      { name: 'prepare_query', type: 'step', description: 'Prepare and clean the search query' },
      { name: 'execute_search', type: 'step', description: 'Execute web search using the query' },
      { name: 'format_results', type: 'step', description: 'Format results for output' },
    ],
  },
  {
    name: 'Delay Module',
    path: 'workflows/modules/delay_module.yaml',
    description: 'Simulate work with configurable delay',
    goal: 'A simple module that introduces a delay to simulate work',
    defaultParams: { delay_seconds: '3', call_id: '1' },
    workflow: [
      { name: 'start', type: 'step', description: 'Record the start timestamp' },
      { name: 'do_work', type: 'step', description: 'Simulate work by sleeping' },
      { name: 'complete', type: 'step', description: 'Record completion timestamp' },
    ],
  },
];

function DraggableNode({ type }: { type: NodeType }) {
  const config = NODE_CONFIGS[type];
  const Icon = iconMap[config.icon] || FileText;

  const onDragStart = (event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.setData('application/reactflow', type);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div
      className="drag-item flex items-center gap-2 bg-white border shadow-sm hover:shadow-md text-xs text-slate-800"
      style={{
        borderColor: config.borderColor,
        boxShadow: `inset 3px 0 0 ${config.color}`,
      }}
      onDragStart={onDragStart}
      draggable
    >
      <Icon size={16} className="flex-shrink-0" />
      <span className="truncate">{config.label}</span>
    </div>
  );
}

function DraggableModule({ module, isSelected, onSelect, onRemove }: {
  module: ModuleTemplate;
  isSelected?: boolean;
  onSelect?: (module: ModuleTemplate) => void;
  onRemove?: (modulePath: string) => void;
}) {
  const onDragStart = (event: DragEvent<HTMLDivElement>) => {
    // Use special format for module drag
    event.dataTransfer.setData('application/reactflow', 'call');
    event.dataTransfer.setData('application/module', JSON.stringify(module));
    event.dataTransfer.effectAllowed = 'move';
  };

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelect?.(module);
  };

  return (
    <div
      className={`drag-item group flex items-center gap-2 cursor-pointer bg-white border shadow-sm hover:shadow-md text-xs ${
        isSelected ? 'ring-2 ring-sky-400 bg-sky-50' : ''
      }`}
      style={{
        borderColor: '#0284C7',
        boxShadow: 'inset 3px 0 0 #0EA5E9',
      }}
      onDragStart={onDragStart}
      onClick={handleClick}
      draggable
      title={module.description}
    >
      <Package size={14} style={{ color: '#0284C7' }} className="flex-shrink-0" />
      <div className="flex flex-col flex-1 min-w-0">
        <span className="text-xs font-medium truncate">{module.name}</span>
      </div>
      {onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(module.path);
          }}
          className="flex-shrink-0 p-0.5 rounded hover:bg-red-100 text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
          title={`Remove ${module.name}`}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

interface SidebarProps {
  customModules?: ModuleTemplate[];
  selectedModule?: ModuleTemplate | null;
  onModuleSelect?: (module: ModuleTemplate | null) => void;
  onRemoveModule?: (modulePath: string) => void;
  onClearModules?: () => void;
}

export default function Sidebar({ customModules = [], selectedModule, onModuleSelect, onRemoveModule, onClearModules }: SidebarProps) {
  const [showNodes, setShowNodes] = useState(true);
  const [showModules, setShowModules] = useState(true);
  const allModules = [...PREDEFINED_MODULES, ...customModules];
  const predefinedPaths = new Set(PREDEFINED_MODULES.map((m) => m.path));

  const handleModuleSelect = (module: ModuleTemplate) => {
    // Toggle selection if clicking the same module
    if (selectedModule?.path === module.path) {
      onModuleSelect?.(null);
    } else {
      onModuleSelect?.(module);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Scrollable content area */}
      <div className="flex-1 overflow-y-auto min-h-0 pr-1">
        {/* Nodes Section */}
        <button
          onClick={() => setShowNodes(!showNodes)}
          className="flex items-center gap-1 text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-1 hover:text-slate-700 w-full sticky top-0 bg-gradient-to-b from-slate-50/95 to-slate-100/95 py-1 z-10 backdrop-blur"
        >
          {showNodes ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Nodes ({DRAGGABLE_NODES.length})
        </button>
        <p className="text-[11px] text-slate-400 mb-2">
          Drag steps and control-flow blocks into the canvas.
        </p>
        {showNodes && (
          <div className="space-y-2 mb-4">
            {DRAGGABLE_NODES.map((type) => (
              <DraggableNode key={type} type={type} />
            ))}
          </div>
        )}

        {/* Modules Section */}
        <div className="border-t border-gray-200 pt-3">
          <div className="flex items-center gap-1 sticky top-0 bg-gradient-to-b from-slate-50/95 to-slate-100/95 py-1 z-10 backdrop-blur">
            <button
              onClick={() => setShowModules(!showModules)}
              className="flex items-center gap-1 text-[11px] font-semibold text-slate-500 uppercase tracking-wider hover:text-slate-700 flex-1"
            >
              {showModules ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Modules ({allModules.length})
            </button>
            {customModules.length > 0 && onClearModules && (
              <button
                onClick={onClearModules}
                className="p-0.5 rounded hover:bg-red-100 text-slate-400 hover:text-red-500 transition-colors"
                title="Clear all imported modules"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
          <p className="text-[11px] text-slate-400 mb-2">
            Prebuilt and imported modules you can call from the main plan.
          </p>
          {showModules && (
            <div className="space-y-2">
              {allModules.map((module) => (
                <DraggableModule
                  key={module.path}
                  module={module}
                  isSelected={selectedModule?.path === module.path}
                  onSelect={handleModuleSelect}
                  onRemove={predefinedPaths.has(module.path) ? undefined : onRemoveModule}
                />
              ))}
              {allModules.length === 0 && (
                <div className="text-xs text-gray-400 italic">
                  No modules available
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Fixed footer */}
      <div className="text-xs text-gray-400 pt-2 border-t border-gray-200 flex-shrink-0">
        Drag to canvas
      </div>
    </div>
  );
}

