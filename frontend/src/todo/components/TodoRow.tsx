import type { ReactNode } from 'react';
import { todoApi } from '../api';
import type { Todo } from '../../core/types';
import { IconCheck, IconStar, IconStarFilled } from '../../shared/icons';
import { useIsMobile } from '../../shared/useIsMobile';
import { toast } from '../../shared/toast';
import { CORAL, GOLD, INK, INK_DIM, INK_SOFT, LINE, LINE_STRONG, SAGE, mono } from '../../shared/styles';
import { cardStyle } from '../styles';
import { ContextChip, TagChip } from './badges';
import { todayStr } from '../util';

interface Props {
  todo: Todo;
  onChanged: () => void;
  onOpen: (todo: Todo) => void;
  /** Status to set when un-checking a done/dropped item (default next_action). */
  uncheckStatus?: string;
  /** Extra inline action(s) rendered at the right edge, e.g. a "→ Next" button. */
  trailing?: ReactNode;
  /** Show the project name chip (hidden inside a project's own view). */
  showProject?: boolean;
}

export function TodoRow({ todo, onChanged, onOpen, uncheckStatus = 'next_action', trailing, showProject = true }: Props) {
  const isMobile = useIsMobile();
  const isDone = todo.status === 'done' || todo.status === 'dropped';
  const overdue = !isDone && !!todo.due_date && todo.due_date < todayStr();

  async function patch(fields: Record<string, unknown>): Promise<boolean> {
    try {
      await todoApi(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify(fields) });
    } catch {
      toast.error('Failed to update todo.');
      return false;
    }
    onChanged();
    return true;
  }

  async function toggleDone() {
    const reopeningSpawned = todo.status === 'done' && !!todo.repeat;
    if (await patch({ status: isDone ? uncheckStatus : 'done' }) && reopeningSpawned) {
      // Completing a repeating todo already spawned its successor; reopening
      // this one means both copies are now live.
      toast.info('Reopened — its next occurrence already exists from when it was completed.');
    }
  }

  const checkbox = (
    <button
      onClick={e => { e.stopPropagation(); toggleDone(); }}
      title={isDone ? 'Reopen' : 'Mark done'}
      style={{
        width: 20, height: 20, borderRadius: 4, flexShrink: 0,
        border: `1.5px solid ${todo.status === 'done' ? SAGE : LINE_STRONG}`,
        background: todo.status === 'done' ? 'rgba(142,165,137,0.2)' : 'transparent',
        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: SAGE, padding: 0,
      }}
    >
      {todo.status === 'done' && <IconCheck size={12} strokeWidth={2.5} />}
    </button>
  );

  const star = (
    <button
      onClick={e => { e.stopPropagation(); patch({ star: !todo.star }); }}
      title={todo.star ? 'Unstar' : 'Star (today’s priority)'}
      style={{
        background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
        color: todo.star ? GOLD : INK_DIM, flexShrink: 0,
        display: 'flex', alignItems: 'center',
      }}
    >
      {todo.star ? <IconStarFilled size={15} /> : <IconStar size={15} />}
    </button>
  );

  const meta = (
    <>
      {todo.context && <ContextChip context={todo.context} />}
      {showProject && todo.project_name && (
        <span style={{ fontSize: 13, color: INK_SOFT, whiteSpace: 'nowrap' }}>{todo.project_name}</span>
      )}
      {todo.tags.slice(0, 3).map(t => <TagChip key={t} tag={t} />)}
      {todo.repeat && (
        <span title={`Repeats ${todo.repeat}`} style={{ ...mono(12, INK_SOFT), whiteSpace: 'nowrap' }}>
          ↻ {todo.repeat}
        </span>
      )}
      {todo.due_date && (
        <span style={{
          ...mono(12, overdue ? CORAL : INK_SOFT),
          fontWeight: overdue ? 600 : 400, whiteSpace: 'nowrap',
        }}>{todo.due_date}</span>
      )}
    </>
  );

  if (isMobile) {
    return (
      <div
        onClick={() => onOpen(todo)}
        style={{ padding: '12px 14px', cursor: 'pointer', ...cardStyle, opacity: isDone ? 0.55 : 1 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          {checkbox}
          <span style={{
            flex: 1, fontSize: 16, color: isDone ? INK_DIM : INK,
            textDecoration: todo.status === 'done' ? 'line-through' : 'none',
          }}>{todo.title}</span>
          {star}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', paddingLeft: 30 }}>
          {meta}
          {trailing}
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={() => onOpen(todo)}
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '11px 16px', cursor: 'pointer',
        borderBottom: `1px solid ${LINE}`,
        opacity: isDone ? 0.55 : 1,
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      {checkbox}
      {star}
      <span style={{
        flex: 1, minWidth: 0, fontSize: 15,
        color: isDone ? INK_DIM : INK,
        textDecoration: todo.status === 'done' ? 'line-through' : 'none',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>{todo.title}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        {meta}
        {trailing}
      </div>
    </div>
  );
}
