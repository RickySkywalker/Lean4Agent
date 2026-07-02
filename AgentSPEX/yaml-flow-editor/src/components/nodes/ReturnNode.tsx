import { NodeProps } from '@xyflow/react';
import BaseNode from './BaseNode';
import { ReturnNodeData, FlowNodeData } from '../../types';

export default function ReturnNode({ data, selected }: NodeProps) {
  const returnData = data as ReturnNodeData;
  const subtitle = returnData.variable ? `→ ${returnData.variable}` : undefined;

  return <BaseNode data={data as FlowNodeData} selected={selected} subtitle={subtitle} />;
}
