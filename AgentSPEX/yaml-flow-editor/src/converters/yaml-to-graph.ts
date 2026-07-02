import yaml from 'js-yaml';
import {
  Workflow,
  WorkflowStep,
  FlowNode,
  FlowEdge,
  FlowNodeData,
  StartNodeData,
  StepData,
  IfData,
  WhileData,
  ForEachData,
  SwitchData,
  GatherData,
  CallData,
  SetVariableData,
  ParallelModuleData,
  InputData,
  ReturnData,
  TaskData,
} from '../types';
import {
  workflowStepsToFlowNodeData,
  normalizeValue,
  normalizeObject,
} from '../utils/workflowStepConverters';

interface ConversionContext {
  nodes: FlowNode[];
  edges: FlowEdge[];
  nodeIdCounter: number;
  xPosition: number;
  yPosition: number;
}

const NODE_SPACING_Y = 140;

/** Add fields from `src` to `dst`, skipping undefined values. */
function assignDefined(dst: Record<string, unknown>, src: Record<string, unknown>): void {
  for (const [k, v] of Object.entries(src)) {
    if (v !== undefined) dst[k] = v;
  }
}

function getNextNodeId(ctx: ConversionContext, prefix: string = 'node'): string {
  return `${prefix}_${ctx.nodeIdCounter++}`;
}

function createNode(
  ctx: ConversionContext,
  type: string,
  data: FlowNodeData,
  position: { x: number; y: number }
): FlowNode {
  const id = getNextNodeId(ctx, type);
  const node: FlowNode = { id, type, position, data };
  ctx.nodes.push(node);
  return node;
}

function createEdge(
  ctx: ConversionContext,
  source: string,
  target: string,
  sourceHandle?: string,
  targetHandle?: string
): FlowEdge {
  const edge: FlowEdge = {
    id: `edge_${source}_${target}_${sourceHandle || 'default'}_${ctx.nodeIdCounter}`,
    source,
    target,
    sourceHandle,
    targetHandle,
    type: 'default',
  };
  ctx.edges.push(edge);
  return edge;
}

function processWorkflowStep(
  ctx: ConversionContext,
  step: WorkflowStep,
  baseX: number,
  baseY: number
): { node: FlowNode; endY: number } {

  if ('step' in step) {
    const stepData = step.step as StepData;
    const nodeData: Record<string, unknown> = {
      label: stepData.name ?? 'Step',
      nodeType: 'step',
      name: stepData.name ?? '',
    };
    // Optional fields: include only when present in YAML, converting null → ''
    if (stepData.instruction !== undefined) nodeData.instruction = stepData.instruction ?? '';
    if (stepData.save_as !== undefined) nodeData.save_as = stepData.save_as ?? '';
    if (stepData.output_file !== undefined) nodeData.output_file = stepData.output_file ?? '';
    if (stepData.enabled_tools !== undefined) nodeData.enabled_tools = stepData.enabled_tools;

    const node = createNode(ctx, 'step', nodeData as FlowNodeData, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('if' in step) {
    const ifData = step.if as IfData;
    const condition = normalizeValue(ifData.condition, 'true');

    const thenSteps = ifData.then?.length
      ? workflowStepsToFlowNodeData(ifData.then)
      : [];
    const elseSteps = ifData.else?.length
      ? workflowStepsToFlowNodeData(ifData.else)
      : [];

    const ifNode = createNode(ctx, 'if', {
      label: `If: ${condition.substring(0, 20)}${condition.length > 20 ? '...' : ''}`,
      nodeType: 'if',
      condition,
      thenSteps,
      elseSteps,
    } as FlowNodeData, { x: baseX, y: baseY });

    return { node: ifNode, endY: baseY + NODE_SPACING_Y };
  }

  if ('while' in step) {
    const whileData = step.while as WhileData;
    const condition = normalizeValue(whileData.condition, 'true');

    const loopSteps = whileData.steps?.length
      ? workflowStepsToFlowNodeData(whileData.steps)
      : [];

    const whileNode = createNode(ctx, 'while', {
      label: `While: ${condition.substring(0, 15)}${condition.length > 15 ? '...' : ''}`,
      nodeType: 'while',
      condition,
      max_iterations: whileData.max_iterations,
      loopSteps,
    } as FlowNodeData, { x: baseX, y: baseY });

    return { node: whileNode, endY: baseY + NODE_SPACING_Y };
  }

  if ('for_each' in step) {
    const forEachData = step.for_each as ForEachData;
    const variable = normalizeValue(forEachData.variable, 'item');

    const loopSteps = forEachData.steps?.length
      ? workflowStepsToFlowNodeData(forEachData.steps)
      : [];

    const forEachNode = createNode(ctx, 'for_each', {
      label: `For Each ${variable}`,
      nodeType: 'for_each',
      variable,
      in: forEachData.in || [],
      max_iterations: forEachData.max_iterations,
      limit: forEachData.limit,
      loopSteps,
    } as FlowNodeData, { x: baseX, y: baseY });

    return { node: forEachNode, endY: baseY + NODE_SPACING_Y };
  }

  if ('switch' in step) {
    const switchData = step.switch as SwitchData;
    const variable = normalizeValue(switchData.variable, 'value');

    const casesData: Record<string, FlowNodeData[]> = {};
    if (switchData.cases) {
      for (const [caseKey, caseSteps] of Object.entries(switchData.cases)) {
        casesData[caseKey] = caseSteps?.length
          ? workflowStepsToFlowNodeData(caseSteps)
          : [];
      }
    }

    const defaultSteps = switchData.default?.length
      ? workflowStepsToFlowNodeData(switchData.default)
      : [];

    const switchNode = createNode(ctx, 'switch', {
      label: `Switch: ${variable}`,
      nodeType: 'switch',
      variable,
      cases: casesData,
      defaultSteps,
    } as FlowNodeData, { x: baseX, y: baseY });
    return { node: switchNode, endY: baseY + NODE_SPACING_Y };
  }

  if ('gather' in step) {
    const gatherData = step.gather as GatherData;
    const node = createNode(ctx, 'gather', {
      label: 'Gather',
      nodeType: 'gather',
      calls: gatherData.calls || [],
      module: gatherData.module,
      parameters_list: gatherData.parameters_list,
      save_as_prefix: gatherData.save_as_prefix,
      save_as_list: gatherData.save_as_list,
      save_results_as: gatherData.save_results_as,
      max_workers: gatherData.max_workers,
      config: gatherData.config,
    }, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('input' in step) {
    const inputData = step.input as InputData;
    const prompt = normalizeValue(inputData.prompt, '');
    const node = createNode(ctx, 'input', {
      label: prompt.length > 25 ? `Input: ${prompt.substring(0, 25)}...` : `Input: ${prompt || 'user input'}`,
      nodeType: 'input',
      prompt: inputData.prompt ?? '',
      save_as: inputData.save_as ?? 'user_input',
      default: inputData.default,
    }, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('return' in step) {
    const ret = step.return;
    const variable = typeof ret === 'string' ? ret : (ret as ReturnData)?.variable ?? 'prev_output';
    const node = createNode(ctx, 'return', {
      label: `Return: ${variable}`,
      nodeType: 'return',
      variable: variable ?? 'prev_output',
    }, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('call' in step) {
    const callData = step.call as CallData;
    const module = callData.module ?? '';
    const moduleName = module.split('/').pop() || module || 'module';


    const nodeData: Record<string, unknown> = {
      label: `Call: ${moduleName}`,
      nodeType: 'call',
      module,
    };
    if (callData.parameters !== undefined) {
      nodeData.parameters = normalizeObject(callData.parameters || {});
    }
    assignDefined(nodeData, {
      save_as: callData.save_as,
      config: callData.config,
      return: callData.return,
    });

    const node = createNode(ctx, 'call', nodeData as FlowNodeData, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('increment' in step) {
    const variable = normalizeValue(step.increment as string, 'counter');
    const node = createNode(ctx, 'increment', {
      label: `Increment: ${variable}`,
      nodeType: 'increment',
      variable,
    }, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('set_variable' in step) {
    const data = step.set_variable as SetVariableData;
    const name = normalizeValue(data.name, 'variable');
    const node = createNode(ctx, 'set_variable', {
      label: `Set: ${name}`,
      nodeType: 'set_variable',
      name,
      value: data.value ?? '',
    }, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('parallel' in step) {
    const raw = step.parallel;

    // Format 1: inline step list
    if (Array.isArray(raw)) {
      const parallelSteps = workflowStepsToFlowNodeData(raw as WorkflowStep[]);
      const node = createNode(ctx, 'parallel', {
        label: `Parallel (${raw.length} steps)`,
        nodeType: 'parallel',
        parallelSteps,
      } as FlowNodeData, { x: baseX, y: baseY });
      return { node, endY: baseY + NODE_SPACING_Y };
    }

    // Format 2: module + parameter sets
    const data = raw as ParallelModuleData;
    const module = normalizeValue(data.module, '');
    const moduleName = module.split('/').pop() || module || 'module';
    const node = createNode(ctx, 'parallel', {
      label: `Parallel: ${moduleName}`,
      nodeType: 'parallel',
      module,
      parameters_list: data.parameters_list || [],
      save_results_as: normalizeValue(data.save_results_as, ''),
      max_workers: data.max_workers,
    } as FlowNodeData, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  if ('task' in step) {
    const taskData = step.task as TaskData;
    const nodeData: Record<string, unknown> = {
      label: taskData.name || 'Task',
      nodeType: 'task',
      instruction: taskData.instruction ?? '',
    };
    assignDefined(nodeData, {
      name: taskData.name,
      save_as: taskData.save_as,
      system_prompt: taskData.system_prompt,
      enabled_tools: taskData.enabled_tools,
    });

    const node = createNode(ctx, 'task', nodeData as FlowNodeData, { x: baseX, y: baseY });
    return { node, endY: baseY + NODE_SPACING_Y };
  }

  // Unknown step type — render as generic step
  const node = createNode(ctx, 'step', {
    label: 'Unknown Step',
    nodeType: 'step',
    name: 'unknown',
  }, { x: baseX, y: baseY });
  return { node, endY: baseY + NODE_SPACING_Y };
}

/** Process a sequence of workflow steps, creating nodes and connecting them with edges. */
function processWorkflowSequence(
  ctx: ConversionContext,
  steps: WorkflowStep[],
  baseX: number,
  startY: number,
  connectFromNodeId?: string,
  connectFromHandle?: string
): { firstNodeId: string | null; lastNodeId: string | null; endY: number } {

  if (steps.length === 0) {
    return { firstNodeId: null, lastNodeId: null, endY: startY };
  }

  let currentY = startY;
  let firstNodeId: string | null = null;
  let prevNodeId: string | null = null;
  let prevNodeType: string | null = null;

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const { node, endY } = processWorkflowStep(ctx, step, baseX, currentY);

    if (!firstNodeId) {
      firstNodeId = node.id;
      if (connectFromNodeId) {
        createEdge(ctx, connectFromNodeId, node.id, connectFromHandle);
      }
    }

    if (prevNodeId) {
      const useNextHandle = prevNodeType === 'if' || prevNodeType === 'while' || prevNodeType === 'for_each';
      createEdge(ctx, prevNodeId, node.id, useNextHandle ? 'next' : undefined);
    }

    prevNodeId = node.id;
    prevNodeType = node.type || null;
    currentY = endY;
  }

  return { firstNodeId, lastNodeId: prevNodeId, endY: currentY };
}

/** Parse a YAML workflow string and convert it into a graph of FlowNodes and FlowEdges. */
export function yamlToGraph(yamlContent: string): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const ctx: ConversionContext = {
    nodes: [],
    edges: [],
    nodeIdCounter: 0,
    xPosition: 250,
    yPosition: 50,
  };

  const workflow = yaml.load(yamlContent) as Workflow;

  if (!workflow || !workflow.workflow) {
    return { nodes: [], edges: [] };
  }

  // Start node (also stores workflow-level system_prompt / submodules)
  const startNodeData: Record<string, unknown> = {
    label: workflow.name || 'Start',
    nodeType: 'start',
  };
  assignDefined(startNodeData, {
    goal: workflow.goal,
    config: normalizeObject(workflow.config),
    parameters: normalizeObject(workflow.parameters),
    system_prompt: workflow.system_prompt,
    submodules: workflow.submodules,
  });
  const startNode = createNode(ctx, 'start', startNodeData as StartNodeData, { x: 250, y: 50 });

  const { firstNodeId, lastNodeId, endY } = processWorkflowSequence(
    ctx,
    workflow.workflow,
    250,
    50 + NODE_SPACING_Y
  );

  if (firstNodeId) {
    createEdge(ctx, startNode.id, firstNodeId);
  }

  const endNode = createNode(ctx, 'end', {
    label: 'End',
    nodeType: 'end',
  }, { x: 250, y: endY });

  if (lastNodeId) {
    const lastNode = ctx.nodes.find(n => n.id === lastNodeId);
    const useNextHandle = lastNode?.type === 'if' || lastNode?.type === 'while' || lastNode?.type === 'for_each';
    createEdge(ctx, lastNodeId, endNode.id, useNextHandle ? 'next' : undefined);
  } else {
    createEdge(ctx, startNode.id, endNode.id);
  }

  return { nodes: ctx.nodes, edges: ctx.edges };
}
