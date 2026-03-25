import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { CrmDeal, CrmContact } from '../../core/types';

interface Props {
  deal?: CrmDeal;
  contactId?: number;
  onClose: () => void;
  onSaved: () => void;
}

const STAGES = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

export function DealForm({ deal, contactId, onClose, onSaved }: Props) {
  const isEdit = !!deal;
  const [title, setTitle] = useState(deal?.title || '');
  const [stage, setStage] = useState(deal?.stage || 'lead');
  const [value, setValue] = useState(deal?.value?.toString() || '');
  const [probability, setProbability] = useState(deal?.probability?.toString() || '');
  const [expectedClose, setExpectedClose] = useState(deal?.expected_close_date || '');
  const [notes, setNotes] = useState(deal?.notes || '');
  const [selectedContact, setSelectedContact] = useState<number | null>(deal?.contact_id ?? contactId ?? null);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api<{ contacts: CrmContact[] }>('/api/crm/contacts?limit=200')
      .then(d => setContacts(d.contacts))
      .catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true); setError('');
    try {
      const body: Record<string, unknown> = {
        title,
        stage,
        value: parseFloat(value) || 0,
        probability: parseInt(probability) || 0,
        expected_close_date: expectedClose,
        notes,
      };
      if (selectedContact) body.contact_id = selectedContact;

      if (isEdit) {
        await api(`/api/crm/deals/${deal.id}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await api('/api/crm/deals', { method: 'POST', body: JSON.stringify(body) });
      }
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
        <h2 className="text-white font-bold text-lg mb-4">{isEdit ? 'Edit Deal' : 'New Deal'}</h2>
        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        <div className="space-y-3">
          <div>
            <label className="text-gray-400 text-xs block mb-1">Title *</label>
            <input value={title} onChange={e => setTitle(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
          </div>

          <div>
            <label className="text-gray-400 text-xs block mb-1">Contact</label>
            <select
              value={selectedContact ?? ''}
              onChange={e => setSelectedContact(e.target.value ? Number(e.target.value) : null)}
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            >
              <option value="">No contact</option>
              {contacts.map(c => <option key={c.id} value={c.id}>{c.name}{c.company ? ` (${c.company})` : ''}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-gray-400 text-xs block mb-1">Stage</label>
              <select value={stage} onChange={e => setStage(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm capitalize focus:outline-none focus:border-indigo-500">
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="text-gray-400 text-xs block mb-1">Value ($)</label>
              <input type="number" value={value} onChange={e => setValue(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-gray-400 text-xs block mb-1">Probability (%)</label>
              <input type="number" min="0" max="100" value={probability} onChange={e => setProbability(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
            </div>
            <div>
              <label className="text-gray-400 text-xs block mb-1">Expected Close</label>
              <input type="date" value={expectedClose} onChange={e => setExpectedClose(e.target.value)} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
            </div>
          </div>

          <div>
            <label className="text-gray-400 text-xs block mb-1">Notes</label>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 resize-none" />
          </div>
        </div>

        <div className="flex gap-2 mt-5">
          <button type="button" onClick={onClose} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">Cancel</button>
          <button type="submit" disabled={saving} className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50">
            {saving ? 'Saving...' : isEdit ? 'Update' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}
