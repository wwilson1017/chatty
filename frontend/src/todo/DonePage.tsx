import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { INK_DIM } from '../shared/styles';
import { pageHeading, filterBar, filterTab, listContainer } from './styles';
import { STATUS_META } from './constants';
import { matchesFilter } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { ListFilterBar } from './components/ListFilterBar';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

type Filter = 'done' | 'dropped';

export function DonePage() {
  const isMobile = useIsMobile();
  const { contexts, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [filter, setFilter] = useState<Filter>('done');
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [search, setSearch] = useState('');
  const [contextFilter, setContextFilter] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<{ todos: Todo[] }>(`/api/todo/todos?status=${filter}&limit=200`);
      // Server orders done/dropped newest-finished first.
      setTodos(data.todos);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
    setLoading(false);
  }, [filter]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  const filtered = todos.filter(t => matchesFilter(t, search, contextFilter));

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

      <ListFilterBar
        search={search} onSearch={setSearch}
        context={contextFilter} onContext={setContextFilter} contexts={contexts}
        isMobile={isMobile} placeholder="Search finished todos..."
      />

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
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>Nothing matches your filter.</p>
        </div>
      ) : (
        <div style={listContainer(isMobile)}>
          {filtered.map(todo => (
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
