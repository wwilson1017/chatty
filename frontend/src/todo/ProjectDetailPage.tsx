import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { api } from '../core/api/client';
import type { Todo, TodoStatus } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { LoadError } from '../shared/LoadError';
import { toast } from '../shared/toast';
import { IconArrowLeft } from '../shared/icons';
import { FONT_MONO, GOLD, INK_DIM, INK_SOFT, inputStyle } from '../shared/styles';
import { pageHeading, sectionHeading, btnSecondary, btnPrimary, listContainer } from './styles';
import { PROJECT_STATUS_META, STATUS_META } from './constants';
import { TodoRow } from './components/TodoRow';
import { TodoEditSheet } from './components/TodoEditSheet';
import { ProjectForm } from './components/ProjectForm';
import { LoadingSpinner } from './components/LoadingSpinner';
import type { TodoOutletContext } from './TodoLayout';

const SECTIONS: { label: string; statuses: TodoStatus[] }[] = [
  { label: 'Next Actions', statuses: ['next_action'] },
  { label: 'Waiting / Delegated', statuses: ['waiting_for', 'delegated'] },
  { label: 'Someday', statuses: ['someday_maybe'] },
  { label: 'Inbox', statuses: ['inbox'] },
  { label: 'Finished', statuses: ['done', 'dropped'] },
];

export function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { projects, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editTodo, setEditTodo] = useState<Todo | null>(null);
  const [editProject, setEditProject] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [adding, setAdding] = useState(false);

  const project = projects.find(p => p.id === projectId) || null;

  const load = useCallback(async () => {
    try {
      const data = await api<{ todos: Todo[] }>(`/api/todo/todos?project=${projectId}&limit=500`);
      setTodos(data.todos);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, [projectId]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const reload = useCallback(() => { load(); refreshMeta(); }, [load, refreshMeta]);

  const grouped = useMemo(() => SECTIONS.map(section => ({
    ...section,
    items: todos.filter(t => section.statuses.includes(t.status)),
  })), [todos]);

  const hasNextAction = todos.some(t => t.status === 'next_action');

  async function addNextAction() {
    const title = newTitle.trim();
    if (!title || adding) return;
    setAdding(true);
    try {
      await api('/api/todo/todos', {
        method: 'POST',
        body: JSON.stringify({ title, status: 'next_action', project_id: projectId }),
      });
      setNewTitle('');
      reload();
    } catch {
      toast.error('Failed to add todo.');
    }
    setAdding(false);
  }

  if (!project) {
    return (
      <div style={{ padding: isMobile ? '20px 16px' : '32px 44px' }}>
        {projects.length === 0 ? (
          <LoadingSpinner />
        ) : (
          <LoadError label="Project not found" onRetry={() => navigate('/todos/projects')} />
        )}
      </div>
    );
  }

  const meta = PROJECT_STATUS_META[project.status];

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <button
        onClick={() => navigate('/todos/projects')}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: INK_SOFT, fontSize: 13, padding: 0, marginBottom: 16,
        }}
      >
        <IconArrowLeft size={14} /> Projects
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <h1 style={pageHeading(isMobile)}>{project.name}</h1>
        <span style={{
          fontSize: 11, padding: '3px 10px', borderRadius: 4,
          fontFamily: FONT_MONO, letterSpacing: '0.08em', fontWeight: 500,
          background: meta.bg, color: meta.color,
        }}>{meta.label}</span>
        <div style={{ flex: 1 }} />
        <button onClick={() => setEditProject(true)} style={{ ...btnSecondary, padding: '7px 14px', fontSize: 13 }}>
          Edit
        </button>
      </div>

      {project.notes && (
        <p style={{ fontSize: 14, color: INK_SOFT, lineHeight: 1.55, margin: '0 0 20px', whiteSpace: 'pre-wrap' }}>
          {project.notes}
        </p>
      )}

      {project.status === 'active' && !hasNextAction && (
        <div style={{
          background: 'rgba(212,168,90,0.08)', border: '1px solid rgba(212,168,90,0.15)',
          borderRadius: 6, padding: '10px 14px', marginBottom: 20,
          fontSize: 13, color: GOLD,
        }}>
          This active project has no next action — what's the very next physical step?
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        <input
          value={newTitle}
          onChange={e => setNewTitle(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') addNextAction(); }}
          placeholder="Add a next action to this project..."
          style={{ ...inputStyle, flex: 1 }}
        />
        <button
          onClick={addNextAction}
          disabled={adding || !newTitle.trim()}
          style={{ ...btnPrimary, opacity: adding || !newTitle.trim() ? 0.5 : 1 }}
        >Add</button>
      </div>

      {loadFailed && todos.length === 0 ? (
        <LoadError label="Couldn't load this project's todos" onRetry={load} />
      ) : (
        grouped.map(section => section.items.length > 0 && (
          <div key={section.label} style={{ marginBottom: 28 }}>
            <div style={sectionHeading(section.label === 'Next Actions' ? STATUS_META.next_action.color : undefined)}>
              {section.label.toUpperCase()} · {section.items.length}
            </div>
            <div style={listContainer(isMobile)}>
              {section.items.map(todo => (
                <TodoRow
                  key={todo.id}
                  todo={todo}
                  onChanged={reload}
                  onOpen={setEditTodo}
                  showProject={false}
                />
              ))}
            </div>
          </div>
        ))
      )}

      {todos.length === 0 && !loadFailed && (
        <p style={{ color: INK_DIM, fontSize: 14, textAlign: 'center', padding: '32px 0' }}>
          Nothing in this project yet.
        </p>
      )}

      {editTodo && (
        <TodoEditSheet
          todo={editTodo}
          onClose={() => setEditTodo(null)}
          onSaved={() => { setEditTodo(null); reload(); }}
        />
      )}
      {editProject && (
        <ProjectForm
          project={project}
          onClose={() => setEditProject(false)}
          onSaved={(deleted) => {
            setEditProject(false);
            refreshMeta();
            if (deleted) navigate('/todos/projects');
            else reload();
          }}
        />
      )}
    </div>
  );
}
