import { useCallback, useRef, useEffect, useState } from 'react';
import { FlowNode, FlowEdge } from '../types';

interface HistoryState {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

interface UseHistoryOptions {
  maxHistorySize?: number;
}

interface UseHistoryReturn {
  pushHistory: (nodes: FlowNode[], edges: FlowEdge[]) => void;
  undo: () => HistoryState | null;
  redo: () => HistoryState | null;
  canUndo: boolean;
  canRedo: boolean;
  clearHistory: () => void;
}

export function useHistory(options: UseHistoryOptions = {}): UseHistoryReturn {
  const { maxHistorySize = 50 } = options;
  
  // Use refs for history data to avoid unnecessary re-renders
  const historyRef = useRef<HistoryState[]>([]);
  const currentIndexRef = useRef(-1);
  const isUndoRedoRef = useRef(false);
  
  // Use state for canUndo/canRedo to trigger re-renders
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  
  // Update the button states
  const updateButtonStates = useCallback(() => {
    setCanUndo(currentIndexRef.current > 0);
    setCanRedo(currentIndexRef.current < historyRef.current.length - 1);
  }, []);

  // Deep clone state for history
  const cloneState = useCallback((nodes: FlowNode[], edges: FlowEdge[]): HistoryState => {
    return {
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    };
  }, []);

  // Compare two states
  const statesEqual = useCallback((a: HistoryState, b: HistoryState): boolean => {
    return JSON.stringify(a) === JSON.stringify(b);
  }, []);

  // Push a new state to history
  const pushHistory = useCallback((nodes: FlowNode[], edges: FlowEdge[]) => {
    // Skip if this is an undo/redo operation
    if (isUndoRedoRef.current) {
      return;
    }

    const newState = cloneState(nodes, edges);
    
    // Skip if same as current state
    const currentState = historyRef.current[currentIndexRef.current];
    if (currentState && statesEqual(currentState, newState)) {
      return;
    }

    // If we're not at the end of history, truncate future states
    if (currentIndexRef.current < historyRef.current.length - 1) {
      historyRef.current = historyRef.current.slice(0, currentIndexRef.current + 1);
    }

    // Add new state
    historyRef.current.push(newState);
    currentIndexRef.current = historyRef.current.length - 1;

    // Limit history size
    if (historyRef.current.length > maxHistorySize) {
      historyRef.current.shift();
      currentIndexRef.current = historyRef.current.length - 1;
    }

    updateButtonStates();
  }, [cloneState, statesEqual, maxHistorySize, updateButtonStates]);

  // Undo operation
  const undo = useCallback((): HistoryState | null => {
    if (currentIndexRef.current <= 0) {
      return null;
    }

    isUndoRedoRef.current = true;
    currentIndexRef.current -= 1;
    const state = historyRef.current[currentIndexRef.current];
    updateButtonStates();
    
    // Reset flag after a short delay
    setTimeout(() => {
      isUndoRedoRef.current = false;
    }, 100);

    return state ? cloneState(state.nodes, state.edges) : null;
  }, [cloneState, updateButtonStates]);

  // Redo operation
  const redo = useCallback((): HistoryState | null => {
    if (currentIndexRef.current >= historyRef.current.length - 1) {
      return null;
    }

    isUndoRedoRef.current = true;
    currentIndexRef.current += 1;
    const state = historyRef.current[currentIndexRef.current];
    updateButtonStates();
    
    // Reset flag after a short delay
    setTimeout(() => {
      isUndoRedoRef.current = false;
    }, 100);

    return state ? cloneState(state.nodes, state.edges) : null;
  }, [cloneState, updateButtonStates]);

  // Clear history
  const clearHistory = useCallback(() => {
    historyRef.current = [];
    currentIndexRef.current = -1;
    updateButtonStates();
  }, [updateButtonStates]);

  return {
    pushHistory,
    undo,
    redo,
    canUndo,
    canRedo,
    clearHistory,
  };
}

// Keyboard shortcut hook for undo/redo
export function useUndoRedoKeyboard(
  onUndo: () => void,
  onRedo: () => void,
  enabled: boolean = true
) {
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      // Check for Ctrl (Windows/Linux) or Cmd (Mac)
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      const modifier = isMac ? event.metaKey : event.ctrlKey;

      if (!modifier) return;

      // Avoid interfering with text inputs
      const activeElement = document.activeElement;
      const isInputActive = 
        activeElement instanceof HTMLInputElement ||
        activeElement instanceof HTMLTextAreaElement ||
        (activeElement as HTMLElement)?.isContentEditable;

      if (isInputActive) return;

      if (event.key === 'z' || event.key === 'Z') {
        event.preventDefault();
        if (event.shiftKey) {
          // Ctrl/Cmd + Shift + Z = Redo
          onRedo();
        } else {
          // Ctrl/Cmd + Z = Undo
          onUndo();
        }
      }
      
      // Also support Ctrl/Cmd + Y for redo (common on Windows)
      if (event.key === 'y' || event.key === 'Y') {
        if (!event.shiftKey) {
          event.preventDefault();
          onRedo();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onUndo, onRedo, enabled]);
}
