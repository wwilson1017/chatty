import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import { labelStyle, inputStyle, CORAL } from '../../shared/styles';
import { formModalOverlay, formModalContent, formTitle, btnPrimary, btnSecondary } from '../styles';
import type { CrmContact, CrmTask } from '../../core/types';

interface Props {
  task?: CrmTask;
  contactId?: number;
  dealId?: number;
  onClose: () => void;
  onSaved: () => void;
}

export function TaskForm({ task, contactId, dealId, onClose, onSaved }: Props) {
  const isEdit = !!task;
  const [title, setTitle] = useState(task?.title || '');
  const [description, setDescription] = useState(task?.description || '');
  const [dueDate, setDueDate] = useState(task?.due_date || '');
  const [priority, setPriority] = useState(task?.priority || 'medium');
  const [selectedContact, setSelectedContact] = useState<number | null>(task?.contact_id ?? contactId ?? null);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!contactId) {
      api<{ contacts: CrmContact[] }>('/api/crm/contacts?limit=200')
        .then(d => setContacts(d.contacts)).catch(() => {});
    }
  }, [contactId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true); setError('');
    try {
      const body: Record<string, unknown> = { title, description, due_date: dueDate, priority };
      if (selectedContact) body.contact_id = selectedContact;
      if (dealId) body.deal_id = dealId;

      if (isEdit) {
        await api(`/api/crm/tasks/${task.id}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await api('/api/crm/tasks', { method: 'POST', body: JSON.stringify(body) });
      }
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Failed to save'); }
    setSaving(false);
  }

  return (
    <div style={formModalOverlay} onClick={onClose}>
      <form onClick={e => e.stopPropagation()} onSubmit={handleSubmit} style={formModalContent()}>
        <h2 style={formTitle}>
          {isEdit ? 'Edit Task' : 'New Task'}
        </h2>
        {error && <p style={{ color: CORAL, fontSize: 12, marginBottom: 12 }}>{error}</p>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={labelStyle}>What needs to be done? *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>Description</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} style={{ ...inputStyle, resize: 'none' }} />
          </div>
          {!contactId && (
            <div>
              <label style={labelStyle}>Contact</label>
              <select value={selectedContact ?? ''} onChange={e => setSelectedContact(e.target.value ? Number(e.target.value) : null)} style={inputStyle}>
                <option value="">No contact</option>
                {contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>Due Date</label>
              <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Priority</label>
              <select value={priority} onChange={e => setPriority(e.target.value)} style={inputStyle}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button type="button" onClick={onClose} style={{ ...btnSecondary, flex: 1 }}>Cancel</button>
          <button type="submit" disabled={saving} style={{
            ...btnPrimary, flex: 1, opacity: saving ? 0.5 : 1,
          }}>{saving ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Task'}</button>
        </div>
      </form>
    </div>
  );
}
