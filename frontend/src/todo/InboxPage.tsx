import { useCallback, useEffect, useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { FONT_DISPLAY, INK, INK_DIM, SAGE } from '../shared/styles';
import { pageHeading, sectionHeading, listContainer } from './styles';
import { TriageCard } from './components/TriageCard';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

export function InboxPage() {
  const isMobile = useIsMobile();
  const { projects, refreshMeta, quickAddSeq } = useOutletContext<TodoOutletContext>();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const load = useCallback(async () => {
    try {
      // Server order is FIFO (oldest first) — process in capture order.
      const data = await api<{ todos: Todo[] }>('/api/todo/todos?status=inbox&limit=500');
      setTodos(data.todos);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load, quickAddSeq]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  const active = todos.find(t => t.id === activeId) || todos[0] || null;
  const rest = todos.filter(t => t.id !== (active?.id ?? -1));

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <h1 style={{ ...pageHeading(isMobile), marginBottom: isMobile ? 16 : 24 }}>Inbox</h1>

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load your inbox" onRetry={load} />
      ) : !active ? (
        <div style={{ textAlign: 'center', padding: '72px 0' }}>
          <div style={{ fontSize: 28, marginBottom: 12, color: SAGE }}>✓</div>
          <p style={{ fontFamily: FONT_DISPLAY, fontSize: 24, color: INK, margin: '0 0 8px' }}>Inbox zero</p>
          <p style={{ color: INK_DIM, fontSize: 14, margin: 0 }}>
            Everything is captured and clarified. Mind like water.
          </p>
        </div>
      ) : (
        <>
          <TriageCard
            todo={active}
            projects={projects}
            onProcessed={reload}
            onChanged={reload}
            onEdit={setEditTodo}
          />

          {rest.length > 0 && (
            <>
              <div style={sectionHeading()}>{rest.length} MORE IN INBOX</div>
              <div style={listContainer(isMobile)}>
                {rest.map(todo => (
                  <TodoRow
                    key={todo.id}
                    todo={todo}
                    onChanged={reload}
                    onOpen={t => setActiveId(t.id)}
                  />
                ))}
              </div>
            </>
          )}
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
