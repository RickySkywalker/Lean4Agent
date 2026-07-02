import { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { FlowNodeData } from '../types';

interface InnerStepSelection {
  parentNodeId: string;
  branch: string; // 'then' | 'else' | 'loop'
  stepIndex: number;
  stepData: FlowNodeData;
}

interface InnerStepContextType {
  selectedInnerStep: InnerStepSelection | null;
  selectInnerStep: (selection: InnerStepSelection | null) => void;
  updateInnerStep: (parentNodeId: string, branch: string, stepIndex: number, updates: Partial<FlowNodeData>) => void;
  onUpdateCallback: ((parentNodeId: string, branch: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null;
  setOnUpdateCallback: (callback: ((parentNodeId: string, branch: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null) => void;
}

const InnerStepContext = createContext<InnerStepContextType | null>(null);

export function InnerStepProvider({ children }: { children: ReactNode }) {
  const [selectedInnerStep, setSelectedInnerStep] = useState<InnerStepSelection | null>(null);
  const [onUpdateCallback, setOnUpdateCallback] = useState<((parentNodeId: string, branch: string, stepIndex: number, updates: Partial<FlowNodeData>) => void) | null>(null);

  const selectInnerStep = useCallback((selection: InnerStepSelection | null) => {
    setSelectedInnerStep(selection);
  }, []);

  const updateInnerStep = useCallback((parentNodeId: string, branch: string, stepIndex: number, updates: Partial<FlowNodeData>) => {
    if (onUpdateCallback) {
      onUpdateCallback(parentNodeId, branch, stepIndex, updates);
    }
  }, [onUpdateCallback]);

  return (
    <InnerStepContext.Provider value={{ 
      selectedInnerStep, 
      selectInnerStep, 
      updateInnerStep,
      onUpdateCallback,
      setOnUpdateCallback
    }}>
      {children}
    </InnerStepContext.Provider>
  );
}

export function useInnerStep() {
  const context = useContext(InnerStepContext);
  if (!context) {
    throw new Error('useInnerStep must be used within InnerStepProvider');
  }
  return context;
}

