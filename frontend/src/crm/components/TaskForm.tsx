import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { CrmContact } from '../../core/types';

interface Props {
  contactId?: number;
  dealId?: number;
  onClose: () => void;
  onSaved: () => void;
}

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
        .then(d => setContacts(d.contacts))
        .catch(() => {});
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
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
    setSaving(false);
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="bg-gray-900 rounded-2xl border border-gray-700 p-6 w-full max-w-md"
      >
        <h2 className="text-white font-bold text-lg mb-4">New Task</h2>
        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        <div className="space-y-3">
          <div>
            <label className="text-gray-400 text-xs block mb-1">What needs to be done? *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
          </div>

          <div>
            <label className="text-gray-400 text-xs block mb-1">Description</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 resize-none" />
          </div>

          {!contactId && (
            <div>
              <label className="text-gray-400 text-xs block mb-1">Contact</label>
              <select
                value={selectedContact ?? ''}
                onChange={e => setSelectedContact(e.target.value ? Number(e.target.value) : null)}
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
              >
                <option value="">No contact</option>
                {contacts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-gray-400 text-xs block mb-1">Due Date</label>
              <input type="date" value={dueDate} onChange={e => setDueDate(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
            </div>
            <div>
              <label className="text-gray-400 text-xs block mb-1">Priority</label>
              <select value={priority} onChange={e => setPriority(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>
        </div>

        <div className="flex gap-2 mt-5">
          <button type="button" onClick={onClose} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">Cancel</button>
          <button type="submit" disabled={saving} className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50">
            {saving ? 'Saving...' : 'Create Task'}
          </button>
        </div>
      </form>
    </div>
  );
}
