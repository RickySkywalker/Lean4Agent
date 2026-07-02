import {
  WorkflowStep,
  FlowNodeData,
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
  StepNodeData,
  CallNodeData,
  TaskNodeData,
  IfNodeData,
  WhileNodeData,
  ForEachNodeData,
  SwitchNodeData,
  GatherNodeData,
  ParallelNodeData,
  InputNodeData,
  ReturnNodeData,
  IncrementNodeData,
  SetVariableNodeData,
} from '../types';

/**
 * Normalize null/undefined to a default value.
 */
export function normalizeValue<T>(value: T | null | undefined, defaultValue: T): T {
  if (value === null || value === undefined) {
    return defaultValue;
  }
  return value;
}

/**
 * Recursively normalize an object, converting null/undefined leaves to empty strings.
 */
export function normalizeObject<T extends Record<string, unknown>>(obj: T | null | undefined): T {
  if (!obj) return {} as T;
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined) {
      result[key] = '';
    } else if (typeof value === 'object' && !Array.isArray(value)) {
      result[key] = normalizeObject(value as Record<string, unknown>);
    } else {
      result[key] = value;
    }
  }
  return result as T;
}

/** Add fields to a record only if they have a defined value. */
function addOptional(obj: Record<string, unknown>, fields: Record<string, unknown>): void {
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined) obj[k] = v;
  }
}

/** Convert nested FlowNodeData[] via recursive map, defaulting to []. */
function convertNestedSteps(steps: FlowNodeData[] | undefined): WorkflowStep[] {
  return steps && steps.length > 0
    ? steps.map((s) => flowNodeDataToWorkflowStep(s))
    : [];
}

/**
 * Convert a single WorkflowStep (YAML-level) into FlowNodeData (editor-level).
 */
export function workflowStepToFlowNodeData(step: WorkflowStep): FlowNodeData {
  if ('step' in step) {
    const stepData = step.step as StepData;
    return {
      label: stepData.name || 'Step',
      nodeType: 'step',
      name: stepData.name ?? '',
      instruction: stepData.instruction,
      save_as: stepData.save_as,
      enabled_tools: stepData.enabled_tools,
    } as FlowNodeData;
  }

  if ('task' in step) {
    const taskData = step.task as TaskData;
    return {
      label: taskData.name || 'Task',
      nodeType: 'task',
      instruction: taskData.instruction ?? '',
      name: taskData.name,
      save_as: taskData.save_as,
      system_prompt: taskData.system_prompt,
      enabled_tools: taskData.enabled_tools,
    } as FlowNodeData;
  }

  if ('call' in step) {
    const callData = step.call as CallData;
    return {
      label: `Call: ${callData.module}`,
      nodeType: 'call',
      module: callData.module ?? '',
      parameters: callData.parameters || {},
      save_as: callData.save_as,
      config: callData.config,
      return: callData.return,
    } as FlowNodeData;
  }

  if ('input' in step) {
    const inputData = step.input as InputData;
    const prompt = normalizeValue(inputData.prompt, '');
    return {
      label: `Input: ${prompt.substring(0, 30)}${prompt.length > 30 ? '...' : ''}`,
      nodeType: 'input',
      prompt: inputData.prompt ?? '',
      save_as: inputData.save_as,
      default: inputData.default,
    } as FlowNodeData;
  }

  if ('return' in step) {
    const ret = step.return;
    const variable = typeof ret === 'string' ? ret : (ret as ReturnData)?.variable ?? 'prev_output';
    return {
      label: `Return: ${variable}`,
      nodeType: 'return',
      variable: variable ?? 'prev_output',
    } as FlowNodeData;
  }

  if ('if' in step) {
    const ifData = step.if as IfData;
    const condition = normalizeValue(ifData.condition, 'true');
    return {
      label: `If: ${condition.substring(0, 20)}${condition.length > 20 ? '...' : ''}`,
      nodeType: 'if',
      condition,
      thenSteps: workflowStepsToFlowNodeData(ifData.then ?? []),
      elseSteps: workflowStepsToFlowNodeData(ifData.else ?? []),
    } as FlowNodeData;
  }

  if ('while' in step) {
    const whileData = step.while as WhileData;
    const condition = normalizeValue(whileData.condition, 'true');
    return {
      label: `While: ${condition.substring(0, 15)}${condition.length > 15 ? '...' : ''}`,
      nodeType: 'while',
      condition,
      max_iterations: whileData.max_iterations,
      loopSteps: workflowStepsToFlowNodeData(whileData.steps ?? []),
    } as FlowNodeData;
  }

  if ('for_each' in step) {
    const forEachData = step.for_each as ForEachData;
    const variable = normalizeValue(forEachData.variable, 'item');
    return {
      label: `For Each ${variable}`,
      nodeType: 'for_each',
      variable,
      in: forEachData.in || [],
      max_iterations: forEachData.max_iterations,
      limit: forEachData.limit,
      loopSteps: workflowStepsToFlowNodeData(forEachData.steps ?? []),
    } as FlowNodeData;
  }

  if ('switch' in step) {
    const switchData = step.switch as SwitchData;
    const variable = normalizeValue(switchData.variable, 'value');
    const casesData: Record<string, FlowNodeData[]> = {};
    if (switchData.cases) {
      for (const [caseKey, caseSteps] of Object.entries(switchData.cases)) {
        casesData[caseKey] = workflowStepsToFlowNodeData(caseSteps ?? []);
      }
    }
    return {
      label: `Switch: ${variable}`,
      nodeType: 'switch',
      variable,
      cases: casesData,
      defaultSteps: workflowStepsToFlowNodeData(switchData.default ?? []),
    } as FlowNodeData;
  }

  if ('increment' in step) {
    const variable = normalizeValue(step.increment as string, 'counter');
    return {
      label: `Increment: ${variable}`,
      nodeType: 'increment',
      variable,
    } as FlowNodeData;
  }

  if ('set_variable' in step) {
    const data = step.set_variable as SetVariableData;
    return {
      label: `Set: ${data.name ?? 'variable'}`,
      nodeType: 'set_variable',
      name: data.name ?? 'variable',
      value: data.value ?? '',
    } as FlowNodeData;
  }

  if ('parallel' in step) {
    const raw = step.parallel;

    if (Array.isArray(raw)) {
      const parallelSteps = workflowStepsToFlowNodeData(raw as WorkflowStep[]);
      return {
        label: `Parallel (${raw.length} steps)`,
        nodeType: 'parallel',
        parallelSteps,
      } as FlowNodeData;
    }

    const data = raw as ParallelModuleData;
    const module = normalizeValue(data.module, '');
    return {
      label: `Parallel: ${module.split('/').pop() || module || 'module'}`,
      nodeType: 'parallel',
      module,
      parameters_list: data.parameters_list ?? [],
      save_results_as: data.save_results_as,
      max_workers: data.max_workers,
    } as FlowNodeData;
  }

  if ('gather' in step) {
    const data = step.gather as GatherData;
    return {
      label: 'Gather',
      nodeType: 'gather',
      calls: data.calls || [],
      module: data.module,
      parameters_list: data.parameters_list,
      save_as_prefix: data.save_as_prefix,
      save_as_list: data.save_as_list,
      save_results_as: data.save_results_as,
      max_workers: data.max_workers,
      config: data.config,
    } as FlowNodeData;
  }

  return {
    label: 'Unknown Step',
    nodeType: 'step',
    name: 'unknown',
  } as FlowNodeData;
}

/** Convert an array of WorkflowStep to FlowNodeData[]. */
export function workflowStepsToFlowNodeData(steps: WorkflowStep[]): FlowNodeData[] {
  return steps.map((s) => workflowStepToFlowNodeData(s));
}

/*
 * The `as unknown as WorkflowStep` casts below are necessary because WorkflowStep
 * is a discriminated union and TypeScript cannot narrow a constructed Record literal
 * to a specific union member. The runtime shape is always correct.
 */

/** Convert FlowNodeData back to a WorkflowStep (used by graph-to-yaml and submodule editors). */
export function flowNodeDataToWorkflowStep(stepData: FlowNodeData): WorkflowStep {
  const nodeType = stepData.nodeType;

  switch (nodeType) {
    case 'step': {
      const d = stepData as StepNodeData;
      const step: Record<string, unknown> = { name: d.name ?? 'step' };
      addOptional(step, {
        instruction: d.instruction,
        save_as: d.save_as,
        output_file: d.output_file,
        enabled_tools: d.enabled_tools,
      });
      return { step } as unknown as WorkflowStep;
    }
    case 'task': {
      const d = stepData as TaskNodeData;
      const task: Record<string, unknown> = { instruction: d.instruction ?? '' };
      addOptional(task, {
        name: d.name,
        save_as: d.save_as,
        system_prompt: d.system_prompt,
        enabled_tools: d.enabled_tools,
      });
      return { task } as unknown as WorkflowStep;
    }
    case 'call': {
      const d = stepData as CallNodeData;
      const call: Record<string, unknown> = { module: d.module ?? '' };
      if (d.parameters && Object.keys(d.parameters).length > 0) {
        const normalizedParams: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(d.parameters)) {
          normalizedParams[key] = value ?? '';
        }
        call.parameters = normalizedParams;
      }
      addOptional(call, { save_as: d.save_as, return: d.return });
      if (d.config && Object.keys(d.config).length > 0) call.config = d.config;
      return { call } as unknown as WorkflowStep;
    }
    case 'input': {
      const d = stepData as InputNodeData;
      const input: Record<string, unknown> = { prompt: d.prompt ?? '' };
      addOptional(input, { save_as: d.save_as, default: d.default });
      return { input } as unknown as WorkflowStep;
    }
    case 'return': {
      const variable = (stepData as ReturnNodeData).variable ?? 'prev_output';
      return { return: variable } as unknown as WorkflowStep;
    }
    case 'increment': {
      const variable = (stepData as IncrementNodeData).variable ?? 'counter';
      return { increment: variable } as unknown as WorkflowStep;
    }
    case 'set_variable': {
      const d = stepData as SetVariableNodeData;
      return {
        set_variable: { name: d.name ?? 'variable', value: d.value ?? '' },
      } as unknown as WorkflowStep;
    }
    case 'parallel': {
      const d = stepData as ParallelNodeData;

      if (d.parallelSteps && d.parallelSteps.length > 0) {
        return { parallel: convertNestedSteps(d.parallelSteps) } as unknown as WorkflowStep;
      }

      const parallel: Record<string, unknown> = {};
      addOptional(parallel, {
        module: d.module,
        parameters_list: d.parameters_list,
        save_results_as: d.save_results_as,
        max_workers: d.max_workers,
      });
      return { parallel } as unknown as WorkflowStep;
    }
    case 'gather': {
      const d = stepData as GatherNodeData;
      const gather: Record<string, unknown> = {};
      if (d.calls?.length) {
        gather.calls = d.calls;
      } else if (d.module) {
        gather.module = d.module;
        addOptional(gather, {
          parameters_list: d.parameters_list,
          save_as_prefix: d.save_as_prefix,
          save_as_list: d.save_as_list,
        });
      }
      addOptional(gather, {
        save_results_as: d.save_results_as,
        max_workers: d.max_workers,
      });
      if (d.config && Object.keys(d.config).length > 0) gather.config = d.config;
      return { gather } as unknown as WorkflowStep;
    }
    case 'if': {
      const d = stepData as IfNodeData;
      const ifStep: Record<string, unknown> = { condition: d.condition ?? '' };
      const thenSteps = convertNestedSteps(d.thenSteps);
      const elseSteps = convertNestedSteps(d.elseSteps);
      if (thenSteps.length > 0) ifStep.then = thenSteps;
      if (elseSteps.length > 0) ifStep.else = elseSteps;
      return { if: ifStep } as unknown as WorkflowStep;
    }
    case 'while': {
      const d = stepData as WhileNodeData;
      const whileStep: Record<string, unknown> = {
        condition: d.condition ?? '',
        steps: convertNestedSteps(d.loopSteps),
      };
      addOptional(whileStep, { max_iterations: d.max_iterations });
      return { while: whileStep } as unknown as WorkflowStep;
    }
    case 'for_each': {
      const d = stepData as ForEachNodeData;
      const forEachStep: Record<string, unknown> = {
        variable: d.variable ?? '',
        in: d.in ?? [],
        steps: convertNestedSteps(d.loopSteps),
      };
      addOptional(forEachStep, {
        max_iterations: d.max_iterations,
        limit: d.limit,
      });
      return { for_each: forEachStep } as unknown as WorkflowStep;
    }
    case 'switch': {
      const d = stepData as SwitchNodeData;
      const casesOutput: Record<string, WorkflowStep[]> = {};
      if (d.cases) {
        for (const [caseKey, caseSteps] of Object.entries(d.cases)) {
          casesOutput[caseKey] = convertNestedSteps(caseSteps);
        }
      }
      const switchStep: Record<string, unknown> = {
        variable: d.variable ?? '',
        cases: casesOutput,
      };
      const defaultOutput = convertNestedSteps(d.defaultSteps);
      if (defaultOutput.length > 0) switchStep.default = defaultOutput;
      return { switch: switchStep } as unknown as WorkflowStep;
    }
    default:
      return {
        step: { name: (stepData as Record<string, unknown>).label || nodeType },
      } as unknown as WorkflowStep;
  }
}
