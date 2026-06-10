/**
 * Chatty — toast viewport. Mounted once in App.tsx; renders the toast store
 * as a fixed bottom-right stack (full-width above the bottom nav on mobile).
 */

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { subscribeToasts, getToasts, dismissToast } from './toast';
import type { ToastItem, ToastSeverity } from './toast';
import { useIsMobile } from './useIsMobile';
import { BG_ELEV, LINE_STRONG, INK, INK_DIM, CORAL, SAGE, GOLD, FONT_SANS, mono } from './styles';

const SEVERITY_COLOR: Record<ToastSeverity, string> = {
  error: CORAL,
  success: SAGE,
  info: GOLD,
};

const SEVERITY_TAG: Record<ToastSeverity, string> = {
  error: 'Error',
  success: 'Success',
  info: 'Notice',
};

// getServerSnapshot must return a stable reference, or React warns about
// an infinite loop of new snapshots.
const EMPTY: ToastItem[] = [];

export function ToastViewport() {
  const items = useSyncExternalStore(subscribeToasts, getToasts, () => EMPTY);
  const isMobile = useIsMobile();

  if (items.length === 0) return null;

  return (
    <div
      style={{
        position: 'fixed',
        zIndex: 200,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        ...(isMobile
          ? { left: 12, right: 12, bottom: 68 }
          : { right: 20, bottom: 16, width: 360 }),
      }}
    >
      {items.map(item => (
        <ToastCard key={item.id} item={item} onDismiss={() => dismissToast(item.id)} />
      ))}
    </div>
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const color = SEVERITY_COLOR[item.severity];
  // Auto-dismiss with hover-pause: track remaining time across pauses.
  const remainingRef = useRef(item.duration);
  const startedAtRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    startTimer();
    return stopTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startTimer() {
    startedAtRef.current = Date.now();
    timerRef.current = setTimeout(onDismiss, remainingRef.current);
  }

  function stopTimer() {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = null;
  }

  function handleMouseEnter() {
    stopTimer();
    remainingRef.current = Math.max(0, remainingRef.current - (Date.now() - startedAtRef.current));
  }

  function handleMouseLeave() {
    startTimer();
  }

  return (
    <div
      role={item.severity === 'error' ? 'alert' : 'status'}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        background: BG_ELEV,
        border: `1px solid ${LINE_STRONG}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 8,
        padding: '10px 12px 10px 14px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
        animation: 'ch-toast-in 0.18s ease-out',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ ...mono(10, color), marginBottom: 3 }}>{SEVERITY_TAG[item.severity]}</div>
        <div style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK, lineHeight: 1.45, overflowWrap: 'break-word' }}>
          {item.message}
        </div>
      </div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          background: 'none',
          border: 'none',
          color: INK_DIM,
          cursor: 'pointer',
          fontSize: 16,
          lineHeight: 1,
          padding: '2px 4px',
          flexShrink: 0,
        }}
      >
        ×
      </button>
    </div>
  );
}
