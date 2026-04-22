import type { CSSProperties } from 'react';
import {
  INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG,
  BG_ELEV, BG_CARD, ACCENT, ACCENT_INK, CORAL,
  FONT_DISPLAY, FONT_SANS, mono,
} from '../shared/styles';

// ── Layout ───────────────────────────────────────────────────────────────────

export function pagePadding(isMobile: boolean): CSSProperties {
  return { padding: isMobile ? '20px 16px' : '32px 44px' };
}

export function pageHeading(isMobile: boolean): CSSProperties {
  return {
    fontFamily: FONT_DISPLAY,
    fontSize: isMobile ? 30 : 48, fontWeight: 400, letterSpacing: '-0.02em',
    lineHeight: 1.1, color: INK, margin: 0,
  };
}

export function sectionHeading(color: string = INK_DIM): CSSProperties {
  return { ...mono(11, color), marginBottom: 14 };
}

// ── Cards ────────────────────────────────────────────────────────────────────

export const cardStyle: CSSProperties = {
  background: BG_CARD, border: `1px solid ${LINE}`, borderRadius: 6,
};

export function stageCard(bg: string, color: string): CSSProperties {
  return {
    background: bg,
    border: `1px solid ${LINE}`,
    borderLeft: `3px solid ${color}`,
    borderRadius: 6,
  };
}

// ── Modals ────────────────────────────────────────────────────────────────────

export function modalOverlay(isMobile: boolean): CSSProperties {
  return {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
    zIndex: 50, display: 'flex',
    alignItems: isMobile ? 'flex-end' : 'center',
    justifyContent: 'center',
  };
}

export function modalContent(isMobile: boolean, maxWidth = 480): CSSProperties {
  return {
    background: BG_ELEV,
    borderRadius: isMobile ? '12px 12px 0 0' : 8,
    border: `1px solid ${LINE_STRONG}`,
    borderBottom: isMobile ? 'none' : undefined,
    padding: isMobile ? '20px 20px 28px' : 28,
    width: '100%', maxWidth, margin: isMobile ? 0 : '0 16px',
    boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
  };
}

export const formModalOverlay: CSSProperties = modalOverlay(false);

export function formModalContent(maxWidth = 420): CSSProperties {
  return {
    background: BG_ELEV, borderRadius: 6, border: `1px solid ${LINE_STRONG}`,
    padding: 24, width: '100%', maxWidth, margin: '0 16px',
    maxHeight: '90vh', overflowY: 'auto',
    boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
  };
}

export const formTitle: CSSProperties = {
  fontFamily: FONT_DISPLAY,
  fontSize: 20, fontWeight: 400, letterSpacing: '-0.02em',
  color: INK, marginBottom: 20,
};

export const mobileDragHandle: CSSProperties = {
  width: 36, height: 4, borderRadius: 2, background: LINE_STRONG,
};

// ── Buttons ──────────────────────────────────────────────────────────────────

export const btnPrimary: CSSProperties = {
  background: ACCENT, color: ACCENT_INK,
  border: 'none', padding: '10px 20px', borderRadius: 4,
  fontSize: 15, fontWeight: 500, cursor: 'pointer',
  display: 'flex', alignItems: 'center', gap: 6,
  fontFamily: FONT_SANS,
};

export const btnSecondary: CSSProperties = {
  background: 'transparent', color: INK_MUTE,
  border: `1px solid ${LINE_STRONG}`,
  padding: '10px 20px', borderRadius: 4,
  fontSize: 15, cursor: 'pointer',
  fontFamily: FONT_SANS,
};

export const btnDanger: CSSProperties = {
  background: 'rgba(217,119,87,0.1)', color: CORAL,
  border: '1px solid rgba(217,119,87,0.2)',
  padding: '10px 20px', borderRadius: 4,
  fontSize: 15, cursor: 'pointer',
  fontFamily: FONT_SANS,
};

export const btnSmall: CSSProperties = {
  padding: '7px 14px', borderRadius: 4,
  fontSize: 13, fontWeight: 500, cursor: 'pointer',
  fontFamily: FONT_SANS,
};

// ── Tables ────────────────────────────────────────────────────────────────────

export function tableHeader(columns: string): CSSProperties {
  return {
    display: 'grid', gridTemplateColumns: columns,
    gap: 16, padding: '10px 16px',
    borderBottom: `1px solid ${LINE}`,
    ...mono(12), fontWeight: 600,
  };
}

export function tableRow(columns: string): CSSProperties {
  return {
    display: 'grid', gridTemplateColumns: columns,
    gap: 16, padding: '14px 16px', cursor: 'pointer',
    borderBottom: `1px solid ${LINE}`,
  };
}

// ── Filters ──────────────────────────────────────────────────────────────────

export function filterBar(isMobile: boolean): CSSProperties {
  return {
    display: 'flex', gap: 0, marginBottom: isMobile ? 16 : 28,
    overflowX: isMobile ? 'auto' : undefined,
    WebkitOverflowScrolling: 'touch' as const,
  };
}

export function filterTab(isMobile: boolean, isActive: boolean, activeColor?: string): CSSProperties {
  const borderColor = activeColor || ACCENT;
  return {
    flex: 1, padding: isMobile ? '10px 8px' : '12px 16px',
    fontSize: 14, fontWeight: 500, textTransform: 'capitalize',
    color: isActive ? INK : INK_MUTE,
    background: isActive ? 'rgba(200,209,217,0.15)' : 'rgba(200,209,217,0.06)',
    border: 'none',
    borderLeft: `3px solid ${isActive ? borderColor : 'rgba(230,235,242,0.10)'}`,
    borderRight: `3px solid ${isActive ? borderColor : 'rgba(230,235,242,0.10)'}`,
    borderRadius: 0, cursor: 'pointer', whiteSpace: 'nowrap',
    fontFamily: FONT_SANS,
    transition: 'background 0.15s, color 0.15s',
  };
}
