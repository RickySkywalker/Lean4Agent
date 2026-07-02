import { Handle, Position } from '@xyflow/react';
import React from 'react';
import { NODE_CONFIGS, NodeType, FlowNodeData } from '../../types';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';
import {
  FileText,
  GitBranch,
  RefreshCw,
  List,
  GitMerge,
  Layers,
  ExternalLink,
  Play,
  Square,
  Plus,
  Variable,
  GitFork,
  MessageCircle,
  MessageSquare,
  ArrowRight,
  LucideIcon,
} from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  FileText,
  GitBranch,
  RefreshCw,
  List,
  GitMerge,
  Layers,
  ExternalLink,
  Play,
  Square,
  Plus,
  Variable,
  GitFork,
  MessageCircle,
  MessageSquare,
  ArrowRight,
};

interface BaseNodeProps {
  data: FlowNodeData;
  selected?: boolean;
  showSourceHandle?: boolean;
  showTargetHandle?: boolean;
  subtitle?: string | React.ReactNode;
  dropHint?: string;
}

export default function BaseNode({
  data,
  selected,
  showSourceHandle = true,
  showTargetHandle = true,
  subtitle,
  dropHint,
}: BaseNodeProps) {
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;
  const nodeType = data.nodeType as NodeType;
  const config = NODE_CONFIGS[nodeType];
  const Icon = iconMap[config?.icon] || FileText;

  return (
    <div
      className={`custom-node bg-white border shadow-sm hover:shadow-md transition-shadow ${
        selected ? 'selected ring-2 ring-sky-400 ring-offset-2 ring-offset-slate-50' : ''
      }`}
      style={{
        borderWidth: 1,
        borderStyle: 'solid',
        borderColor: config?.borderColor || '#e5e7eb',
        boxShadow: '0 8px 20px rgba(15,23,42,0.06)',
      }}
    >
      {showTargetHandle && (
        <Handle
          type="target"
          position={targetPos}
          className="!bg-gray-400 !w-2 !h-2"
        />
      )}
      
      <div className="flex items-start gap-2">
        <div
          className="p-1 rounded"
          style={{ backgroundColor: `${config?.borderColor}20` }}
        >
          <Icon size={14} color={config?.borderColor} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="node-header" style={{ color: config?.borderColor }}>
            {nodeType}
          </div>
          <div className="node-title">{data.label}</div>
          {typeof subtitle === 'string' ? (
            <div className="node-subtitle">{subtitle}</div>
          ) : (
            subtitle
          )}
          {dropHint && <div className="text-xs text-green-600 mt-1 font-medium">{dropHint}</div>}
        </div>
      </div>
      
      {showSourceHandle && (
        <Handle
          type="source"
          position={sourcePos}
          className="!bg-gray-400 !w-2 !h-2"
        />
      )}
    </div>
  );
}

