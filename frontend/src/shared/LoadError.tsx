/**
 * Chatty — inline "Couldn't load — Retry" callout for primary data loads
 * that failed. Lives where the content would be (errors belong where the
 * user is looking); toasts are reserved for failed mutations.
 */

import { INK_MUTE, CORAL, GOLD, FONT_SANS, mono } from './styles';

interface Props {
  label?: string;
  onRetry: () => void;
  compact?: boolean;
}

export function LoadError({ label = "Couldn't load", onRetry, compact }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: 'rgba(217,119,87,0.06)',
        border: '1px solid rgba(217,119,87,0.18)',
        borderRadius: 6,
        padding: compact ? '10px 12px' : '14px 16px',
        margin: compact ? '8px 12px' : '12px 16px',
      }}
    >
      <span style={{ ...mono(9, CORAL), flexShrink: 0 }}>Error</span>
      <span style={{ fontFamily: FONT_SANS, fontSize: compact ? 12 : 13, color: INK_MUTE, flex: 1, minWidth: 0 }}>
        {label}
      </span>
      <button
        onClick={onRetry}
        style={{
          background: 'none',
          border: 'none',
          color: GOLD,
          cursor: 'pointer',
          fontSize: 12,
          fontFamily: FONT_SANS,
          padding: '2px 4px',
          flexShrink: 0,
        }}
      >
        Retry
      </button>
    </div>
  );
}
