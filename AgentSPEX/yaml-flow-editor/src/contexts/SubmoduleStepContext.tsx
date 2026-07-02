import { createContext, useContext, useState, useCallback, useMemo, ReactNode } from 'react';
import { FlowNodeData } from '../types';

export interface SubmoduleStepSelection {
  modulePath: string;
  stepIndex: number;
  stepData: FlowNodeData;
  parentNodeId: string;
}

interface SubmoduleStepContextType {
  selectedSubmoduleStep: SubmoduleStepSelection | null;
  selectSubmoduleStep: (selection: SubmoduleStepSelection | null) => void;
  updateSubmoduleStep: (parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => void;
  onUpdateCallback: ((parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null;
  setOnUpdateCallback: (callback: ((parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null) => void;
}

const SubmoduleStepContext = createContext<SubmoduleStepContextType | null>(null);

export function SubmoduleStepProvider({ children }: { children: ReactNode }) {
  const [selectedSubmoduleStep, setSelectedSubmoduleStep] = useState<SubmoduleStepSelection | null>(null);
  const [onUpdateCallback, setOnUpdateCallback] = useState<((parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null>(null);

  const selectSubmoduleStep = useCallback((selection: SubmoduleStepSelection | null) => {
    setSelectedSubmoduleStep(selection);
  }, []);

  const updateSubmoduleStep = useCallback((parentNodeId: string, modulePath: string, stepIndex: number, updates: Partial<FlowNodeData>) => {
    if (onUpdateCallback) {
      onUpdateCallback(parentNodeId, modulePath, stepIndex, updates);
    }
  }, [onUpdateCallback]);

  const value = useMemo(() => ({
    selectedSubmoduleStep,
    selectSubmoduleStep,
    updateSubmoduleStep,
    onUpdateCallback,
    setOnUpdateCallback,
  }), [selectedSubmoduleStep, selectSubmoduleStep, updateSubmoduleStep, onUpdateCallback, setOnUpdateCallback]);

  return (
    <SubmoduleStepContext.Provider value={value}>
      {children}
    </SubmoduleStepContext.Provider>
  );
}

export function useSubmoduleStep() {
  const context = useContext(SubmoduleStepContext);
  if (!context) {
    throw new Error('useSubmoduleStep must be used within SubmoduleStepProvider');
  }
  return context;
}
