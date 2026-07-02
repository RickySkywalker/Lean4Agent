import { Handle, Position, NodeProps } from '@xyflow/react';
import { NODE_CONFIGS, BaseNodeData } from '../../types';
import { Play, Square } from 'lucide-react';
import { useLayoutDirection } from '../../contexts/LayoutDirectionContext';

export function StartNode({ data, selected }: NodeProps) {
  const nodeData = data as BaseNodeData;
  const config = NODE_CONFIGS['start'];
  const layoutDirection = useLayoutDirection();
  const sourcePos = layoutDirection === 'LR' ? Position.Right : Position.Bottom;

  return (
    <div
      className={`custom-node ${selected ? 'selected' : ''}`}
      style={{
        backgroundColor: '#ffffff',
        borderWidth: 1,
        borderStyle: 'solid',
        borderColor: config.borderColor,
        borderRadius: 24,
        padding: '8px 20px',
        boxShadow: '0 8px 20px rgba(15,23,42,0.06)',
      }}
    >
      <div className="flex items-center gap-2">
        <Play size={16} style={{ color: config.borderColor }} />
        <span className="font-medium" style={{ color: config.borderColor }}>
          {nodeData.label || 'Start'}
        </span>
      </div>
      <Handle
        type="source"
        position={sourcePos}
        className="!bg-green-500 !w-2 !h-2"
      />
    </div>
  );
}

export function EndNode({ data, selected }: NodeProps) {
  const nodeData = data as BaseNodeData;
  const config = NODE_CONFIGS['end'];
  const layoutDirection = useLayoutDirection();
  const targetPos = layoutDirection === 'LR' ? Position.Left : Position.Top;

  return (
    <div
      className={`custom-node ${selected ? 'selected' : ''}`}
      style={{
        backgroundColor: '#ffffff',
        borderWidth: 1,
        borderStyle: 'solid',
        borderColor: config.borderColor,
        borderRadius: 24,
        padding: '8px 20px',
        boxShadow: '0 8px 20px rgba(15,23,42,0.06)',
      }}
    >
      <Handle
        type="target"
        position={targetPos}
        className="!bg-red-500 !w-2 !h-2"
      />
      <div className="flex items-center gap-2">
        <Square size={14} style={{ color: config.borderColor }} />
        <span className="font-medium" style={{ color: config.borderColor }}>
          {nodeData.label || 'End'}
        </span>
      </div>
    </div>
  );
}

