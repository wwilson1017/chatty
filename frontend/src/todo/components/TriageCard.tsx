import { useState } from 'react';
import { todoApi } from '../api';
import type { Todo, TodoProject, TodoStatus } from '../../core/types';
import { useIsMobile } from '../../shared/useIsMobile';
import { toast } from '../../shared/toast';
import { confirmDialog } from '../../shared/confirm';
import { IconStar, IconStarFilled } from '../../shared/icons';
import {
  FONT_DISPLAY, GOLD, INK, INK_DIM, INK_MUTE, INK_SOFT,
  inputStyle, mono, SAGE, ACCENT_INK, LINE_STRONG,
} from '../../shared/styles';
import { cardStyle, btnSecondary, btnDanger } from '../styles';
import { SourceBadge } from './badges';
import { InlineTitle } from './InlineTitle';
import { formatAgeAgo } from '../util';

interface Props {
  todo: Todo;
  projects: TodoProject[];
  /** Contexts already in use — the options for the final "set context" step. */
  contexts: string[];
  /** Called after any mutation that resolves this item (status move / delete). */
  onProcessed: () => void;
  /** Called after an in-place change (project, due date, star). */
  onChanged: () => void;
  onEdit: (todo: Todo) => void;
}

// Where the item is headed once it is filed. Picking one is a local decision —
// nothing is written until the context step below, so the item stays in the
// inbox (and on this card) while you keep clarifying it.
const DESTINATIONS: { label: string; status: TodoStatus; list: string }[] = [
  { label: 'Next action', status: 'next_action', list: 'To Do' },
  { label: 'Waiting', status: 'waiting_for', list: 'Waiting For' },
  { label: 'Delegated', status: 'delegated', list: 'Delegated' },
  { label: 'Someday', status: 'someday_maybe', list: 'Someday / Maybe' },
];

const NEW_CONTEXT = '__new__';
const NEW_PROJECT = '__new__';

/** Inbox processing card — clarify the head item one decision at a time. */
export function TriageCard({ todo, projects, contexts, onProcessed, onChanged, onEdit }: Props) {
  const isMobile = useIsMobile();
  const [busy, setBusy] = useState(false);
  const [newContext, setNewContext] = useState<string | null>(null);
  const [newProject, setNewProject] = useState<string | null>(null);
  const [destination, setDestination] = useState<TodoStatus>('next_action');
  const dest = DESTINATIONS.find(d => d.status === destination) ?? DESTINATIONS[0];

  async function patch(fields: Record<string, unknown>, resolves: boolean) {
    if (busy) return;
    setBusy(true);
    try {
      await todoApi(`/api/todo/todos/${todo.id}`, { method: 'PUT', body: JSON.stringify(fields) });
      (resolves ? onProcessed : onChanged)();
    } catch {
      toast.error('Failed to update todo.');
    }
    setBusy(false);
  }

  /**
   * Create a project without leaving triage and file this item under it.
   * Name only — the outcome/notes belong to the weekly review, not to
   * clarifying one inbox item.
   */
  async function createProject(name: string) {
    const value = name.trim();
    if (busy || !value) return;
    setBusy(true);
    try {
      const created = await todoApi<{ id: number }>('/api/todo/projects', {
        method: 'POST', body: JSON.stringify({ name: value }),
      });
      await todoApi(`/api/todo/todos/${todo.id}`, {
        method: 'PUT', body: JSON.stringify({ project_id: created.id }),
      });
      setNewProject(null);
      // Refreshes the project list too, so the new one is in the dropdown.
      onChanged();
    } catch {
      toast.error('Failed to create project.');
    }
    setBusy(false);
  }

  /**
   * The last step: context + the chosen destination in one write, so the item
   * leaves the inbox. A context is always required — this is the only path out.
   */
  async function fileUnder(context: string) {
    const value = context.trim();
    if (busy || !value) return;
    setBusy(true);
    try {
      await todoApi(`/api/todo/todos/${todo.id}`, {
        method: 'PUT',
        body: JSON.stringify({ context: value, status: destination }),
      });
      toast.success(`Filed under ${value} → ${dest.list}`);
      setNewContext(null);
      onProcessed();
    } catch {
      toast.error('Failed to update todo.');
    }
    setBusy(false);
  }

  function onContextPick(value: string) {
    if (!value) return;
    if (value === NEW_CONTEXT) { setNewContext(''); return; }
    fileUnder(value);
  }

  async function handleDelete() {
    const ok = await confirmDialog({
      title: 'Delete todo',
      message: `Permanently delete "${todo.title}"?`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await todoApi(`/api/todo/todos/${todo.id}`, { method: 'DELETE' });
      onProcessed();
    } catch {
      toast.error('Failed to delete todo.');
    }
  }

  const stepLabel = (n: number, text: string): React.ReactNode => (
    <div style={{ ...mono(11, INK_DIM), marginBottom: 8 }}>
      <span style={{ color: INK_SOFT }}>{n}.</span> {text}
    </div>
  );

  return (
    <div style={{ ...cardStyle, padding: isMobile ? '16px 14px' : '22px 24px', marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 8 }}>
        <h2 style={{ margin: 0, flex: 1, minWidth: 0, fontWeight: 400 }}>
          <InlineTitle
            todoId={todo.id}
            title={todo.title}
            onSaved={onChanged}
            multiline
            style={{
              fontFamily: FONT_DISPLAY, fontSize: isMobile ? 21 : 26, fontWeight: 400,
              letterSpacing: '-0.01em', color: INK, lineHeight: 1.25,
              overflowWrap: 'anywhere',
            }}
          />
        </h2>
        <button
          onClick={() => patch({ star: !todo.star }, false)}
          title={todo.star ? 'Unstar' : 'Star as today’s priority'}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: todo.star ? GOLD : INK_DIM, padding: 4,
          }}
        >
          {todo.star ? <IconStarFilled size={18} /> : <IconStar size={18} />}
        </button>
      </div>

      {todo.notes && (
        <p style={{ fontSize: 14, color: INK_MUTE, lineHeight: 1.55, margin: '0 0 12px', whiteSpace: 'pre-wrap' }}>
          {todo.notes}
        </p>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 20 }}>
        <SourceBadge source={todo.source} />
        <span style={mono(11, INK_DIM)}>captured {formatAgeAgo(todo.created_at)}</span>
      </div>

      {/* Step 1 — choose where it lands. Selecting is local: the item stays put
          until step 3 gives it a context. */}
      {stepLabel(1, 'WHAT KIND OF ACTION?')}
      <div style={{
        display: isMobile ? 'grid' : 'flex',
        gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10,
        flexWrap: 'wrap',
      }}>
        {DESTINATIONS.map(d => {
          const selected = d.status === destination;
          return (
            <button
              key={d.status}
              onClick={() => setDestination(d.status)}
              aria-pressed={selected}
              style={{
                ...btnSecondary,
                padding: '10px 14px', fontSize: 14,
                borderColor: selected ? SAGE : undefined,
                color: selected ? INK : INK_MUTE,
                background: selected ? 'rgba(142,165,137,0.12)' : 'transparent',
                fontWeight: selected ? 500 : 400,
              }}
            >{d.label}</button>
          );
        })}
      </div>
      <div style={{ marginBottom: 18 }}>
        <button
          disabled={busy}
          onClick={() => patch({ status: 'done' }, true)}
          title="It took under 2 minutes — done"
          style={{
            ...btnSecondary, padding: '8px 14px', fontSize: 13,
            color: SAGE, opacity: busy ? 0.6 : 1,
          }}
        >Took 2 minutes — Done ✓</button>
      </div>

      {/* Step 2 — optional enrichment. Nothing here leaves the inbox. */}
      {stepLabel(2, 'ADD DETAIL (OPTIONAL)')}
      <div style={{
        display: isMobile ? 'grid' : 'flex',
        gridTemplateColumns: '1fr 1fr', gap: 8, alignItems: 'center',
        flexWrap: 'wrap', marginBottom: 18,
      }}>
        {newProject === null ? (
          <select
            value={todo.project_id ?? ''}
            onChange={e => {
              if (e.target.value === NEW_PROJECT) { setNewProject(''); return; }
              patch({ project_id: e.target.value ? Number(e.target.value) : null }, false);
            }}
            aria-label="Project"
            style={{ ...inputStyle, width: isMobile ? '100%' : 180, padding: '8px 10px', fontSize: 13 }}
          >
            <option value="">No project</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            <option value={NEW_PROJECT}>+ New project…</option>
          </select>
        ) : (
          <form
            onSubmit={e => { e.preventDefault(); createProject(newProject); }}
            style={{ display: 'flex', gap: 8, gridColumn: '1 / -1' }}
          >
            <input
              value={newProject}
              onChange={e => setNewProject(e.target.value)}
              placeholder="New project name"
              autoFocus
              aria-label="New project name"
              style={{ ...inputStyle, width: isMobile ? '100%' : 180, padding: '8px 10px', fontSize: 13 }}
            />
            <button
              type="submit"
              disabled={busy || !newProject.trim()}
              style={{
                ...btnSecondary, padding: '8px 14px', fontSize: 13,
                borderColor: SAGE, color: INK,
                opacity: busy || !newProject.trim() ? 0.5 : 1,
              }}
            >Create</button>
            <button
              type="button"
              onClick={() => setNewProject(null)}
              style={{ ...btnSecondary, padding: '8px 14px', fontSize: 13 }}
            >Cancel</button>
          </form>
        )}
        <input
          type="date"
          value={todo.due_date || ''}
          onChange={e => patch({ due_date: e.target.value || null }, false)}
          aria-label="Due date"
          style={{ ...inputStyle, width: isMobile ? '100%' : 160, padding: '8px 10px', fontSize: 13 }}
        />
        <button onClick={() => onEdit(todo)} style={{ ...btnSecondary, padding: '8px 14px', fontSize: 13 }}>
          Edit
        </button>
        <button onClick={handleDelete} style={{ ...btnDanger, padding: '8px 14px', fontSize: 13 }}>
          Delete
        </button>
      </div>

      {/* Step 3 — the last step. Picking a context files it and clears the inbox. */}
      <div style={{
        borderTop: `1px solid ${LINE_STRONG}`, paddingTop: 16,
      }}>
        {stepLabel(3, 'LAST STEP — SET CONTEXT (REQUIRED)')}
        <p style={{ fontSize: 13, color: INK_MUTE, margin: '0 0 10px', lineHeight: 1.5 }}>
          Where can you actually do this? Every item needs a context before it leaves the
          inbox. Choosing one files it under{' '}
          <strong style={{ color: INK, fontWeight: 500 }}>{dest.list}</strong> and clears it out
          of your inbox — do it last.
        </p>

        {newContext === null ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <select
              value=""
              disabled={busy}
              onChange={e => onContextPick(e.target.value)}
              aria-label="Set context and file this todo"
              style={{
                ...inputStyle, width: isMobile ? '100%' : 260,
                padding: '10px 12px', fontSize: 14,
                borderColor: SAGE, color: INK,
                opacity: busy ? 0.6 : 1,
              }}
            >
              <option value="">Set context…</option>
              {contexts.map(c => <option key={c} value={c}>{c}</option>)}
              <option value={NEW_CONTEXT}>+ New context…</option>
            </select>
            {todo.context && (
              <span style={mono(11, INK_DIM)}>currently {todo.context}</span>
            )}
          </div>
        ) : (
          <form
            onSubmit={e => { e.preventDefault(); if (newContext.trim()) fileUnder(newContext); }}
            style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
          >
            <input
              value={newContext}
              onChange={e => setNewContext(e.target.value)}
              placeholder="@home, @calls, @errands..."
              autoFocus
              aria-label="New context"
              style={{
                ...inputStyle, width: isMobile ? '100%' : 220,
                padding: '10px 12px', fontSize: 14, borderColor: SAGE,
              }}
            />
            <button
              type="submit"
              disabled={busy || !newContext.trim()}
              style={{
                background: SAGE, color: ACCENT_INK, border: 'none', borderRadius: 4,
                padding: '10px 16px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
                opacity: busy || !newContext.trim() ? 0.5 : 1,
              }}
            >File →</button>
            <button
              type="button"
              onClick={() => setNewContext(null)}
              style={{ ...btnSecondary, padding: '9px 14px', fontSize: 13 }}
            >Cancel</button>
          </form>
        )}
      </div>
    </div>
  );
}
