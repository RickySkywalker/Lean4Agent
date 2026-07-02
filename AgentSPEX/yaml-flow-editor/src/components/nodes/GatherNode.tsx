import { NodeProps, useReactFlow } from '@xyflow/react';
import React, { useState, useCallback } from 'react';
import BaseNode from './BaseNode';
import { GatherNodeData, FlowNodeData } from '../../types';
import SubmoduleInlineViewer from '../SubmoduleInlineViewer';

export default function GatherNode({ data, selected, id }: NodeProps) {
  const gatherData = data as GatherNodeData;
  const workers = gatherData.max_workers || 4;
  const [isDragOver, setIsDragOver] = useState(false);
  const { setNodes } = useReactFlow();
  
  // Determine which format is used
  let subtitle: string | React.ReactNode = '';
  if (gatherData.calls && gatherData.calls.length > 0) {
    subtitle = (
      <div className="mt-1 w-full">
        <div className="text-[10px] opacity-70 mb-1">{workers} workers</div>
        <div className="flex flex-col gap-1">
          {gatherData.calls.map((call, i) => (
            <div 
              key={i} 
              className="bg-black/5 px-1.5 py-0.5 rounded text-[10px] truncate border border-black/5 w-full"
              title={call.module}
            >
              {call.module.split('/').pop()}
            </div>
          ))}
        </div>
      </div>
    );
  } else if (gatherData.module) {
    const paramCount = Array.isArray(gatherData.parameters_list) ? gatherData.parameters_list.length : 0;
    subtitle = `${gatherData.module.split('/').pop()}, ${paramCount} params`;
  } else {
    subtitle = `${workers} workers`;
  }

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

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const moduleData = e.dataTransfer.getData('application/module');
    if (!moduleData) return;

    try {
      const module = JSON.parse(moduleData);
      // Add the module to the gather's calls list
      setNodes((nodes) =>
        nodes.map((node) => {
          if (node.id === id) {
            const currentCalls = (node.data as GatherNodeData).calls || [];
            const newCall = {
              module: module.path,
              parameters: module.defaultParams || {},
              save_as: `${module.name.toLowerCase().replace(/\s+/g, '_')}_result_${currentCalls.length + 1}`,
            };
            return {
              ...node,
              data: {
                ...node.data,
                calls: [...currentCalls, newCall],
                moduleContents: undefined,
              },
            };
          }
          return node;
        })
      );
    } catch (err) {
      console.error('Failed to parse module data:', err);
    }
  }, [id, setNodes]);

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={isDragOver ? 'ring-2 ring-green-500 ring-offset-2 rounded-lg' : ''}
    >
      <BaseNode 
        data={data as FlowNodeData} 
        selected={selected} 
        subtitle={subtitle}
        dropHint={isDragOver ? 'Drop to add module' : undefined}
      />
      {/* Format 2: single module – one submodule viewer */}
      {gatherData.module && (
        <SubmoduleInlineViewer modulePath={gatherData.module} parentNodeId={id} depth={1} nodeModuleContents={gatherData.moduleContents} />
      )}
      {/* Format 1: multiple calls – one submodule viewer per worker for view/edit */}
      {(gatherData.calls?.length ?? 0) > 0 && (
        <div className="mt-2 space-y-2">
          {(gatherData.calls ?? []).map((call, i) => (
            <div key={i} className="rounded-lg border border-slate-200 bg-slate-50/80 p-1.5">
              <div className="text-[10px] font-medium text-slate-500 mb-1">
                Worker {i + 1}: {call.module.split('/').pop() || call.module}
              </div>
              <SubmoduleInlineViewer
                modulePath={call.module}
                parentNodeId={id}
                depth={1}
                nodeModuleContents={gatherData.moduleContents}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

