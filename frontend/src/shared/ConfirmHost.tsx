/**
 * Chatty — confirm dialog host. Mounted once in App.tsx; renders the head
 * of the confirm store's queue as a styled modal (visual language of
 * dashboard/DeleteAgentModal.tsx).
 */

import { useEffect, useRef, useSyncExternalStore } from 'react';
import { subscribeConfirms, getCurrentConfirm, settleConfirm } from './confirm';
import type { ConfirmOptions } from './confirm';
import {
  BG_ELEV, LINE_STRONG, INK, INK_MUTE, INK_SOFT, ACCENT, ACCENT_INK, CORAL,
  FONT_DISPLAY, FONT_SANS,
} from './styles';

export function ConfirmHost() {
  const current = useSyncExternalStore(subscribeConfirms, getCurrentConfirm, () => null);
  return current ? <ConfirmCard key={current.id} options={current.options} /> : null;
}

function ConfirmCard({ options }: { options: ConfirmOptions }) {
  const { title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger } = options;
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    // Danger dialogs focus Cancel so a reflexive Enter can't destroy data;
    // otherwise Confirm gets focus to match native confirm()'s Enter ≈ OK.
    (danger ? cancelRef.current : confirmRef.current)?.focus();

    // Capture phase: runs before the bubble-phase document Escape listeners
    // in AvatarMenu/ConversationSidebar/HeartbeatChecklist, so Escape closes
    // only the confirm — not a popover underneath it.
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        settleConfirm(false);
      } else if (e.key === 'Tab') {
        // Two focusable elements — trap focus by toggling between them.
        e.preventDefault();
        e.stopPropagation();
        (document.activeElement === confirmRef.current ? cancelRef : confirmRef).current?.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown, { capture: true });
    return () => {
      document.removeEventListener('keydown', onKeyDown, { capture: true });
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [danger]);

  return (
    <div
      onClick={() => settleConfirm(false)}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 150, padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="chatty-confirm-title"
        aria-describedby="chatty-confirm-message"
        onClick={e => e.stopPropagation()}
        style={{
          background: BG_ELEV, borderRadius: 6,
          border: `1px solid ${LINE_STRONG}`,
          padding: 28, width: '100%', maxWidth: 420,
          boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
        }}
      >
        <h2
          id="chatty-confirm-title"
          style={{
            fontFamily: FONT_DISPLAY, fontSize: 20, fontWeight: 400,
            letterSpacing: '-0.02em', margin: '0 0 8px', color: INK,
          }}
        >
          {title}
        </h2>
        <p
          id="chatty-confirm-message"
          style={{
            fontFamily: FONT_SANS, fontSize: 13, color: INK_SOFT,
            lineHeight: 1.5, margin: '0 0 24px',
          }}
        >
          {message}
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            ref={cancelRef}
            type="button"
            onClick={() => settleConfirm(false)}
            style={{
              flex: 1, padding: '9px 16px', borderRadius: 4,
              border: `1px solid ${LINE_STRONG}`,
              background: 'transparent', color: INK_MUTE,
              cursor: 'pointer', fontSize: 13, fontFamily: FONT_SANS,
            }}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={() => settleConfirm(true)}
            style={{
              flex: 1, padding: '9px 16px', borderRadius: 4,
              background: danger ? CORAL : ACCENT, color: ACCENT_INK,
              border: 'none', fontWeight: 500, cursor: 'pointer',
              fontSize: 13, fontFamily: FONT_SANS,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
