import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { toast } from '../shared/toast';
import { INK_DIM, INK_SOFT, mono } from '../shared/styles';
import { pageHeading, sectionHeading, btnSmall } from './styles';
import { STATUS_META } from './constants';
import { formatAge } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import type { TodoOutletContext } from './TodoLayout';

export function WaitingPage() {
  const isMobile = useIsMobile();
  const { refreshMeta } = useOutletContext<TodoOutletContext>();
  const [waiting, setWaiting] = useState<Todo[]>([]);
  const [delegated, setDelegated] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const load = useCallback(async () => {
    try {
      const [w, d] = await Promise.all([
        api<{ todos: Todo[] }>('/api/todo/todos?status=waiting_for&limit=500'),
        api<{ todos: Todo[] }>('/api/todo/todos?status=delegated&limit=500'),
      ]);
      setWaiting(w.todos);
      setDelegated(d.todos);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  async function reactivate(todo: Todo) {
    try {
      await api(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify({ status: 'next_action' }) });
    } catch {
      toast.error('Failed to update todo.');
      return;
    }
    reload();
  }

  function section(label: string, color: string, items: Todo[]) {
    if (items.length === 0) return null;
    return (
      <div style={{ marginBottom: 28 }}>
        <div style={sectionHeading(color)}>{label.toUpperCase()} · {items.length}</div>
        <div style={isMobile
          ? { display: 'flex', flexDirection: 'column', gap: 8 }
          : { borderTop: '1px solid rgba(230,235,242,0.07)' }
        }>
          {items.map(todo => (
            <TodoRow
              key={todo.id}
              todo={todo}
              onChanged={reload}
              onOpen={setEditTodo}
              trailing={
                <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={mono(11, INK_SOFT)}>waiting {formatAge(todo.updated_at)}</span>
                  <button
                    onClick={e => { e.stopPropagation(); reactivate(todo); }}
                    style={{ ...btnSmall, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: INK_SOFT }}
                  >→ Next</button>
                </span>
              }
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <h1 style={{ ...pageHeading(isMobile), marginBottom: isMobile ? 16 : 24 }}>Waiting</h1>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : loadFailed && waiting.length === 0 && delegated.length === 0 ? (
        <LoadError label="Couldn't load waiting items" onRetry={load} />
      ) : waiting.length === 0 && delegated.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>Nothing waiting on anyone. Nice.</p>
        </div>
      ) : (
        <>
          {section('Waiting For', STATUS_META.waiting_for.color, waiting)}
          {section('Delegated', STATUS_META.delegated.color, delegated)}
        </>
      )}

      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          onClose={() => setEditTodo(null)}
          onSaved={() => { setEditTodo(null); reload(); }}
        />
      )}
    </div>
  );
}
