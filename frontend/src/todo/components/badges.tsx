import type { TodoSource, TodoStatus } from '../../core/types';
import { FONT_MONO, INK_DIM, INK_SOFT } from '../../shared/styles';
import { SOURCE_LABELS, STATUS_META } from '../constants';

const badgeBase: React.CSSProperties = {
  fontSize: 11, padding: '3px 10px', borderRadius: 4,
  fontFamily: FONT_MONO, letterSpacing: '0.08em',
  fontWeight: 500, whiteSpace: 'nowrap',
};

export function TodoStatusBadge({ status }: { status: TodoStatus }) {
  const meta = STATUS_META[status];
  return <span style={{ ...badgeBase, background: meta.bg, color: meta.color }}>{meta.label}</span>;
}

export function ContextChip({ context }: { context: string }) {
  if (!context) return null;
  return (
    <span style={{
      ...badgeBase, textTransform: 'none',
      background: 'rgba(230,235,242,0.06)', color: INK_SOFT,
    }}>{context}</span>
  );
}

export function TagChip({ tag }: { tag: string }) {
  return (
    <span style={{
      ...badgeBase, textTransform: 'none', padding: '3px 8px',
      background: 'rgba(230,235,242,0.04)', color: INK_DIM,
    }}>#{tag}</span>
  );
}

export function SourceBadge({ source }: { source: TodoSource }) {
  return (
    <span style={{
      ...badgeBase,
      background: 'rgba(230,235,242,0.05)', color: INK_DIM,
    }}>{SOURCE_LABELS[source] || source}</span>
  );
}
