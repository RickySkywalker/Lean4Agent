import yaml from 'js-yaml';
import type { Workflow, FlowNodeData, WorkflowStep } from '../types';
import { flowNodeDataToWorkflowStep } from './workflowStepConverters';

/**
 * Update only the `workflow` section of a module YAML while preserving
 * name / goal / parameters / config and other top-level fields.
 */
export function updateModuleWorkflowYaml(
  originalContent: string,
  newSteps: FlowNodeData[],
): { yaml: string; workflow: Workflow | null } {
  let parsed: Workflow | null = null;
  try {
    parsed = yaml.load(originalContent) as Workflow | null;
  } catch {
    parsed = null;
  }

  if (!parsed || typeof parsed !== 'object') {
    parsed = {
      name: 'module',
      workflow: [],
    };
  }

  const workflow: WorkflowStep[] = newSteps.map((s) => flowNodeDataToWorkflowStep(s));

  const nextPlan: Workflow = {
    ...parsed,
    workflow,
  };

  const yamlText = yaml.dump(nextPlan, {
    indent: 2,
    lineWidth: 120,
    noRefs: true,
    sortKeys: false,
  });

  return { yaml: yamlText, workflow: nextPlan };
}

