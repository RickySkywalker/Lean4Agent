import { NodeProps } from '@xyflow/react';
import BaseNode from './BaseNode';
import { StepNodeData, FlowNodeData } from '../../types';

export default function StepNode({ data, selected }: NodeProps) {
  const stepData = data as StepNodeData;
  const subtitle = stepData.instruction
    ? stepData.instruction.length > 40
      ? stepData.instruction.substring(0, 40) + '...'
      : stepData.instruction
    : undefined;

  return <BaseNode data={data as FlowNodeData} selected={selected} subtitle={subtitle} />;
}

