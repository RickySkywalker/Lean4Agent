import { Node, Edge } from '@xyflow/react';

// ── Submodule declaration (top-level `submodules:` key) ──────────────
export interface SubmoduleDeclaration {
  name: string;
  path: string;
}

// ── Top-level workflow structure ─────────────────────────────────────
export interface Workflow {
  name: string;
  goal?: string;
  config?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  system_prompt?: string;
  submodules?: SubmoduleDeclaration[];
  workflow: WorkflowStep[];
}

export type WorkflowStep =
  | { step: StepData }
  | { if: IfData }
  | { while: WhileData }
  | { for_each: ForEachData }
  | { switch: SwitchData }
  | { gather: GatherData }
  | { call: CallData }
  | { increment: string }
  | { set_variable: SetVariableData }
  | { parallel: WorkflowStep[] | ParallelModuleData }  // Format 1 (array) or Format 2 (module+params)
  | { input: InputData }
  | { return: string | ReturnData }
  | { task: TaskData };

export interface StepData {
  name: string;
  instruction?: string;
  save_as?: string;
  output_file?: string;
  enabled_tools?: string[];
}

export interface IfData {
  condition: string;
  then?: WorkflowStep[];
  else?: WorkflowStep[];
}

export interface WhileData {
  condition: string;
  max_iterations?: number;
  steps?: WorkflowStep[];
}

export interface ForEachData {
  variable: string;
  in: string | string[];
  max_iterations?: number;
  limit?: number;
  steps?: WorkflowStep[];
}

export interface SwitchData {
  variable: string;
  cases: Record<string, WorkflowStep[]>;
  default?: WorkflowStep[];
}

// Gather supports two formats:
// Format 1: calls array (different modules)
// Format 2: module + parameters_list (same module, different params)
export interface GatherData {
  // Format 1: Different modules
  calls?: GatherCall[];
  // Format 2: Same module with different parameters
  module?: string;
  parameters_list?: Record<string, unknown>[] | string;
  save_as_prefix?: string;
  save_as_list?: string[];
  // Common
  save_results_as?: string;
  max_workers?: number;
  config?: Record<string, unknown>;
}

export interface GatherCall {
  module: string;
  parameters?: Record<string, unknown>;
  save_as?: string;
}

export interface InputData {
  prompt: string;
  save_as?: string;
  default?: string;
}

export interface ReturnData {
  /** Variable name to return (or use scalar form: - return: "var_name") */
  variable?: string;
}

export interface CallData {
  module: string;
  parameters?: Record<string, unknown>;
  save_as?: string;
  config?: Record<string, unknown>;
  return?: string;
}

export interface SetVariableData {
  name: string;
  value: unknown;
}

export interface TaskData {
  name?: string;
  instruction: string;
  save_as?: string;
  system_prompt?: string;
  enabled_tools?: string[];
}

// Parallel Format 2: same module with different parameter sets
export interface ParallelModuleData {
  module: string;
  parameters_list: Record<string, unknown>[] | string;
  save_results_as?: string;
  max_workers?: number;
}

export type NodeType =
  | 'start'
  | 'end'
  | 'step'
  | 'if'
  | 'while'
  | 'for_each'
  | 'switch'
  | 'gather'
  | 'call'
  | 'increment'
  | 'set_variable'
  | 'parallel'
  | 'input'
  | 'return'
  | 'task';

export interface BaseNodeData {
  label: string;
  nodeType: NodeType;
  [key: string]: unknown;
}

export interface StartNodeData extends BaseNodeData {
  nodeType: 'start';
  goal?: string;
  config?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  system_prompt?: string;
  submodules?: SubmoduleDeclaration[];
}

export interface StepNodeData extends BaseNodeData {
  nodeType: 'step';
  name: string;
  instruction?: string;
  save_as?: string;
  output_file?: string;
  enabled_tools?: string[];
}

export interface IfNodeData extends BaseNodeData {
  nodeType: 'if';
  condition: string;
  thenSteps?: FlowNodeData[];
  elseSteps?: FlowNodeData[];
}

export interface WhileNodeData extends BaseNodeData {
  nodeType: 'while';
  condition: string;
  max_iterations?: number;
  loopSteps?: FlowNodeData[];
}

export interface ForEachNodeData extends BaseNodeData {
  nodeType: 'for_each';
  variable: string;
  in: string | string[];
  max_iterations?: number;
  limit?: number;
  loopSteps?: FlowNodeData[];
}

export interface SwitchNodeData extends BaseNodeData {
  nodeType: 'switch';
  variable: string;
  cases?: Record<string, FlowNodeData[]>;
  defaultSteps?: FlowNodeData[];
}

export interface GatherNodeData extends BaseNodeData {
  nodeType: 'gather';
  // Format 1: Different modules
  calls?: GatherCall[];
  // Format 2: Same module with different parameters
  module?: string;
  parameters_list?: Record<string, unknown>[] | string;
  save_as_prefix?: string;
  save_as_list?: string[];
  // Common
  save_results_as?: string;
  max_workers?: number;
  config?: Record<string, unknown>;
  /** Per-node module YAML overrides (module path -> YAML content) */
  moduleContents?: Record<string, string>;
}

export interface ParallelNodeData extends BaseNodeData {
  nodeType: 'parallel';
  // Format 1: inline steps executed in parallel
  parallelSteps?: FlowNodeData[];
  // Format 2: same module with different parameter sets
  module?: string;
  parameters_list?: Record<string, unknown>[] | string;
  save_results_as?: string;
  max_workers?: number;
  /** Per-node module YAML overrides (module path -> YAML content) */
  moduleContents?: Record<string, string>;
}

export interface IncrementNodeData extends BaseNodeData {
  nodeType: 'increment';
  variable: string;
}

export interface SetVariableNodeData extends BaseNodeData {
  nodeType: 'set_variable';
  name: string;
  value: unknown;
}

export interface CallNodeData extends BaseNodeData {
  nodeType: 'call';
  module: string;
  parameters?: Record<string, unknown>;
  save_as?: string;
  config?: Record<string, unknown>;
  return?: string;
  /** Per-node module YAML overrides (module path -> YAML content) */
  moduleContents?: Record<string, string>;
}

export interface InputNodeData extends BaseNodeData {
  nodeType: 'input';
  prompt: string;
  save_as?: string;
  default?: string;
}

export interface ReturnNodeData extends BaseNodeData {
  nodeType: 'return';
  variable?: string;
}

export interface TaskNodeData extends BaseNodeData {
  nodeType: 'task';
  name?: string;
  instruction: string;
  save_as?: string;
  system_prompt?: string;
  enabled_tools?: string[];
}

export type FlowNodeData =
  | StartNodeData
  | StepNodeData
  | IfNodeData
  | WhileNodeData
  | ForEachNodeData
  | SwitchNodeData
  | GatherNodeData
  | ParallelNodeData
  | InputNodeData
  | ReturnNodeData
  | IncrementNodeData
  | SetVariableNodeData
  | CallNodeData
  | TaskNodeData
  | BaseNodeData;

export type FlowNode = Node<FlowNodeData>;
export type FlowEdge = Edge;

// Node Configuration
export interface NodeConfig {
  type: NodeType;
  label: string;
  color: string;
  borderColor: string;
  icon: string;
  defaultData: Partial<FlowNodeData>;
}

export const NODE_CONFIGS: Record<NodeType, NodeConfig> = {
  start: {
    type: 'start',
    label: 'Start',
    color: '#E8F5E9',
    borderColor: '#4CAF50',
    icon: 'Play',
    defaultData: { label: 'Start', nodeType: 'start' },
  },
  end: {
    type: 'end',
    label: 'End',
    color: '#FFEBEE',
    borderColor: '#F44336',
    icon: 'Square',
    defaultData: { label: 'End', nodeType: 'end' },
  },
  step: {
    type: 'step',
    label: 'Step (History)',
    color: '#E3F2FD',
    borderColor: '#1976D2',
    icon: 'MessageSquare',
    defaultData: { label: 'New Step', nodeType: 'step', name: 'new_step', instruction: '' },
  },
  if: {
    type: 'if',
    label: 'If Condition',
    color: '#FFE0B2',
    borderColor: '#E64A19',
    icon: 'GitBranch',
    defaultData: { label: 'If', nodeType: 'if', condition: '' },
  },
  while: {
    type: 'while',
    label: 'While Loop',
    color: '#F3E5F5',
    borderColor: '#7B1FA2',
    icon: 'RefreshCw',
    defaultData: { label: 'While', nodeType: 'while', condition: '', max_iterations: 10 },
  },
  for_each: {
    type: 'for_each',
    label: 'For Each',
    color: '#F3E5F5',
    borderColor: '#7B1FA2',
    icon: 'List',
    defaultData: { label: 'For Each', nodeType: 'for_each', variable: 'item', in: '[]' },
  },
  switch: {
    type: 'switch',
    label: 'Switch',
    color: '#FFE0B2',
    borderColor: '#E64A19',
    icon: 'GitMerge',
    defaultData: { label: 'Switch', nodeType: 'switch', variable: '' },
  },
  gather: {
    type: 'gather',
    label: 'Gather',
    color: '#C8E6C9',
    borderColor: '#388E3C',
    icon: 'Layers',
    defaultData: { label: 'Gather', nodeType: 'gather', calls: [], max_workers: 4 },
  },
  input: {
    type: 'input',
    label: 'Input',
    color: '#FFF8E1',
    borderColor: '#F9A825',
    icon: 'MessageCircle',
    defaultData: { label: 'Input', nodeType: 'input', prompt: '', save_as: 'user_input' },
  },
  return: {
    type: 'return',
    label: 'Return',
    color: '#E8EAF6',
    borderColor: '#3949AB',
    icon: 'ArrowRight',
    defaultData: { label: 'Return', nodeType: 'return', variable: 'prev_output' },
  },
  call: {
    type: 'call',
    label: 'Call Module',
    color: '#B3E5FC',
    borderColor: '#0277BD',
    icon: 'ExternalLink',
    defaultData: { label: 'Call', nodeType: 'call', module: '' },
  },
  increment: {
    type: 'increment',
    label: 'Increment',
    color: '#DCEDC8',
    borderColor: '#558B2F',
    icon: 'Plus',
    defaultData: { label: 'Increment', nodeType: 'increment', variable: 'counter' },
  },
  set_variable: {
    type: 'set_variable',
    label: 'Set Variable',
    color: '#DCEDC8',
    borderColor: '#558B2F',
    icon: 'Variable',
    defaultData: { label: 'Set Variable', nodeType: 'set_variable', name: 'variable', value: '' },
  },
  parallel: {
    type: 'parallel',
    label: 'Parallel',
    color: '#B2DFDB',
    borderColor: '#00796B',
    icon: 'GitFork',
    defaultData: { label: 'Parallel', nodeType: 'parallel', parallelSteps: [], max_workers: 4 },
  },
  task: {
    type: 'task',
    label: 'Task (Stateless)',
    color: '#E8EAF6',
    borderColor: '#5C6BC0',
    icon: 'FileText',
    defaultData: { label: 'New Task', nodeType: 'task', instruction: '' },
  },
};

// Draggable node types for sidebar
export const DRAGGABLE_NODES: NodeType[] = [
  'task',
  'step',
  'if',
  'while',
  'for_each',
  'switch',
  'parallel',
  'gather',
  'call',
  'set_variable',
  'increment',
  'input',
  'return',
];
