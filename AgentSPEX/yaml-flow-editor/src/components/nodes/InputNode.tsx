import { NodeProps } from '@xyflow/react';
import BaseNode from './BaseNode';
import { InputNodeData, FlowNodeData } from '../../types';

export default function InputNode({ data, selected }: NodeProps) {
  const inputData = data as InputNodeData;
  const subtitle = inputData.prompt
    ? inputData.prompt.length > 40
      ? inputData.prompt.substring(0, 40) + '...'
      : inputData.prompt
    : inputData.save_as
      ? `→ ${inputData.save_as}`
      : undefined;

  return <BaseNode data={data as FlowNodeData} selected={selected} subtitle={subtitle} />;
}
