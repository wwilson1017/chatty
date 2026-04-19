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
      .then(d => setContacts(d.contacts)).catch(() => {});
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }
    setSaving(true); setError('');
    try {
      const body: Record<string, unknown> = {
        title, stage, value: parseFloat(value) || 0,
        probability: parseInt(probability) || 0,
        expected_close_date: expectedClose, notes,
      };
      if (selectedContact) body.contact_id = selectedContact;
      if (isEdit) {
        await api(`/api/crm/deals/${deal.id}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await api('/api/crm/deals', { method: 'POST', body: JSON.stringify(body) });
      }
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
        <h2 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 400, letterSpacing: '-0.02em', color: '#EDF0F4', marginBottom: 20 }}>
          {isEdit ? 'Edit Deal' : 'New Deal'}
        </h2>
        {error && <p style={{ color: '#D97757', fontSize: 12, marginBottom: 12 }}>{error}</p>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div><label style={labelStyle}>Title *</label><input value={title} onChange={e => setTitle(e.target.value)} style={inputStyle} /></div>
          <div>
            <label style={labelStyle}>Contact</label>
            <select value={selectedContact ?? ''} onChange={e => setSelectedContact(e.target.value ? Number(e.target.value) : null)} style={inputStyle}>
              <option value="">No contact</option>
              {contacts.map(c => <option key={c.id} value={c.id}>{c.name}{c.company ? ` (${c.company})` : ''}</option>)}
            </select>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={labelStyle}>Stage</label>
              <select value={stage} onChange={e => setStage(e.target.value)} style={{ ...inputStyle, textTransform: 'capitalize' }}>
                {STAGES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div><label style={labelStyle}>Value ($)</label><input type="number" value={value} onChange={e => setValue(e.target.value)} style={inputStyle} /></div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div><label style={labelStyle}>Probability (%)</label><input type="number" min="0" max="100" value={probability} onChange={e => setProbability(e.target.value)} style={inputStyle} /></div>
            <div><label style={labelStyle}>Expected Close</label><input type="date" value={expectedClose} onChange={e => setExpectedClose(e.target.value)} style={inputStyle} /></div>
          </div>
          <div><label style={labelStyle}>Notes</label><textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} style={{ ...inputStyle, resize: 'none' }} /></div>
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
          }}>{saving ? 'Saving...' : isEdit ? 'Update' : 'Create'}</button>
        </div>
      </form>
    </div>
  );
}
