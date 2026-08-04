import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { todoApi } from './api';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { toast } from '../shared/toast';
import { IconPlus } from '../shared/icons';
import { INK_DIM, INK_SOFT, mono } from '../shared/styles';
import { pageHeading, sectionHeading, btnPrimary, btnSmall, listContainer } from './styles';
import { STATUS_META } from './constants';
import { formatAge, matchesFilter } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { FilterEmptyState, ListFilterBar } from './components/ListFilterBar';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

export function WaitingPage() {
  const isMobile = useIsMobile();
  const { contexts, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [waiting, setWaiting] = useState<Todo[]>([]);
  const [delegated, setDelegated] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');
  const [contextFilter, setContextFilter] = useState('');

  const load = useCallback(async () => {
    try {
      const [w, d] = await Promise.all([
        todoApi<{ todos: Todo[] }>('/api/todo/todos?status=waiting_for&limit=500'),
        todoApi<{ todos: Todo[] }>('/api/todo/todos?status=delegated&limit=500'),
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
      await todoApi(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify({ status: 'next_action' }) });
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
        <div style={listContainer(isMobile)}>
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

  const visibleWaiting = waiting.filter(t => matchesFilter(t, search, contextFilter));
  const visibleDelegated = delegated.filter(t => matchesFilter(t, search, contextFilter));

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={pageHeading(isMobile)}>Waiting</h1>
        <button onClick={() => setShowCreate(true)} style={{ ...btnPrimary, padding: '7px 14px', fontSize: 13 }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Waiting Item'}
        </button>
      </div>

      <ListFilterBar
        search={search} onSearch={setSearch}
        context={contextFilter} onContext={setContextFilter} contexts={contexts}
        isMobile={isMobile} placeholder="Search waiting items..."
      />

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && waiting.length === 0 && delegated.length === 0 ? (
        <LoadError label="Couldn't load waiting items" onRetry={load} />
      ) : waiting.length === 0 && delegated.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>Nothing waiting on anyone. Nice.</p>
        </div>
      ) : visibleWaiting.length === 0 && visibleDelegated.length === 0 ? (
        <FilterEmptyState />
      ) : (
        <>
          {section('Waiting For', STATUS_META.waiting_for.color, visibleWaiting)}
          {section('Delegated', STATUS_META.delegated.color, visibleDelegated)}
        </>
      )}

      {showCreate && (
        <TodoEditSheet
          defaults={{ status: 'waiting_for' }}
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); reload(); }}
        />
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
