import type { CSSProperties } from 'react';

// Section-shell tokens shared with CRM — single source in shared/sectionStyles.
export * from '../shared/sectionStyles';

// The todo list wrapper: bordered row list on desktop, stacked cards on mobile.
export function listContainer(isMobile: boolean): CSSProperties {
  return isMobile
    ? { display: 'flex', flexDirection: 'column', gap: 8 }
    : { borderTop: '1px solid rgba(230,235,242,0.07)' };
}
