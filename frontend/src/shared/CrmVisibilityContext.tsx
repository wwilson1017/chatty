import { createContext, useContext } from 'react';

const CrmVisibilityContext = createContext(false);

export const CrmVisibilityProvider = CrmVisibilityContext.Provider;

export function useCrmHidden(): boolean {
  return useContext(CrmVisibilityContext);
}
