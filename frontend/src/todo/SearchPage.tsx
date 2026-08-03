import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo, TodoStatus } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { INK_DIM, INK_SOFT, inputStyle } from '../shared/styles';
import { pageHeading, sectionHeading, listContainer } from './styles';
import { groupByContext } from './util';
import { STATUS_META, TODO_STATUS_ORDER } from './constants';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

const OPEN_STATUSES: TodoStatus[] = [
  'inbox', 'next_action', 'waiting_for', 'delegated', 'someday_maybe',
];

/**
 * Contexts browse + global search results. The query comes from ?q= — typed
 * into the always-visible header search box, never on this page. With no
 * query, every open todo is shown grouped by context; with one, the whole
 * list (all statuses, including finished) is searched server-side and
 * grouped by status.
 */
export function SearchPage() {
  const isMobile = useIsMobile();
  const { contexts, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [searchParams] = useSearchParams();
  const query = searchParams.get('q') || '';
  const [context, setContext] = useState('');
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (q: string) => {
    const mySeq = ++seq.current;
    try {
      let results: Todo[];
      if (q.trim()) {
        const data = await api<{ todos: Todo[] }>(
          `/api/todo/todos?search=${encodeURIComponent(q.trim())}&limit=500`,
        );
        results = data.todos;
      } else {
        const lists = await Promise.all(OPEN_STATUSES.map(s =>
          api<{ todos: Todo[] }>(`/api/todo/todos?status=${s}&limit=500`)));
        results = lists.flatMap(l => l.todos);
      }
      if (mySeq !== seq.current) return; // a newer request superseded this one
      setTodos(results);
      setLoadFailed(false);
    } catch {
      if (mySeq !== seq.current) return;
      setLoadFailed(true);
    }
    setLoading(false);
  }, []);

  // Debounced live search (the header box updates ?q= per keystroke);
  // instant initial browse load.
  useEffect(() => {
    const t = setTimeout(() => { load(query); }, query ? 250 : 0);
    return () => clearTimeout(t);
  }, [query, load]);

  const reload = useCallback(() => { load(query); refreshMeta(); }, [load, query, refreshMeta]);

  const searching = query.trim().length > 0;

  const visible = useMemo(
    () => context
      ? todos.filter(t => t.context.toLowerCase() === context.toLowerCase())
      : todos,
    [todos, context],
  );

  // Search results group by status; the browse view groups by context.
  const groups = useMemo(() => {
    if (searching) {
      return TODO_STATUS_ORDER
        .map(s => ({
          key: s as string,
          label: STATUS_META[s].label,
          color: STATUS_META[s].color as string | undefined,
          items: visible.filter(t => t.status === s),
        }))
        .filter(g => g.items.length > 0);
    }
    return groupByContext(visible).map(([ctx, items]) => ({
      key: ctx || '(none)',
      label: ctx || 'No context',
      color: undefined as string | undefined,
      items,
    }));
  }, [visible, searching]);

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <h1 style={{ ...pageHeading(isMobile), marginBottom: 8 }}>
        {searching ? 'Search' : 'Contexts'}
      </h1>
      <p style={{ color: INK_SOFT, fontSize: 14, margin: '0 0 20px', lineHeight: 1.5 }}>
        {searching
          ? `Everything matching "${query.trim()}" — titles, notes, tags, projects, and contexts, including finished items.`
          : 'Everything open, grouped by context. The search box above searches your whole list.'}
      </p>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: isMobile ? 16 : 24 }}>
        <select
          value={context}
          onChange={e => setContext(e.target.value)}
          aria-label="Filter by context"
          style={{ ...inputStyle, width: 'auto', maxWidth: 200, padding: '7px 12px' }}
        >
          <option value="">All contexts</option>
          {contexts.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load todos" onRetry={() => load(query)} />
      ) : visible.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            {searching ? `No matches for "${query.trim()}".` : 'Nothing open. Mind like water.'}
          </p>
        </div>
      ) : (
        <>
          {searching && todos.length >= 500 && (
            <p style={{ color: INK_DIM, fontSize: 13, margin: '0 0 16px' }}>
              Showing the first 500 matches — refine your search to narrow down.
            </p>
          )}
          {groups.map(group => (
            <div key={group.key} style={{ marginBottom: 28 }}>
              <div style={sectionHeading(group.color)}>
                {group.label.toUpperCase()} · {group.items.length}
              </div>
              <div style={listContainer(isMobile)}>
                {group.items.map(todo => (
                  <TodoRow key={todo.id} todo={todo} onChanged={reload} onOpen={setEditTodo} />
                ))}
              </div>
            </div>
          ))}
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
