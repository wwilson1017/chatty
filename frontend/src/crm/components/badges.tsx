import { FONT_MONO, CORAL, GOLD, SAGE, INK_SOFT, INK_DIM } from '../../shared/styles';

const badgeBase: React.CSSProperties = {
  fontSize: 12, padding: '4px 12px', borderRadius: 4,
  fontFamily: FONT_MONO, letterSpacing: '0.1em',
  textTransform: 'capitalize', fontWeight: 500,
};

const PRIORITY_COLORS: Record<string, { bg: string; color: string }> = {
  urgent: { bg: 'rgba(217,87,87,0.15)', color: '#D95757' },
  high: { bg: 'rgba(217,119,87,0.12)', color: CORAL },
  medium: { bg: 'rgba(212,168,90,0.10)', color: GOLD },
  low: { bg: 'rgba(230,235,242,0.08)', color: INK_SOFT },
};

export function PriorityBadge({ priority }: { priority: string }) {
  const c = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;
  return <span style={{ ...badgeBase, background: c.bg, color: c.color }}>{priority}</span>;
}

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  active: { bg: 'rgba(142,165,137,0.12)', color: SAGE },
  inactive: { bg: 'rgba(230,235,242,0.06)', color: INK_DIM },
  archived: { bg: 'rgba(217,119,87,0.08)', color: CORAL },
};

export function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.inactive;
  return <span style={{ ...badgeBase, background: c.bg, color: c.color }}>{status}</span>;
}
