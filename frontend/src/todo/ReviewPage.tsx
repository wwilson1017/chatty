import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { FONT_DISPLAY, GOLD, INK, INK_DIM, INK_SOFT, mono } from '../shared/styles';
import { pageHeading, sectionHeading, cardStyle } from './styles';
import { STALE_DAYS, STATUS_META } from './constants';
import { daysSince } from './util';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import type { TodoOutletContext } from './TodoLayout';

/** Read-only weekly-review overview: counts, stale items, projects w/o next action. */
export function ReviewPage() {
  const isMobile = useIsMobile();
  const { counts, projects, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [openItems, setOpenItems] = useState<Todo[]>([]);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);

  const load = useCallback(async () => {
    try {
      const [next, waiting, delegated] = await Promise.all([
        api<{ todos: Todo[] }>('/api/todo/todos?status=next_action&limit=500'),
        api<{ todos: Todo[] }>('/api/todo/todos?status=waiting_for&limit=500'),
        api<{ todos: Todo[] }>('/api/todo/todos?status=delegated&limit=500'),
      ]);
      setOpenItems([...next.todos, ...waiting.todos, ...delegated.todos]);
    } catch {
      // tiles still render from counts; stale/projects sections show nothing
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  const stale = useMemo(
    () => openItems
      .filter(t => daysSince(t.updated_at) >= STALE_DAYS)
      .sort((a, b) => a.updated_at.localeCompare(b.updated_at)),
    [openItems],
  );

  const projectsWithoutNext = useMemo(() => {
    const withNext = new Set(
      openItems.filter(t => t.status === 'next_action' && t.project_id != null).map(t => t.project_id),
    );
    return projects.filter(p => p.status === 'active' && !withNext.has(p.id));
  }, [openItems, projects]);

  const tiles: { label: string; value: number; color?: string; to: string }[] = [
    { label: 'Inbox', value: counts.inbox, color: STATUS_META.inbox.color, to: '/todos' },
    { label: 'Next', value: counts.next_action, color: STATUS_META.next_action.color, to: '/todos/next' },
    { label: 'Waiting', value: counts.waiting_for + counts.delegated, color: STATUS_META.waiting_for.color, to: '/todos/waiting' },
    { label: 'Someday', value: counts.someday_maybe, color: STATUS_META.someday_maybe.color, to: '/todos/someday' },
    { label: 'Done', value: counts.done, color: STATUS_META.done.color, to: '/todos/done' },
  ];

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <h1 style={{ ...pageHeading(isMobile), marginBottom: 8 }}>Review</h1>
      <p style={{ color: INK_SOFT, fontSize: 14, margin: '0 0 24px', lineHeight: 1.5 }}>
        The weekly once-over: empty the inbox, give every active project a next action,
        chase stale waiting items, prune someday/maybe.
      </p>

      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(5, 1fr)',
        gap: 10, marginBottom: 32,
      }}>
        {tiles.map(tile => (
          <Link key={tile.label} to={tile.to} style={{ textDecoration: 'none' }}>
            <div style={{ ...cardStyle, padding: '14px 16px', borderLeft: `3px solid ${tile.color}` }}>
              <div style={{ fontFamily: FONT_DISPLAY, fontSize: 28, color: INK, lineHeight: 1 }}>
                {tile.value}
              </div>
              <div style={{ ...mono(11, INK_DIM), marginTop: 6 }}>{tile.label.toUpperCase()}</div>
            </div>
          </Link>
        ))}
      </div>

      <div style={{ marginBottom: 32 }}>
        <div style={sectionHeading(GOLD)}>
          STALE — UNTOUCHED {STALE_DAYS}+ DAYS · {stale.length}
        </div>
        {stale.length === 0 ? (
          <p style={{ color: INK_DIM, fontSize: 13, margin: 0 }}>Nothing stale. Everything's moving.</p>
        ) : (
          <div style={isMobile
            ? { display: 'flex', flexDirection: 'column', gap: 8 }
            : { borderTop: '1px solid rgba(230,235,242,0.07)' }
          }>
            {stale.map(todo => (
              <TodoRow
                key={todo.id}
                todo={todo}
                onChanged={reload}
                onOpen={setEditTodo}
                trailing={<span style={mono(11, GOLD)}>{daysSince(todo.updated_at)}d idle</span>}
              />
            ))}
          </div>
        )}
      </div>

      <div>
        <div style={sectionHeading(STATUS_META.next_action.color)}>
          ACTIVE PROJECTS WITHOUT A NEXT ACTION · {projectsWithoutNext.length}
        </div>
        {projectsWithoutNext.length === 0 ? (
          <p style={{ color: INK_DIM, fontSize: 13, margin: 0 }}>Every active project has a next action. Textbook.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {projectsWithoutNext.map(project => (
              <Link
                key={project.id}
                to={`/todos/projects/${project.id}`}
                style={{ textDecoration: 'none' }}
              >
                <div style={{ ...cardStyle, padding: '12px 16px', fontSize: 14, color: INK }}>
                  {project.name}
                  <span style={{ color: INK_SOFT, fontSize: 13, marginLeft: 10 }}>
                    {project.open_count} open item{project.open_count === 1 ? '' : 's'}, none actionable
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

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
