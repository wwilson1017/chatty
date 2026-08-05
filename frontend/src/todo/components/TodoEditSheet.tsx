import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { todoApi } from '../api';
import type { Todo, TodoRepeat, TodoStatus } from '../../core/types';
import { useIsMobile } from '../../shared/useIsMobile';
import { toast } from '../../shared/toast';
import { confirmDialog } from '../../shared/confirm';
import { labelStyle, inputStyle, CORAL, GOLD, INK_DIM, INK_SOFT, mono } from '../../shared/styles';
import { IconStar, IconStarFilled } from '../../shared/icons';
import { modalOverlay, modalContent, mobileDragHandle, formTitle, btnPrimary, btnSecondary, btnDanger } from '../styles';
import { STATUS_META, TODO_STATUS_ORDER, SOURCE_LABELS } from '../constants';
import { parseTags } from '../util';
import type { TodoOutletContext } from '../TodoLayout';

const NEW_PROJECT_SENTINEL = '__new__';

interface Props {
  /** Present = edit mode; absent = create mode. */
  todo?: Todo;
  /** Field presets for create mode (e.g. { status: 'next_action', project_id }). */
  defaults?: Partial<Pick<Todo, 'status' | 'project_id'>>;
  onClose: () => void;
  onSaved: () => void;
}

/** Full-field editor: centered modal on desktop, bottom sheet on mobile. */
export function TodoEditSheet({ todo, defaults, onClose, onSaved }: Props) {
  const isEdit = !!todo;
  const isMobile = useIsMobile();
  const { projects, contexts, refreshMeta } = useOutletContext<TodoOutletContext>();

  const [title, setTitle] = useState(todo?.title || '');
  const [notes, setNotes] = useState(todo?.notes || '');
  const [status, setStatus] = useState<TodoStatus>(todo?.status || defaults?.status || 'inbox');
  const [projectId, setProjectId] = useState<number | null>(todo?.project_id ?? defaults?.project_id ?? null);
  const [newProject, setNewProject] = useState<string | null>(null);
  const [context, setContext] = useState(todo?.context || '');
  const [tagsInput, setTagsInput] = useState((todo?.tags || []).join(', '));
  const [star, setStar] = useState(todo?.star || false);
  const [dueDate, setDueDate] = useState(todo?.due_date || '');
  const [repeat, setRepeat] = useState<TodoRepeat>(todo?.repeat || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true); setError('');
    try {
      let pid = projectId;
      if (newProject !== null && newProject.trim()) {
        const created = await todoApi<{ id: number }>('/api/todo/projects', {
          method: 'POST', body: JSON.stringify({ name: newProject.trim() }),
        });
        pid = created.id;
      }
      const body = {
        title: title.trim(), notes, status, project_id: pid,
        context: context.trim(), tags: parseTags(tagsInput),
        star, due_date: dueDate || null, repeat,
      };
      if (isEdit) {
        await todoApi(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await todoApi('/api/todo/todos', { method: 'POST', body: JSON.stringify(body) });
      }
      refreshMeta();
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
    setSaving(false);
  }

  async function handleDelete() {
    if (!todo) return;
    const ok = await confirmDialog({
      title: 'Delete todo',
      message: `Permanently delete "${todo.title}"? Consider marking it Dropped instead to keep history.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await todoApi(`/api/todo/todos/${todo.id}`, { method: 'DELETE' });
    } catch {
      toast.error('Failed to delete todo.');
      return;
    }
    refreshMeta();
    onSaved();
  }

  return (
    <div style={modalOverlay(isMobile)} onClick={onClose}>
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={handleSubmit}
        style={{ ...modalContent(isMobile, 520), maxHeight: '92vh', overflowY: 'auto' }}
      >
        {isMobile && (
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <div style={mobileDragHandle} />
          </div>
        )}
        <h2 style={formTitle}>{isEdit ? 'Edit Todo' : 'New Todo'}</h2>
        {error && <p style={{ color: CORAL, fontSize: 12, marginBottom: 12 }}>{error}</p>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={labelStyle}>What's the next action? *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} style={inputStyle} autoFocus={!isEdit} />
          </div>

          <div>
            <label style={labelStyle}>Notes</label>
            <textarea
              value={notes} onChange={e => setNotes(e.target.value)} rows={3}
              placeholder="Links, phone numbers, extra context..."
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>Status</label>
              <select value={status} onChange={e => setStatus(e.target.value as TodoStatus)} style={inputStyle}>
                {TODO_STATUS_ORDER.map(s => (
                  <option key={s} value={s}>{STATUS_META[s].label}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Due Date</label>
              <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} style={inputStyle} />
            </div>
          </div>

          <div>
            <label style={labelStyle}>Repeat</label>
            <select value={repeat} onChange={e => setRepeat(e.target.value as TodoRepeat)} style={inputStyle}>
              <option value="">Doesn't repeat</option>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
            </select>
            {repeat && (
              <p style={{ fontSize: 12, color: INK_SOFT, margin: '6px 0 0' }}>
                Completing this creates the next occurrence automatically.
              </p>
            )}
          </div>

          <div>
            <label style={labelStyle}>Project</label>
            {newProject === null ? (
              <select
                value={projectId ?? ''}
                onChange={e => {
                  if (e.target.value === NEW_PROJECT_SENTINEL) { setNewProject(''); setProjectId(null); }
                  else setProjectId(e.target.value ? Number(e.target.value) : null);
                }}
                style={inputStyle}
              >
                <option value="">No project</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                <option value={NEW_PROJECT_SENTINEL}>+ New project...</option>
              </select>
            ) : (
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  value={newProject}
                  onChange={e => setNewProject(e.target.value)}
                  placeholder="New project name"
                  autoFocus
                  style={{ ...inputStyle, flex: 1 }}
                />
                <button
                  type="button"
                  onClick={() => setNewProject(null)}
                  style={{ ...btnSecondary, padding: '8px 12px', fontSize: 13 }}
                >Cancel</button>
              </div>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>Context</label>
              <input
                value={context} onChange={e => setContext(e.target.value)}
                list="todo-contexts" placeholder="@home, @calls..."
                style={inputStyle}
              />
              <datalist id="todo-contexts">
                {contexts.map(c => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div>
              <label style={labelStyle}>Tags</label>
              <input
                value={tagsInput} onChange={e => setTagsInput(e.target.value)}
                placeholder="comma, separated"
                style={inputStyle}
              />
            </div>
          </div>

          <button
            type="button"
            onClick={() => setStar(s => !s)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: star ? GOLD : INK_SOFT, padding: 0, fontSize: 13,
              width: 'fit-content',
            }}
          >
            {star ? <IconStarFilled size={15} /> : <IconStar size={15} />}
            {star ? 'Starred — today’s priority' : 'Star as today’s priority'}
          </button>

          {isEdit && (
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <span style={mono(10, INK_DIM)}>Source: {SOURCE_LABELS[todo.source] || todo.source}</span>
              <span style={mono(10, INK_DIM)}>Created: {todo.created_at.split(' ')[0]}</span>
              {todo.completed_at && <span style={mono(10, INK_DIM)}>Completed: {todo.completed_at.split(' ')[0]}</span>}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          {isEdit && (
            <button type="button" onClick={handleDelete} style={{ ...btnDanger, padding: '10px 14px', fontSize: 13 }}>
              Delete
            </button>
          )}
          <div style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={btnSecondary}>Cancel</button>
          <button type="submit" disabled={saving} style={{ ...btnPrimary, opacity: saving ? 0.5 : 1 }}>
            {saving ? 'Saving...' : isEdit ? 'Save' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
