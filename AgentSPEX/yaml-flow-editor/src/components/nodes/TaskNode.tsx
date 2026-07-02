import { NodeProps } from '@xyflow/react';
import BaseNode from './BaseNode';
import { TaskNodeData, FlowNodeData } from '../../types';

export default function TaskNode({ data, selected }: NodeProps) {
  const taskData = data as TaskNodeData;
  const subtitle = taskData.instruction
    ? taskData.instruction.length > 40
      ? taskData.instruction.substring(0, 40) + '...'
      : taskData.instruction
    : undefined;

  return <BaseNode data={data as FlowNodeData} selected={selected} subtitle={subtitle} />;
}
