import { createContext, useContext, ReactNode } from 'react';

interface LayoutContextType {
  triggerLayout: () => void;
  triggerLayoutOnly: () => void; // Layout without fitView
}

const LayoutContext = createContext<LayoutContextType | null>(null);

export function LayoutProvider({ children, triggerLayout, triggerLayoutOnly }: { children: ReactNode; triggerLayout: () => void; triggerLayoutOnly: () => void }) {
  return (
    <LayoutContext.Provider value={{ triggerLayout, triggerLayoutOnly }}>
      {children}
    </LayoutContext.Provider>
  );
}

export function useLayout() {
  const context = useContext(LayoutContext);
  if (!context) {
    // Return a no-op if context is not available (for components outside provider)
    return { triggerLayout: () => {}, triggerLayoutOnly: () => {} };
  }
  return context;
}
