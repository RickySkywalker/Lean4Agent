import { NodeTypes } from '@xyflow/react';
import StepNode from './StepNode';
import TaskNode from './TaskNode';
import IfContainerNode from './IfContainerNode';
import WhileContainerNode from './WhileContainerNode';
import ForEachContainerNode from './ForEachContainerNode';
import SwitchContainerNode from './SwitchContainerNode';
import GatherNode from './GatherNode';
import ParallelNode from './ParallelNode';
import CallNode from './CallNode';
import InputNode from './InputNode';
import ReturnNode from './ReturnNode';
import { StartNode, EndNode } from './StartEndNode';
import BaseNode from './BaseNode';

export const nodeTypes: NodeTypes = {
  start: StartNode,
  end: EndNode,
  step: StepNode,
  if: IfContainerNode,
  while: WhileContainerNode,
  for_each: ForEachContainerNode,
  switch: SwitchContainerNode,
  gather: GatherNode,
  parallel: ParallelNode,
  call: CallNode,
  input: InputNode,
  return: ReturnNode,
  task: TaskNode,
  increment: BaseNode,
  set_variable: BaseNode,
};

