import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { CrmContact } from '../../core/types';

interface Props {
  contactId?: number;
  dealId?: number;
  onClose: () => void;
  onSaved: () => void;
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
  color: 'rgba(237,240,244,0.38)', marginBottom: 6,
};

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
  color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13, outline: 'none',
  fontFamily: "'Inter Tight', system-ui, sans-serif",
};

export function TaskForm({ contactId, dealId, onClose, onSaved }: Props) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [priority, setPriority] = useState('medium');
  const [selectedContact, setSelectedContact] = useState<number | null>(contactId ?? null);
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
      await api('/api/crm/tasks', { method: 'POST', body: JSON.stringify(body) });
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Failed to save'); }
    setSaving(false);
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }} onClick={onClose}>
      <form onClick={e => e.stopPropagation()} onSubmit={handleSubmit} style={{
        background: '#11141A', borderRadius: 6, border: '1px solid rgba(230,235,242,0.14)',
        padding: 24, width: '100%', maxWidth: 420, boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
      }}>
        <h2 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 400, letterSpacing: '-0.02em', color: '#EDF0F4', marginBottom: 20 }}>New Task</h2>
        {error && <p style={{ color: '#D97757', fontSize: 12, marginBottom: 12 }}>{error}</p>}

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
          <button type="button" onClick={onClose} style={{
            flex: 1, padding: '9px 16px', borderRadius: 4,
            border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
            color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
          }}>Cancel</button>
          <button type="submit" disabled={saving} style={{
            flex: 1, padding: '9px 16px', borderRadius: 4,
            background: '#D4A85A', color: '#0E1013',
            border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
            opacity: saving ? 0.5 : 1,
          }}>{saving ? 'Saving...' : 'Create Task'}</button>
        </div>
      </form>
    </div>
  );
}
