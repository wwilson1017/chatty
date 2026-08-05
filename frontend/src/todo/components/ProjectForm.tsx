import { useState } from 'react';
import { todoApi } from '../api';
import type { TodoProject, TodoProjectStatus } from '../../core/types';
import { toast } from '../../shared/toast';
import { confirmDialog } from '../../shared/confirm';
import { labelStyle, inputStyle, CORAL } from '../../shared/styles';
import { formModalOverlay, formModalContent, formTitle, btnPrimary, btnSecondary, btnDanger } from '../styles';
import { PROJECT_STATUS_META, PROJECT_STATUS_ORDER } from '../constants';

interface Props {
  project?: TodoProject;
  onClose: () => void;
  /** deleted=true when the project was removed (caller may need to navigate away). */
  onSaved: (deleted?: boolean) => void;
}

export function ProjectForm({ project, onClose, onSaved }: Props) {
  const isEdit = !!project;
  const [name, setName] = useState(project?.name || '');
  const [notes, setNotes] = useState(project?.notes || '');
  const [status, setStatus] = useState<TodoProjectStatus>(project?.status || 'active');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setError('Name is required'); return; }
    setSaving(true); setError('');
    try {
      const body = JSON.stringify({ name: name.trim(), notes, status });
      if (isEdit) {
        await todoApi(`/api/todo/projects/${project.id}`, { method: 'PUT', body });
      } else {
        await todoApi('/api/todo/projects', { method: 'POST', body });
      }
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
    setSaving(false);
  }

  async function handleDelete() {
    if (!project) return;
    const ok = await confirmDialog({
      title: 'Delete project',
      message: `Delete "${project.name}"? Its todos are kept — they just lose the project assignment.`,
      confirmLabel: 'Delete project',
      danger: true,
    });
    if (!ok) return;
    try {
      await todoApi(`/api/todo/projects/${project.id}`, { method: 'DELETE' });
    } catch {
      toast.error('Failed to delete project.');
      return;
    }
    onSaved(true);
  }

  return (
    <div style={formModalOverlay} onClick={onClose}>
      <form onClick={e => e.stopPropagation()} onSubmit={handleSubmit} style={formModalContent()}>
        <h2 style={formTitle}>{isEdit ? 'Edit Project' : 'New Project'}</h2>
        {error && <p style={{ color: CORAL, fontSize: 12, marginBottom: 12 }}>{error}</p>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={labelStyle}>Project name *</label>
            <input value={name} onChange={e => setName(e.target.value)} style={inputStyle} autoFocus={!isEdit} />
          </div>
          <div>
            <label style={labelStyle}>Notes / desired outcome</label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>
          <div>
            <label style={labelStyle}>Status</label>
            <select value={status} onChange={e => setStatus(e.target.value as TodoProjectStatus)} style={inputStyle}>
              {PROJECT_STATUS_ORDER.map(s => (
                <option key={s} value={s}>{PROJECT_STATUS_META[s].label}</option>
              ))}
            </select>
          </div>
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
