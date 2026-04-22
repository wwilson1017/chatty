import type { CSSProperties } from 'react';

// ── Colors (CSS custom property strings with fallbacks) ──────────────────────

export const INK = 'var(--color-ch-ink, #EDF0F4)';
export const INK_MUTE = 'var(--color-ch-ink-mute, rgba(237,240,244,0.62))';
export const INK_SOFT = 'var(--color-ch-ink-soft, rgba(237,240,244,0.50))';
export const INK_DIM = 'var(--color-ch-ink-dim, rgba(237,240,244,0.38))';
export const LINE = 'var(--color-ch-line, rgba(230,235,242,0.07))';
export const LINE_STRONG = 'var(--color-ch-line-strong, rgba(230,235,242,0.14))';
export const BG_ELEV = 'var(--color-ch-bg-elev, #11141A)';
export const BG_CARD = 'var(--color-ch-bg-card, rgba(20,24,30,0.78))';
export const BG_RAISED = 'var(--color-ch-bg-raised, rgba(34,40,48,0.55))';
export const ACCENT = 'var(--color-ch-accent, #C8D1D9)';
export const ACCENT_INK = 'var(--color-ch-accent-ink, #0E1013)';
export const ACCENT_SOFT = 'var(--color-ch-accent-soft, rgba(200,209,217,0.12))';
export const GOLD = 'var(--color-ch-gold, #D4A85A)';
export const CORAL = 'var(--color-ch-coral, #D97757)';
export const SAGE = 'var(--color-ch-sage, #8EA589)';

// ── Font stacks ──────────────────────────────────────────────────────────────

export const FONT_DISPLAY = "'Fraunces', Georgia, serif";
export const FONT_SANS = "'Inter Tight', system-ui, sans-serif";
export const FONT_MONO = "'JetBrains Mono', ui-monospace, monospace";

// ── Typography helper ────────────────────────────────────────────────────────

export const mono = (size: number, color: string = INK_DIM): CSSProperties => ({
  fontFamily: FONT_MONO,
  fontSize: size,
  letterSpacing: '0.16em',
  textTransform: 'uppercase',
  color,
});

// ── Form styles ──────────────────────────────────────────────────────────────

export const labelStyle: CSSProperties = {
  display: 'block',
  fontFamily: FONT_MONO,
  fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase',
  color: INK_DIM, marginBottom: 6,
};

export const inputStyle: CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
  color: INK, borderRadius: 4, padding: '8px 12px', fontSize: 14, outline: 'none',
  fontFamily: FONT_SANS,
};

// ── Utilities ────────────────────────────────────────────────────────────────

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K';
  return n.toLocaleString();
}
