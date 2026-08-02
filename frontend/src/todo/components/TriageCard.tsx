import { useState } from 'react';
import { api } from '../../core/api/client';
import type { Todo, TodoProject } from '../../core/types';
import { useIsMobile } from '../../shared/useIsMobile';
import { toast } from '../../shared/toast';
import { confirmDialog } from '../../shared/confirm';
import { IconStar, IconStarFilled } from '../../shared/icons';
import { FONT_DISPLAY, GOLD, INK, INK_DIM, INK_MUTE, inputStyle, mono, SAGE, ACCENT_INK } from '../../shared/styles';
import { cardStyle, btnSecondary, btnDanger } from '../styles';
import { SourceBadge } from './badges';
import { formatAge } from '../util';

interface Props {
  todo: Todo;
  projects: TodoProject[];
  /** Called after any mutation that resolves this item (status move / delete). */
  onProcessed: () => void;
  /** Called after an in-place change (project, due date, star). */
  onChanged: () => void;
  onEdit: (todo: Todo) => void;
}

const MOVES: { label: string; status: string; primary?: boolean }[] = [
  { label: '→ Next', status: 'next_action', primary: true },
  { label: '→ Waiting', status: 'waiting_for' },
  { label: '→ Delegated', status: 'delegated' },
  { label: '→ Someday', status: 'someday_maybe' },
];

/** Inbox processing card — clarify the head item one decision at a time. */
export function TriageCard({ todo, projects, onProcessed, onChanged, onEdit }: Props) {
  const isMobile = useIsMobile();
  const [busy, setBusy] = useState(false);

  async function patch(fields: Record<string, unknown>, resolves: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await api(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify(fields) });
      (resolves ? onProcessed : onChanged)();
    } catch {
      toast.error('Failed to update todo.');
    }
    setBusy(false);
  }

  async function handleDelete() {
    const ok = await confirmDialog({
      title: 'Delete todo',
      message: `Permanently delete "${todo.title}"?`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/api/todo/todos/${todo.id}`, { method: 'DELETE' });
      onProcessed();
    } catch {
      toast.error('Failed to delete todo.');
    }
  }

  const moveBtn = (move: typeof MOVES[number]): React.CSSProperties => move.primary
    ? {
        background: SAGE, color: ACCENT_INK, border: 'none', borderRadius: 4,
        padding: '10px 16px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
      }
    : { ...btnSecondary, padding: '10px 14px', fontSize: 14 };

  return (
    <div style={{ ...cardStyle, padding: isMobile ? '16px 14px' : '22px 24px', marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 8 }}>
        <h2 style={{
          fontFamily: FONT_DISPLAY, fontSize: isMobile ? 21 : 26, fontWeight: 400,
          letterSpacing: '-0.01em', color: INK, margin: 0, flex: 1, lineHeight: 1.25,
          overflowWrap: 'anywhere',
        }}>{todo.title}</h2>
        <button
          onClick={() => patch({ star: !todo.star }, false)}
          title={todo.star ? 'Unstar' : 'Star as today’s priority'}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: todo.star ? GOLD : INK_DIM, padding: 4,
          }}
        >
          {todo.star ? <IconStarFilled size={18} /> : <IconStar size={18} />}
        </button>
      </div>

      {todo.notes && (
        <p style={{ fontSize: 14, color: INK_MUTE, lineHeight: 1.55, margin: '0 0 12px', whiteSpace: 'pre-wrap' }}>
          {todo.notes}
        </p>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 18 }}>
        <SourceBadge source={todo.source} />
        <span style={mono(11, INK_DIM)}>captured {formatAge(todo.created_at)} ago</span>
      </div>

      {/* Row 1 — where does it go? */}
      <div style={{
        display: isMobile ? 'grid' : 'flex',
        gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12,
        flexWrap: 'wrap',
      }}>
        {MOVES.map(move => (
          <button
            key={move.status}
            disabled={busy}
            onClick={() => patch({ status: move.status }, true)}
            style={{ ...moveBtn(move), opacity: busy ? 0.6 : 1 }}
          >{move.label}</button>
        ))}
      </div>

      {/* Row 2 — enrich in place */}
      <div style={{
        display: isMobile ? 'grid' : 'flex',
        gridTemplateColumns: '1fr 1fr', gap: 8, alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <select
          value={todo.project_id ?? ''}
          onChange={e => patch({ project_id: e.target.value ? Number(e.target.value) : null }, false)}
          style={{ ...inputStyle, width: isMobile ? '100%' : 180, padding: '8px 10px', fontSize: 13 }}
        >
          <option value="">No project</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input
          type="date"
          value={todo.due_date || ''}
          onChange={e => patch({ due_date: e.target.value || null }, false)}
          style={{ ...inputStyle, width: isMobile ? '100%' : 160, padding: '8px 10px', fontSize: 13 }}
        />
        <button onClick={() => onEdit(todo)} style={{ ...btnSecondary, padding: '8px 14px', fontSize: 13 }}>
          Edit
        </button>
        <button onClick={handleDelete} style={{ ...btnDanger, padding: '8px 14px', fontSize: 13 }}>
          Delete
        </button>
        <button
          disabled={busy}
          onClick={() => patch({ status: 'done' }, true)}
          title="It took under 2 minutes — done"
          style={{ ...btnSecondary, padding: '8px 14px', fontSize: 13, color: SAGE }}
        >Done ✓</button>
      </div>
    </div>
  );
}
