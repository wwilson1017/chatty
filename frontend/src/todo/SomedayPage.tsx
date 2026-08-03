import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { toast } from '../shared/toast';
import { IconPlus } from '../shared/icons';
import { INK_DIM, INK_SOFT } from '../shared/styles';
import { pageHeading, btnPrimary, btnSmall, listContainer } from './styles';
import { matchesFilter } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { ListFilterBar } from './components/ListFilterBar';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

export function SomedayPage() {
  const isMobile = useIsMobile();
  const { contexts, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');
  const [contextFilter, setContextFilter] = useState('');

  const load = useCallback(async () => {
    try {
      const data = await api<{ todos: Todo[] }>('/api/todo/todos?status=someday_maybe&limit=500');
      setTodos(data.todos);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  async function activate(todo: Todo) {
    try {
      await api(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify({ status: 'next_action' }) });
    } catch {
      toast.error('Failed to update todo.');
      return;
    }
    reload();
  }

  const filtered = todos.filter(t => matchesFilter(t, search, contextFilter));

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={pageHeading(isMobile)}>Someday / Maybe</h1>
        <button onClick={() => setShowCreate(true)} style={{ ...btnPrimary, padding: '7px 14px', fontSize: 13 }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Someday Item'}
        </button>
      </div>

      <ListFilterBar
        search={search} onSearch={setSearch}
        context={contextFilter} onContext={setContextFilter} contexts={contexts}
        isMobile={isMobile} placeholder="Search someday items..."
      />

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load someday items" onRetry={load} />
      ) : todos.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>No someday/maybe items parked.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>Nothing matches your filter.</p>
        </div>
      ) : (
        <div style={listContainer(isMobile)}>
          {filtered.map(todo => (
            <TodoRow
              key={todo.id}
              todo={todo}
              onChanged={reload}
              onOpen={setEditTodo}
              trailing={
                <button
                  onClick={e => { e.stopPropagation(); activate(todo); }}
                  style={{ ...btnSmall, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: INK_SOFT }}
                >→ Next</button>
              }
            />
          ))}
        </div>
      )}

      {showCreate && (
        <TodoEditSheet
          defaults={{ status: 'someday_maybe' }}
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
