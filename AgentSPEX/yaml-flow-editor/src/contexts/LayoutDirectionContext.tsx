import { createContext, useContext } from 'react';

export type LayoutDirection = 'TB' | 'LR';

const LayoutDirectionContext = createContext<LayoutDirection>('TB');

export function LayoutDirectionProvider({
  value,
  children,
}: {
  value: LayoutDirection;
  children: React.ReactNode;
}) {
  return (
    <LayoutDirectionContext.Provider value={value}>
      {children}
    </LayoutDirectionContext.Provider>
  );
}

export function useLayoutDirection(): LayoutDirection {
  return useContext(LayoutDirectionContext);
}

