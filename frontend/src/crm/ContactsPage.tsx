import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { SmartImportModal } from './components/SmartImportModal';
import { StatusBadge } from './components/badges';
import { IconPlus, IconSearch } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';
import { INK, INK_MUTE, INK_DIM, LINE, BG_RAISED, FONT_SANS, mono } from '../shared/styles';
import {
  pageHeading, cardStyle, filterTab,
  tableHeader, tableRow, btnPrimary, btnSecondary, btnSmall,
} from './styles';

const STATUS_TABS = ['all', 'active', 'inactive', 'archived'] as const;

const COLS = '2fr 1.5fr 2fr 1.2fr 80px';

export function ContactsPage() {
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const navigate = useNavigate();
  const isMobile = useIsMobile();

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
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={pageHeading(isMobile)}>Contacts</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setShowImport(true)} style={{
            ...btnSecondary, ...btnSmall,
          }}>{isMobile ? 'Import' : 'Import Contacts'}</button>
          <button onClick={() => setShowCreate(true)} style={{
            ...btnPrimary, ...btnSmall,
          }}>
            <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Contact'}
          </button>
        </div>
      </div>

      {/* Search + filter */}
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 12, marginBottom: isMobile ? 16 : 24 }}>
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 8,
          background: BG_RAISED, border: `1px solid ${LINE}`,
          borderRadius: 4, padding: '0 12px',
        }}>
          <IconSearch size={14} strokeWidth={1.85} style={{ color: INK_DIM }} />
          <input type="text" placeholder="Search contacts..." value={search} onChange={e => setSearch(e.target.value)}
            style={{
              flex: 1, background: 'transparent', border: 'none', color: INK,
              padding: '9px 0', fontSize: 13, outline: 'none',
              fontFamily: FONT_SANS,
            }}
          />
        </div>
        <div style={{
          display: 'flex', gap: 0, flexShrink: 0,
        }}>
          {STATUS_TABS.map(tab => {
            const isActive = status === tab;
            return (
              <button key={tab} onClick={() => setStatus(tab)} style={filterTab(isMobile, isActive)}>{tab}</button>
            );
          })}
        </div>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
        </div>
      ) : contacts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            {search ? 'No contacts match your search.' : 'No contacts yet. Add your first one!'}
          </p>
        </div>
      ) : (
        <>
          <p style={{ ...mono(12), marginBottom: 12 }}>{total} contact{total !== 1 ? 's' : ''}</p>
          {isMobile ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {contacts.map(c => (
                <div key={c.id} onClick={() => navigate(`/crm/contacts/${c.id}`)}
                  style={{
                    padding: '12px 14px', cursor: 'pointer',
                    ...cardStyle,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 16, color: INK }}>{c.name}</span>
                    <StatusBadge status={c.status} />
                  </div>
                  {c.company && <div style={{ fontSize: 14, color: INK_MUTE, marginBottom: 2 }}>{c.company}</div>}
                  {c.email && <div style={{ fontSize: 14, color: INK_DIM }}>{c.email}</div>}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ borderTop: `1px solid ${LINE}` }}>
              <div style={tableHeader(COLS)}>
                <span>Name</span><span>Company</span><span>Email</span><span>Phone</span><span>Status</span>
              </div>
              {contacts.map(c => (
                <div key={c.id} onClick={() => navigate(`/crm/contacts/${c.id}`)}
                  style={tableRow(COLS)}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                >
                  <div>
                    <p style={{ fontSize: 16, color: INK, margin: 0 }}>{c.name}</p>
                    {c.title && <p style={{ fontSize: 13, color: INK_DIM, marginTop: 2 }}>{c.title}</p>}
                  </div>
                  <span style={{ fontSize: 15, color: INK_MUTE, alignSelf: 'center' }}>{c.company || '\u2014'}</span>
                  <span style={{ fontSize: 15, color: INK_MUTE, alignSelf: 'center' }}>{c.email || '\u2014'}</span>
                  <span style={{ fontSize: 15, color: INK_MUTE, alignSelf: 'center' }}>{c.phone || '\u2014'}</span>
                  <span style={{ alignSelf: 'center' }}><StatusBadge status={c.status} /></span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {showCreate && <ContactForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {showImport && <SmartImportModal onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); load(); }} />}
    </div>
  );
}
