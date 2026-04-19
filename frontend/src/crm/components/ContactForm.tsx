import { useState } from 'react';
import { api } from '../../core/api/client';
import type { CrmContact } from '../../core/types';

interface Props {
  contact?: CrmContact;
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
          method: 'PUT', body: JSON.stringify({ name, email, phone, company, title, source, status, tags, notes }),
        });
      } else {
        await api('/api/crm/contacts', {
          method: 'POST', body: JSON.stringify({ name, email, phone, company, title, source, status, tags, notes }),
        });
      }
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Failed to save'); }
    setSaving(false);
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }} onClick={onClose}>
      <form onClick={e => e.stopPropagation()} onSubmit={handleSubmit} style={{
        background: '#11141A', borderRadius: 6, border: '1px solid rgba(230,235,242,0.14)',
        padding: 24, width: '100%', maxWidth: 420, maxHeight: '90vh', overflowY: 'auto',
        boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
      }}>
        <h2 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 400, letterSpacing: '-0.02em', color: '#EDF0F4', marginBottom: 20 }}>
          {isEdit ? 'Edit Contact' : 'New Contact'}
        </h2>
        {error && <p style={{ color: '#D97757', fontSize: 12, marginBottom: 12 }}>{error}</p>}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div><label style={labelStyle}>Name *</label><input value={name} onChange={e => setName(e.target.value)} style={inputStyle} /></div>
          <div><label style={labelStyle}>Email</label><input type="email" value={email} onChange={e => setEmail(e.target.value)} style={inputStyle} /></div>
          <div><label style={labelStyle}>Phone</label><input type="tel" value={phone} onChange={e => setPhone(e.target.value)} style={inputStyle} /></div>
          <div><label style={labelStyle}>Company</label><input value={company} onChange={e => setCompany(e.target.value)} style={inputStyle} /></div>
          <div><label style={labelStyle}>Job Title</label><input value={title} onChange={e => setTitle(e.target.value)} style={inputStyle} /></div>
          <div>
            <label style={labelStyle}>Source</label>
            <select value={source} onChange={e => setSource(e.target.value)} style={inputStyle}>
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
            <label style={labelStyle}>Status</label>
            <select value={status} onChange={e => setStatus(e.target.value)} style={inputStyle}>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <div><label style={labelStyle}>Tags (comma-separated)</label><input value={tags} onChange={e => setTags(e.target.value)} style={inputStyle} /></div>
          <div><label style={labelStyle}>Notes</label><textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3} style={{ ...inputStyle, resize: 'none' }} /></div>
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
