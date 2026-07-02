import yaml from 'js-yaml';
import {
  FlowNode,
  FlowEdge,
  FlowNodeData,
  Workflow,
  WorkflowStep,
  StepNodeData,
  IfNodeData,
  WhileNodeData,
  ForEachNodeData,
  SwitchNodeData,
  GatherNodeData,
  ParallelNodeData,
  CallNodeData,
  InputNodeData,
  ReturnNodeData,
  TaskNodeData,
  StartNodeData,
} from '../types';
import { flowNodeDataToWorkflowStep } from '../utils/workflowStepConverters';

interface ConversionContext {
  nodes: Map<string, FlowNode>;
  outgoingEdges: Map<string, FlowEdge[]>;
  incomingEdges: Map<string, FlowEdge[]>;
}

/** Copy fields from src to dst only when explicitly defined (not undefined). */
function copyDefined<T extends Record<string, unknown>>(
  dst: T,
  src: Record<string, unknown>,
  ...fields: string[]
): void {
  for (const f of fields) {
    if (f in src && src[f] !== undefined) {
      (dst as Record<string, unknown>)[f] = src[f];
    }
  }
}

function buildContext(nodes: FlowNode[], edges: FlowEdge[]): ConversionContext {
  const ctx: ConversionContext = {
    nodes: new Map(),
    outgoingEdges: new Map(),
    incomingEdges: new Map(),
  };

  for (const node of nodes) {
    ctx.nodes.set(node.id, node);
  }

  for (const edge of edges) {
    if (!ctx.outgoingEdges.has(edge.source)) {
      ctx.outgoingEdges.set(edge.source, []);
    }
    ctx.outgoingEdges.get(edge.source)!.push(edge);

    if (!ctx.incomingEdges.has(edge.target)) {
      ctx.incomingEdges.set(edge.target, []);
    }
    ctx.incomingEdges.get(edge.target)!.push(edge);
  }

  return ctx;
}

function findStartNode(ctx: ConversionContext): FlowNode | null {
  for (const node of ctx.nodes.values()) {
    if (node.type === 'start') {
      return node;
    }
  }
  return null;
}

function getNextNode(ctx: ConversionContext, nodeId: string): FlowNode | null {
  const edges = ctx.outgoingEdges.get(nodeId) || [];

  const defaultEdge = edges.find((e) => !e.sourceHandle || e.sourceHandle === 'bottom');
  if (defaultEdge) {
    return ctx.nodes.get(defaultEdge.target) || null;
  }

  if (edges.length > 0) {
    return ctx.nodes.get(edges[0].target) || null;
  }

  return null;
}

function getOutgoingEdges(ctx: ConversionContext, nodeId: string): FlowEdge[] {
  return ctx.outgoingEdges.get(nodeId) || [];
}

/**
 * Resolve branch steps: prefer inline container steps over edge-connected legacy steps.
 */
function resolveBranchSteps(
  inlineSteps: FlowNodeData[] | undefined,
  ctx: ConversionContext,
  edges: FlowEdge[],
  handleName: string,
  visited: Set<string>,
): WorkflowStep[] {
  if (inlineSteps && inlineSteps.length > 0) {
    return inlineSteps.map((s) => flowNodeDataToWorkflowStep(s));
  }
  const edge = edges.find((e) => e.sourceHandle === handleName);
  return edge ? traverseBranch(ctx, edge.target, new Set(visited)) : [];
}

function convertNodeToStep(
  ctx: ConversionContext,
  node: FlowNode,
  visited: Set<string>,
): { step: WorkflowStep | null; nextNodeId: string | null } {
  const data = node.data;

  switch (node.type) {
    case 'step': {
      const stepData = data as StepNodeData;
      const step: Record<string, unknown> = {
        name: stepData.name ?? '',
      };
      copyDefined(step, stepData as Record<string, unknown>, 'instruction', 'save_as', 'output_file', 'enabled_tools');

      const nextNode = getNextNode(ctx, node.id);
      return {
        step: { step: step as { name: string; instruction?: string; save_as?: string; output_file?: string } },
        nextNodeId: nextNode?.id ?? null,
      };
    }

    case 'task': {
      const taskData = data as TaskNodeData;
      const task: Record<string, unknown> = {
        instruction: taskData.instruction ?? '',
      };
      copyDefined(task, taskData as Record<string, unknown>, 'name', 'save_as', 'system_prompt', 'enabled_tools');

      const nextNode = getNextNode(ctx, node.id);
      return {
        step: { task: task as { instruction: string; name?: string; save_as?: string } },
        nextNodeId: nextNode?.id ?? null,
      };
    }

    case 'if': {
      const ifData = data as IfNodeData;
      const edges = getOutgoingEdges(ctx, node.id);
      const nextEdge = edges.find((e) => e.sourceHandle === 'next');

      const thenSteps = resolveBranchSteps(ifData.thenSteps, ctx, edges, 'true', visited);
      const elseSteps = resolveBranchSteps(ifData.elseSteps, ctx, edges, 'false', visited);

      const ifStep: Record<string, unknown> = {
        condition: ifData.condition ?? '',
      };
      if (thenSteps.length > 0) ifStep.then = thenSteps;
      if (elseSteps.length > 0) ifStep.else = elseSteps;

      return {
        step: { if: ifStep as { condition: string; then?: WorkflowStep[]; else?: WorkflowStep[] } },
        nextNodeId: nextEdge?.target ?? null,
      };
    }

    case 'while': {
      const whileData = data as WhileNodeData;
      const edges = getOutgoingEdges(ctx, node.id);
      const nextEdge = edges.find((e) => e.sourceHandle === 'next');

      const bodySteps = resolveBranchSteps(whileData.loopSteps, ctx, edges, 'loop', visited);

      const whileStep: Record<string, unknown> = {
        condition: whileData.condition ?? '',
        steps: bodySteps,
      };
      if (whileData.max_iterations) whileStep.max_iterations = whileData.max_iterations;

      return {
        step: { while: whileStep as { condition: string; steps: WorkflowStep[]; max_iterations?: number } },
        nextNodeId: nextEdge?.target ?? null,
      };
    }

    case 'for_each': {
      const forEachData = data as ForEachNodeData;
      const edges = getOutgoingEdges(ctx, node.id);
      const nextEdge = edges.find((e) => e.sourceHandle === 'next');

      const bodySteps = resolveBranchSteps(forEachData.loopSteps, ctx, edges, 'loop', visited);

      const forEachStep: Record<string, unknown> = {
        variable: forEachData.variable ?? '',
        in: forEachData.in ?? [],
        steps: bodySteps,
      };
      if (forEachData.max_iterations) forEachStep.max_iterations = forEachData.max_iterations;
      if (forEachData.limit) forEachStep.limit = forEachData.limit;

      return {
        step: { for_each: forEachStep as { variable: string; in: string | string[]; steps: WorkflowStep[]; max_iterations?: number } },
        nextNodeId: nextEdge?.target ?? null,
      };
    }

    case 'switch': {
      const switchData = data as SwitchNodeData;
      const edges = getOutgoingEdges(ctx, node.id);
      const nextEdge = edges.find((e) => e.sourceHandle === 'next');

      const casesOutput: Record<string, WorkflowStep[]> = {};
      if (switchData.cases) {
        for (const [caseKey, caseSteps] of Object.entries(switchData.cases)) {
          casesOutput[caseKey] = caseSteps?.length
            ? caseSteps.map((s) => flowNodeDataToWorkflowStep(s))
            : [];
        }
      }

      const defaultOutput = switchData.defaultSteps?.length
        ? switchData.defaultSteps.map((s) => flowNodeDataToWorkflowStep(s))
        : [];

      const switchStep: Record<string, unknown> = {
        variable: switchData.variable ?? '',
        cases: casesOutput,
      };
      if (defaultOutput.length > 0) switchStep.default = defaultOutput;

      return {
        step: { switch: switchStep as { variable: string; cases: Record<string, WorkflowStep[]>; default?: WorkflowStep[] } },
        nextNodeId: nextEdge?.target ?? null,
      };
    }

    case 'gather': {
      const gatherData = data as GatherNodeData;
      const gather: Record<string, unknown> = {};

      if (gatherData.calls && gatherData.calls.length > 0) {
        gather.calls = gatherData.calls;
      } else if (gatherData.module) {
        gather.module = gatherData.module;
        copyDefined(gather, gatherData as Record<string, unknown>, 'parameters_list', 'save_as_prefix', 'save_as_list');
      }

      copyDefined(gather, gatherData as Record<string, unknown>, 'save_results_as', 'max_workers');
      if (gatherData.config && Object.keys(gatherData.config).length > 0) {
        gather.config = gatherData.config;
      }

      const nextNode = getNextNode(ctx, node.id);
      return { step: { gather }, nextNodeId: nextNode?.id ?? null };
    }

    case 'input': {
      const inputData = data as InputNodeData;
      const input: Record<string, unknown> = { prompt: inputData.prompt ?? '' };
      copyDefined(input, inputData as Record<string, unknown>, 'save_as');
      if (inputData.default !== undefined) input.default = inputData.default;
      const nextNode = getNextNode(ctx, node.id);
      return { step: { input: input as unknown as import('../types').InputData }, nextNodeId: nextNode?.id ?? null };
    }

    case 'return': {
      const variable = (data as ReturnNodeData).variable ?? 'prev_output';
      const nextNode = getNextNode(ctx, node.id);
      return { step: { return: variable }, nextNodeId: nextNode?.id ?? null };
    }

    case 'call': {
      const callData = data as CallNodeData;
      const call: Record<string, unknown> = {
        module: callData.module ?? '',
      };
      if (callData.parameters && Object.keys(callData.parameters).length > 0) {
        const normalizedParams: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(callData.parameters)) {
          normalizedParams[key] = value ?? '';
        }
        call.parameters = normalizedParams;
      }
      copyDefined(call, callData as Record<string, unknown>, 'save_as', 'return');
      if (callData.config && Object.keys(callData.config).length > 0) {
        call.config = callData.config;
      }

      const nextNode = getNextNode(ctx, node.id);
      return {
        step: { call: call as { module: string; parameters?: Record<string, unknown>; save_as?: string } },
        nextNodeId: nextNode?.id ?? null,
      };
    }

    case 'increment': {
      const variable = ((data as Record<string, unknown>).variable as string) ?? '';
      const nextNode = getNextNode(ctx, node.id);
      return { step: { increment: variable }, nextNodeId: nextNode?.id ?? null };
    }

    case 'set_variable': {
      const nextNode = getNextNode(ctx, node.id);
      return {
        step: {
          set_variable: {
            name: ((data as Record<string, unknown>).name as string) ?? '',
            value: (data as Record<string, unknown>).value ?? '',
          },
        },
        nextNodeId: nextNode?.id ?? null,
      };
    }

    case 'parallel': {
      const parallelData = data as ParallelNodeData;
      const nextNode = getNextNode(ctx, node.id);

      if (parallelData.parallelSteps && parallelData.parallelSteps.length > 0) {
        const steps = parallelData.parallelSteps.map((s) => flowNodeDataToWorkflowStep(s));
        return { step: { parallel: steps }, nextNodeId: nextNode?.id ?? null };
      }

      const parallel: Record<string, unknown> = {};
      copyDefined(parallel, parallelData as Record<string, unknown>, 'module', 'parameters_list', 'max_workers', 'save_results_as');

      return {
        step: { parallel: parallel as unknown as import('../types').ParallelModuleData },
        nextNodeId: nextNode?.id ?? null,
      };
    }

    case 'start':
    case 'end':
      return { step: null, nextNodeId: null };

    default:
      return { step: null, nextNodeId: null };
  }
}

/** Traverse a linear chain of nodes (for branches inside control flow). */
function traverseBranch(
  ctx: ConversionContext,
  startNodeId: string | null,
  visited: Set<string>,
): WorkflowStep[] {
  const steps: WorkflowStep[] = [];
  let currentId: string | null = startNodeId;

  while (currentId && !visited.has(currentId)) {
    const node = ctx.nodes.get(currentId);
    if (!node || node.type === 'end') break;

    visited.add(currentId);

    const { step, nextNodeId } = convertNodeToStep(ctx, node, visited);
    if (step) steps.push(step);

    currentId = nextNodeId;
  }

  return steps;
}

function traverseWorkflow(ctx: ConversionContext, startNodeId: string): WorkflowStep[] {
  const visited = new Set<string>();
  const workflow: WorkflowStep[] = [];
  let currentId: string | null = startNodeId;

  const startNode = ctx.nodes.get(startNodeId);
  if (startNode?.type === 'start') {
    visited.add(startNodeId);
    const nextNode = getNextNode(ctx, startNodeId);
    currentId = nextNode?.id ?? null;
  }

  while (currentId && !visited.has(currentId)) {
    const node = ctx.nodes.get(currentId);
    if (!node || node.type === 'end') break;

    visited.add(currentId);

    const { step, nextNodeId } = convertNodeToStep(ctx, node, visited);
    if (step) workflow.push(step);

    currentId = nextNodeId;
  }

  return workflow;
}

export function graphToYaml(nodes: FlowNode[], edges: FlowEdge[]): string {
  if (nodes.length === 0) return '';

  const ctx = buildContext(nodes, edges);
  const startNode = findStartNode(ctx);

  let taskName = 'my_task';
  let startNodeId: string;

  if (startNode) {
    taskName = (startNode.data.label || 'my_task').replace(/^Start:?\s*/i, '').trim() || 'my_task';
    startNodeId = startNode.id;
  } else {
    const firstNode = nodes[0];
    if (!firstNode) return '';
    startNodeId = firstNode.id;
  }

  if (!taskName || taskName === 'my_task') {
    const rand = Math.random().toString(36).slice(2, 10);
    taskName = `ui_task_${rand}`;
  }

  const steps = traverseWorkflow(ctx, startNodeId);

  const workflow: Workflow = {
    name: taskName,
    goal: 'Generated from visual editor',
    workflow: steps,
  };

  if (startNode) {
    const sd = startNode.data as StartNodeData;
    if (sd.goal !== undefined) workflow.goal = sd.goal;
    if (sd.system_prompt) workflow.system_prompt = sd.system_prompt;
    if (sd.config && Object.keys(sd.config).length > 0) workflow.config = sd.config;
    if (sd.parameters && Object.keys(sd.parameters).length > 0) workflow.parameters = sd.parameters;
    if (sd.submodules && sd.submodules.length > 0) workflow.submodules = sd.submodules;
  }

  return yaml.dump(cleanObject(workflow), {
    indent: 2,
    lineWidth: 120,
    noRefs: true,
    sortKeys: false,
  });
}

/** Recursively strip undefined values; convert null to empty string to preserve keys. */
function cleanObject(obj: unknown): unknown {
  if (obj === undefined) return undefined;
  if (obj === null) return '';

  if (Array.isArray(obj)) {
    return obj.map((item) => cleanObject(item)).filter((item) => item !== undefined);
  }

  if (typeof obj === 'object') {
    const cleaned: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const cleanedValue = cleanObject(value);
      if (cleanedValue !== undefined) cleaned[key] = cleanedValue;
    }
    return Object.keys(cleaned).length > 0 ? cleaned : undefined;
  }

  return obj;
}
