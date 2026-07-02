import yamlLib from 'js-yaml';
import type { FlowNode, WorkflowStep } from '../types';

/**
 * Recursively collect all submodule dependencies referenced by a main YAML plan.
 *
 * Returns a Map of modulePath → yamlContent for every transitively-referenced module.
 */
export function collectDependentModules(
  mainYaml: string,
  modulesByPath: Record<string, { content: string }>,
  nodes: FlowNode[],
): Map<string, string> {
  const result = new Map<string, string>();
  const visited = new Set<string>();

  // Collect per-node moduleContents overrides (call/parallel/gather nodes)
  const nodeOverrides: Record<string, string> = {};
  for (const node of nodes) {
    const data = node.data as Record<string, unknown>;
    const mc = data.moduleContents as Record<string, string> | undefined;
    if (mc) {
      for (const [path, content] of Object.entries(mc)) {
        nodeOverrides[path] = content;
      }
    }
  }

  // Resolve module content by path: node overrides > global modulesByPath (with normalization)
  function resolveContent(modulePath: string): string | undefined {
    if (nodeOverrides[modulePath]) return nodeOverrides[modulePath];

    // Direct lookup
    if (modulesByPath[modulePath]) return modulesByPath[modulePath].content;

    // Normalize: strip leading ./
    const stripped = modulePath.replace(/^\.\//, '');
    if (modulesByPath[stripped]) return modulesByPath[stripped].content;

    // Strip workflows/ prefix
    const noPrefix = stripped.replace(/^workflows\//, '');
    if (modulesByPath[noPrefix]) return modulesByPath[noPrefix].content;

    // Suffix match: find any key ending with the path
    const keys = Object.keys(modulesByPath);
    const suffixMatch = keys.find(
      (k) => k.endsWith('/' + stripped) || k.endsWith('/' + noPrefix),
    );
    if (suffixMatch) return modulesByPath[suffixMatch].content;

    return undefined;
  }

  // Extract module paths from a list of workflow steps
  function extractModulePaths(steps: WorkflowStep[]): string[] {
    const paths: string[] = [];
    for (const step of steps) {
      if ('call' in step && step.call) {
        const c = step.call as { module?: string };
        if (c.module) paths.push(c.module);
      }
      if ('parallel' in step && step.parallel) {
        const p = step.parallel as { module?: string };
        if (p.module) paths.push(p.module);
      }
      if ('gather' in step && step.gather) {
        const g = step.gather as {
          module?: string;
          calls?: Array<{ module?: string }>;
        };
        // Format 2: single module
        if (g.module) paths.push(g.module);
        // Format 1: calls array
        if (g.calls) {
          for (const call of g.calls) {
            if (call.module) paths.push(call.module);
          }
        }
      }
      // Recurse into control flow bodies
      if ('if' in step && step.if) {
        const ifData = step.if as {
          then?: WorkflowStep[];
          else?: WorkflowStep[];
        };
        if (ifData.then) paths.push(...extractModulePaths(ifData.then));
        if (ifData.else) paths.push(...extractModulePaths(ifData.else));
      }
      if ('while' in step && step.while) {
        const w = step.while as { steps?: WorkflowStep[] };
        if (w.steps) paths.push(...extractModulePaths(w.steps));
      }
      if ('for_each' in step && step.for_each) {
        const f = step.for_each as { steps?: WorkflowStep[] };
        if (f.steps) paths.push(...extractModulePaths(f.steps));
      }
      if ('switch' in step && step.switch) {
        const s = step.switch as {
          cases?: Record<string, WorkflowStep[]>;
          default?: WorkflowStep[];
        };
        if (s.cases) {
          for (const body of Object.values(s.cases)) {
            if (Array.isArray(body)) paths.push(...extractModulePaths(body));
          }
        }
        if (s.default) paths.push(...extractModulePaths(s.default));
      }
    }
    return paths;
  }

  // Also extract module paths directly from graph nodes
  function extractModulePathsFromNodes(): string[] {
    const paths: string[] = [];
    for (const node of nodes) {
      const data = node.data as Record<string, unknown>;
      const nodeType = data.nodeType as string;
      if (
        (nodeType === 'call' || nodeType === 'parallel') &&
        typeof data.module === 'string' &&
        data.module
      ) {
        paths.push(data.module);
      }
      if (nodeType === 'gather') {
        if (typeof data.module === 'string' && data.module) {
          paths.push(data.module);
        }
        const calls = data.calls as Array<{ module?: string }> | undefined;
        if (calls) {
          for (const call of calls) {
            if (call.module) paths.push(call.module);
          }
        }
      }
    }
    return paths;
  }

  // Recursively process a YAML string
  function process(yamlContent: string) {
    let parsed: unknown;
    try {
      parsed = yamlLib.load(yamlContent);
    } catch {
      return;
    }
    if (!parsed || typeof parsed !== 'object') return;
    const workflow = (parsed as Record<string, unknown>).workflow;
    if (!Array.isArray(workflow)) return;

    const paths = extractModulePaths(workflow as WorkflowStep[]);
    for (const p of paths) {
      if (visited.has(p)) continue;
      visited.add(p);
      const content = resolveContent(p);
      if (content) {
        result.set(p, content);
        // Recurse into this module's YAML
        process(content);
      }
    }
  }

  // Start with the main YAML
  process(mainYaml);

  // Also process module paths from graph nodes (catches any not in the YAML text)
  const nodePaths = extractModulePathsFromNodes();
  for (const p of nodePaths) {
    if (visited.has(p)) continue;
    visited.add(p);
    const content = resolveContent(p);
    if (content) {
      result.set(p, content);
      process(content);
    }
  }

  return result;
}
