import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { INK_DIM } from '../shared/styles';
import { pageHeading, filterBar, filterTab, listContainer } from './styles';
import { STATUS_META } from './constants';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

type Filter = 'done' | 'dropped';

export function DonePage() {
  const isMobile = useIsMobile();
  const { refreshMeta } = useOutletContext<TodoOutletContext>();
  const [filter, setFilter] = useState<Filter>('done');
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<{ todos: Todo[] }>(`/api/todo/todos?status=${filter}&limit=200`);
      // Most recently finished first.
      setTodos([...data.todos].reverse());
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
    setLoading(false);
  }, [filter]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <h1 style={{ ...pageHeading(isMobile), marginBottom: isMobile ? 16 : 24 }}>Done</h1>

      <div style={filterBar(isMobile)}>
        {(['done', 'dropped'] as Filter[]).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={filterTab(isMobile, filter === f, STATUS_META[f].color)}
          >{STATUS_META[f].label}</button>
        ))}
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load finished todos" onRetry={load} />
      ) : todos.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            {filter === 'done' ? 'Nothing completed yet.' : 'Nothing dropped.'}
          </p>
        </div>
      ) : (
        <div style={listContainer(isMobile)}>
          {todos.map(todo => (
            <TodoRow key={todo.id} todo={todo} onChanged={reload} onOpen={setEditTodo} />
          ))}
        </div>
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
