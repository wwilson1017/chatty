import { useState } from 'react';
import { api } from '../../core/api/client';
import type { CrmContact } from '../../core/types';

interface Props {
  contact?: CrmContact;
  onClose: () => void;
  onSaved: () => void;
}

export function ContactForm({ contact, onClose, onSaved }: Props) {
  const isEdit = !!contact;
  const [name, setName] = useState(contact?.name || '');
  const [email, setEmail] = useState(contact?.email || '');
  const [phone, setPhone] = useState(contact?.phone || '');
  const [company, setCompany] = useState(contact?.company || '');
  const [title, setTitle] = useState(contact?.title || '');
  const [source, setSource] = useState(contact?.source || '');
  const [status, setStatus] = useState(contact?.status || 'active');
  const [tags, setTags] = useState(contact?.tags || '');
  const [notes, setNotes] = useState(contact?.notes || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setError('Name is required'); return; }
    setSaving(true); setError('');
    try {
      if (isEdit) {
        await api(`/api/crm/contacts/${contact.id}`, {
          method: 'PUT',
          body: JSON.stringify({ name, email, phone, company, title, source, status, tags, notes }),
        });
      } else {
        await api('/api/crm/contacts', {
          method: 'POST',
          body: JSON.stringify({ name, email, phone, company, title, source, status, tags, notes }),
        });
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
        className="bg-gray-900 rounded-2xl border border-gray-700 p-6 w-full max-w-md max-h-[90vh] overflow-y-auto"
      >
        <h2 className="text-white font-bold text-lg mb-4">{isEdit ? 'Edit Contact' : 'New Contact'}</h2>

        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        <div className="space-y-3">
          <Input label="Name *" value={name} onChange={setName} />
          <Input label="Email" value={email} onChange={setEmail} type="email" />
          <Input label="Phone" value={phone} onChange={setPhone} type="tel" />
          <Input label="Company" value={company} onChange={setCompany} />
          <Input label="Job Title" value={title} onChange={setTitle} />

          <div>
            <label className="text-gray-400 text-xs block mb-1">Source</label>
            <select
              value={source}
              onChange={e => setSource(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            >
              <option value="">Select...</option>
              <option value="referral">Referral</option>
              <option value="website">Website</option>
              <option value="cold_call">Cold Call</option>
              <option value="social">Social Media</option>
              <option value="event">Event</option>
              <option value="other">Other</option>
            </select>
          </div>

          <div>
            <label className="text-gray-400 text-xs block mb-1">Status</label>
            <select
              value={status}
              onChange={e => setStatus(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="archived">Archived</option>
            </select>
          </div>

          <Input label="Tags (comma-separated)" value={tags} onChange={setTags} />

          <div>
            <label className="text-gray-400 text-xs block mb-1">Notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 resize-none"
            />
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

function Input({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div>
      <label className="text-gray-400 text-xs block mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
      />
    </div>
  );
}
