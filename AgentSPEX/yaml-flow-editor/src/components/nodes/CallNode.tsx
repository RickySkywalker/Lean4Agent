import { useState, useCallback } from 'react';
import { NodeProps, useReactFlow } from '@xyflow/react';
import BaseNode from './BaseNode';
import { CallNodeData, FlowNodeData } from '../../types';
import SubmoduleInlineViewer from '../SubmoduleInlineViewer';

export default function CallNode({ data, selected, id }: NodeProps) {
  const callData = data as CallNodeData;
  const modulePath = callData.module || '';
  // Show just the filename
  const moduleName = modulePath.split('/').pop() || modulePath;
  const subtitle =
    moduleName.length > 30 ? moduleName.substring(0, 30) + '...' : moduleName;

  const [isDragOver, setIsDragOver] = useState(false);
  const { setNodes } = useReactFlow();

  const handleDragOver = useCallback((e: React.DragEvent) => {
    const moduleData = e.dataTransfer.getData('application/module');
    if (moduleData) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      const moduleData = e.dataTransfer.getData('application/module');
      if (!moduleData) return;

      try {
        const module = JSON.parse(moduleData) as {
          name: string;
          path: string;
          defaultParams?: Record<string, unknown>;
        };

        // Update the existing call node instead of creating a new one
        setNodes((nodes) =>
          nodes.map((node) => {
            if (node.id === id) {
              return {
                ...node,
                data: {
                  ...(node.data as FlowNodeData),
                  module: module.path,
                  label: `Call: ${module.name}`,
                  parameters: module.defaultParams || {},
                  moduleContents: undefined,
                } as CallNodeData,
              };
            }
            return node;
          }),
        );
      } catch (err) {
        console.error('Failed to parse module data:', err);
      }
    },
    [id, setNodes],
  );

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={isDragOver ? 'ring-2 ring-sky-500 ring-offset-2 rounded-lg' : ''}
    >
      <BaseNode
        data={data as FlowNodeData}
        selected={selected}
        subtitle={subtitle}
        dropHint={isDragOver ? 'Drop to set module' : undefined}
      />
      {modulePath && (
        <SubmoduleInlineViewer modulePath={modulePath} parentNodeId={id} depth={1} nodeModuleContents={callData.moduleContents} />
      )}
    </div>
  );
}

