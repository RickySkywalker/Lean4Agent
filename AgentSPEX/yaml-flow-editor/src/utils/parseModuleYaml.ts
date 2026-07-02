import yaml from 'js-yaml';
import type { ModuleTemplate, WorkflowStep } from '../components/Sidebar';

interface ParsedYaml {
  name?: string;
  goal?: string;
  parameters?: Record<string, unknown>;
  workflow?: unknown[];
}

function stepToWorkflowStep(entry: unknown): WorkflowStep | null {
  if (!entry || typeof entry !== 'object') return null;
  const obj = entry as Record<string, unknown>;
  if (obj.step && typeof obj.step === 'object') {
    const s = (obj.step as Record<string, unknown>).name;
    return { name: String(s ?? 'step'), type: 'step', description: undefined };
  }
  if (obj.call && typeof obj.call === 'object') {
    const m = (obj.call as Record<string, unknown>).module;
    return { name: String(m ?? 'call'), type: 'step', description: undefined };
  }
  if (obj.if) return { name: 'condition', type: 'if', description: undefined };
  if (obj.while) return { name: 'loop', type: 'while', description: undefined };
  if (obj.for_each) return { name: 'iterate', type: 'for_each', description: undefined };
  if (obj.switch) return { name: 'switch', type: 'switch', description: undefined };
  if (obj.parallel) return { name: 'parallel', type: 'parallel', description: undefined };
  if (obj.gather) return { name: 'gather', type: 'gather', description: undefined };
  if (obj.input) return { name: 'input', type: 'step', description: undefined };
  if (obj.return) return { name: 'return', type: 'step', description: undefined };
  if (obj.increment) return { name: String(obj.increment), type: 'step', description: undefined };
  if (obj.set_variable) return { name: (obj.set_variable as Record<string, unknown>)?.name as string || 'set_variable', type: 'step', description: undefined };
  return null;
}

/**
 * Parse a YAML string as a workflow / module and return a ModuleTemplate.
 * Used for uploaded submodules and folder import.
 */
export function parseModuleYaml(content: string, defaultPath: string): ModuleTemplate {
  const parsed = yaml.load(content) as ParsedYaml | null;
  if (!parsed || typeof parsed !== 'object') {
    return {
      name: defaultPath.replace(/^.*[/\\]/, '').replace(/\.(yaml|yml)$/i, '') || 'Module',
      path: defaultPath,
      description: 'Invalid or empty YAML',
      goal: '',
      defaultParams: {},
      workflow: [],
    };
  }

  const name =
    (typeof parsed.name === 'string' && parsed.name.trim()) ||
    defaultPath.replace(/^.*[/\\]/, '').replace(/\.(yaml|yml)$/i, '') ||
    'Module';
  const goal = typeof parsed.goal === 'string' ? parsed.goal : '';
  const parameters = parsed.parameters && typeof parsed.parameters === 'object'
    ? (Object.fromEntries(
        Object.entries(parsed.parameters).map(([k, v]) => [k, v != null ? String(v) : ''])
      ) as Record<string, string>)
    : {};
  const workflow: WorkflowStep[] = Array.isArray(parsed.workflow)
    ? parsed.workflow.map(stepToWorkflowStep).filter((s): s is WorkflowStep => s != null)
    : [];

  return {
    name,
    path: defaultPath,
    description: goal || undefined,
    goal,
    defaultParams: parameters,
    workflow,
  };
}

/**
 * Check if a parsed YAML looks like a main workflow (has workflow with multiple steps or is clearly a plan).
 */
export function looksLikeMainPlan(parsed: { name?: string; workflow?: unknown[] }): boolean {
  if (!parsed || typeof parsed !== 'object') return false;
  const w = parsed.workflow;
  if (!Array.isArray(w)) return false;
  return w.length >= 1;
}
