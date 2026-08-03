import { useCallback, useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { IconPlus } from '../shared/icons';
import { GOLD, INK_DIM } from '../shared/styles';
import { pageHeading, sectionHeading, btnPrimary, listContainer } from './styles';
import { groupByContext, matchesFilter } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { FilterEmptyState, ListFilterBar } from './components/ListFilterBar';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

export function NextActionsPage() {
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
      const data = await api<{ todos: Todo[] }>('/api/todo/todos?status=next_action&limit=500');
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

  const filtered = useMemo(
    () => todos.filter(t => matchesFilter(t, search, contextFilter)),
    [todos, search, contextFilter],
  );

  const { starred, groups } = useMemo(() => {
    const starredItems = filtered.filter(t => t.star);
    const rest = filtered.filter(t => !t.star);
    return { starred: starredItems, groups: groupByContext(rest) };
  }, [filtered]);


  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={pageHeading(isMobile)}>Next Actions</h1>
        <button onClick={() => setShowCreate(true)} style={{ ...btnPrimary, padding: '7px 14px', fontSize: 13 }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Next Action'}
        </button>
      </div>

      <ListFilterBar
        search={search} onSearch={setSearch}
        context={contextFilter} onContext={setContextFilter} contexts={contexts}
        isMobile={isMobile} placeholder="Search next actions..."
      />

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load next actions" onRetry={load} />
      ) : todos.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            No next actions. Process your inbox or add one directly.
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <FilterEmptyState />
      ) : (
        <>
          {starred.length > 0 && (
            <div style={{ marginBottom: 28 }}>
              <div style={sectionHeading(GOLD)}>★ STARRED · {starred.length}</div>
              <div style={listContainer(isMobile)}>
                {starred.map(todo => (
                  <TodoRow key={todo.id} todo={todo} onChanged={reload} onOpen={setEditTodo} />
                ))}
              </div>
            </div>
          )}
          {groups.map(([context, items]) => (
            <div key={context || '(none)'} style={{ marginBottom: 28 }}>
              <div style={sectionHeading()}>
                {(context || 'NO CONTEXT').toUpperCase()} · {items.length}
              </div>
              <div style={listContainer(isMobile)}>
                {items.map(todo => (
                  <TodoRow key={todo.id} todo={todo} onChanged={reload} onOpen={setEditTodo} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {showCreate && (
        <TodoEditSheet
          defaults={{ status: 'next_action' }}
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
