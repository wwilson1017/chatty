import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { CsvImportModal } from './components/CsvImportModal';
import { IconPlus, IconSearch } from '../shared/icons';

const STATUS_TABS = ['all', 'active', 'inactive', 'archived'] as const;

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function ContactsPage() {
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (search) params.set('q', search);
    if (status !== 'all') params.set('status', status);
    params.set('limit', '100');
    const data = await api<{ contacts: CrmContact[]; total: number }>(`/api/crm/contacts?${params}`);
    setContacts(data.contacts);
    setTotal(data.total);
    setLoading(false);
  }, [search, status]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  return (
    <div style={{ padding: '32px 44px', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 32, fontWeight: 400, letterSpacing: '-0.02em',
          color: '#EDF0F4', margin: 0,
        }}>Contacts</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setShowImport(true)} style={{
            background: 'transparent', color: 'rgba(237,240,244,0.62)',
            border: '1px solid rgba(230,235,242,0.14)',
            padding: '7px 14px', borderRadius: 4, fontSize: 13, cursor: 'pointer',
          }}>Import CSV</button>
          <button onClick={() => setShowCreate(true)} style={{
            background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', padding: '7px 14px', borderRadius: 4,
            fontSize: 13, fontWeight: 500, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <IconPlus size={13} strokeWidth={2.25} /> Add Contact
          </button>
        </div>
      </div>

      {/* Search + filter */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 8,
          background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.07)',
          borderRadius: 4, padding: '0 12px',
        }}>
          <IconSearch size={14} strokeWidth={1.85} style={{ color: 'rgba(237,240,244,0.38)' }} />
          <input type="text" placeholder="Search contacts..." value={search} onChange={e => setSearch(e.target.value)}
            style={{
              flex: 1, background: 'transparent', border: 'none', color: '#EDF0F4',
              padding: '9px 0', fontSize: 13, outline: 'none',
              fontFamily: "'Inter Tight', system-ui, sans-serif",
            }}
          />
        </div>
        <div style={{
          display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
          borderRadius: 4, overflow: 'hidden',
        }}>
          {STATUS_TABS.map(tab => (
            <button key={tab} onClick={() => setStatus(tab)} style={{
              padding: '8px 14px', fontSize: 11, textTransform: 'capitalize',
              color: status === tab ? '#0E1013' : 'rgba(237,240,244,0.62)',
              background: status === tab ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
              border: 'none', cursor: 'pointer',
              fontFamily: "'Inter Tight', system-ui, sans-serif",
            }}>{tab}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : contacts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 14 }}>
            {search ? 'No contacts match your search.' : 'No contacts yet. Add your first one!'}
          </p>
        </div>
      ) : (
        <>
          <p style={{ ...mono(9), marginBottom: 12 }}>{total} contact{total !== 1 ? 's' : ''}</p>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {/* Header row */}
            <div style={{
              display: 'grid', gridTemplateColumns: '2fr 1.5fr 2fr 1.2fr 80px',
              gap: 16, padding: '10px 16px',
              borderBottom: '1px solid rgba(230,235,242,0.07)',
              ...mono(9),
            }}>
              <span>Name</span><span>Company</span><span>Email</span><span>Phone</span><span>Status</span>
            </div>
            {contacts.map(c => (
              <div key={c.id} onClick={() => navigate(`/crm/contacts/${c.id}`)}
                style={{
                  display: 'grid', gridTemplateColumns: '2fr 1.5fr 2fr 1.2fr 80px',
                  gap: 16, padding: '12px 16px', cursor: 'pointer',
                  borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
              >
                <div>
                  <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>{c.name}</p>
                  {c.title && <p style={{ fontSize: 11, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>{c.title}</p>}
                </div>
                <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', alignSelf: 'center' }}>{c.company || '—'}</span>
                <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', alignSelf: 'center' }}>{c.email || '—'}</span>
                <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', alignSelf: 'center' }}>{c.phone || '—'}</span>
                <span style={{ alignSelf: 'center' }}><StatusBadge status={c.status} /></span>
              </div>
            ))}
          </div>
        </>
      )}

      {showCreate && <ContactForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {showImport && <CsvImportModal onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); load(); }} />}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, { bg: string; color: string }> = {
    active: { bg: 'rgba(142,165,137,0.12)', color: '#8EA589' },
    inactive: { bg: 'rgba(230,235,242,0.06)', color: 'rgba(237,240,244,0.38)' },
    archived: { bg: 'rgba(217,119,87,0.08)', color: '#D97757' },
  };
  const c = colors[status] || colors.inactive;
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 3,
      background: c.bg, color: c.color, textTransform: 'capitalize',
      fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      letterSpacing: '0.1em',
    }}>{status}</span>
  );
}
