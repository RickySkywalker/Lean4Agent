import { createContext, useContext } from 'react';
import type { ModuleTemplate } from '../components/Sidebar';

export interface UploadedModuleEntry {
  path: string;
  content: string;
  template: ModuleTemplate;
}

export interface ModulesContextValue {
  modulesByPath: Record<string, UploadedModuleEntry>;
  updateModuleContent: (path: string, newContent: string) => void;
  updateNodeModuleContent: (nodeId: string, modulePath: string, newContent: string) => void;
}

export const ModulesContext = createContext<ModulesContextValue | null>(null);

export function useModules() {
  const ctx = useContext(ModulesContext);
  if (!ctx) {
    throw new Error('useModules must be used within ModulesContext provider');
  }
  return ctx;
}

