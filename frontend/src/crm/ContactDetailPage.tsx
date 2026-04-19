import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { DealForm } from './components/DealForm';
import { TaskForm } from './components/TaskForm';
import { ActivityTimeline } from './components/ActivityTimeline';
import { IconArrowLeft } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';

const STAGE_COLORS: Record<string, { color: string; bg: string }> = {
  lead: { color: '#7B9EC4', bg: 'rgba(123,158,196,0.10)' },
  qualified: { color: '#C8D1D9', bg: 'rgba(200,209,217,0.10)' },
  proposal: { color: '#D4A85A', bg: 'rgba(212,168,90,0.10)' },
  negotiation: { color: '#D4855A', bg: 'rgba(212,133,90,0.10)' },
  won: { color: '#8EA589', bg: 'rgba(142,165,137,0.10)' },
  lost: { color: '#D97757', bg: 'rgba(217,119,87,0.10)' },
};

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [contact, setContact] = useState<CrmContact | null>(null);
  const [loading, setLoading] = useState(true);
  const [showEdit, setShowEdit] = useState(false);
  const [showAddDeal, setShowAddDeal] = useState(false);
  const [showAddTask, setShowAddTask] = useState(false);
  const [logActivity, setLogActivity] = useState('');
  const [logNote, setLogNote] = useState('');
  const [logging, setLogging] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<CrmContact>(`/api/crm/contacts/${id}`);
      setContact(data);
    } catch { setContact(null); }
    setLoading(false);
  }, [id]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  async function handleLogActivity() {
    if (!logActivity) return;
    setLogging(true);
    await api('/api/crm/activity', {
      method: 'POST',
      body: JSON.stringify({ activity: logActivity, note: logNote, contact_id: Number(id) }),
    });
    setLogActivity('');
    setLogNote('');
    setLogging(false);
    load();
  }

  async function handleDelete() {
    if (!confirm('Delete this contact? This cannot be undone.')) return;
    await api(`/api/crm/contacts/${id}`, { method: 'DELETE' });
    navigate('/crm/contacts');
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
        <div className="w-8 h-8 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!contact) return <p style={{ color: 'rgba(237,240,244,0.62)', padding: 32 }}>Contact not found.</p>;

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      {/* Back link */}
      <button onClick={() => navigate('/crm/contacts')} style={{
        background: 'none', border: 'none', color: 'rgba(237,240,244,0.38)',
        fontSize: 13, cursor: 'pointer', marginBottom: 16,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <IconArrowLeft size={14} strokeWidth={1.85} /> Contacts
      </button>

      {/* Header */}
      <div style={{ marginBottom: isMobile ? 20 : 32 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <h1 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: isMobile ? 24 : 32, fontWeight: 400, letterSpacing: '-0.02em',
            color: '#EDF0F4', margin: 0,
          }}>{contact.name}</h1>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <button onClick={() => setShowEdit(true)} style={{
              background: 'transparent', color: 'rgba(237,240,244,0.62)',
              border: '1px solid rgba(230,235,242,0.14)',
              padding: '6px 12px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
            }}>Edit</button>
            <button onClick={handleDelete} style={{
              background: 'transparent', color: '#D97757',
              border: '1px solid rgba(217,119,87,0.2)',
              padding: '6px 12px', borderRadius: 4, fontSize: 12, cursor: 'pointer',
            }}>Delete</button>
          </div>
        </div>
        {contact.title && (
          <p style={{ fontSize: 14, color: 'rgba(237,240,244,0.62)', marginTop: 4 }}>
            {contact.title}{contact.company ? ` at ${contact.company}` : ''}
          </p>
        )}
        {!contact.title && contact.company && (
          <p style={{ fontSize: 14, color: 'rgba(237,240,244,0.62)', marginTop: 4 }}>{contact.company}</p>
        )}
        <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 4 : 16, marginTop: 8, fontSize: 13, color: 'rgba(237,240,244,0.62)' }}>
          {contact.email && <span>{contact.email}</span>}
          {contact.phone && <span>{contact.phone}</span>}
        </div>
        {contact.tags && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            {contact.tags.split(',').map(t => t.trim()).filter(Boolean).map(tag => (
              <span key={tag} style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 3,
                background: 'rgba(245,239,227,0.06)', color: 'rgba(237,240,244,0.62)',
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                letterSpacing: '0.1em',
              }}>{tag}</span>
            ))}
          </div>
        )}
      </div>

      {/* Notes */}
      {contact.notes && (
        <div style={{
          background: 'rgba(20,24,30,0.78)', border: '1px solid rgba(230,235,242,0.07)',
          borderRadius: 6, padding: isMobile ? 14 : 16, marginBottom: isMobile ? 20 : 24,
        }}>
          <p style={{ ...mono(9), marginBottom: 6 }}>Notes</p>
          <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', whiteSpace: 'pre-wrap', lineHeight: 1.5, margin: 0 }}>{contact.notes}</p>
        </div>
      )}

      {/* Deals + Tasks */}
      <div style={{ display: isMobile ? 'flex' : 'grid', flexDirection: isMobile ? 'column' : undefined, gridTemplateColumns: isMobile ? undefined : '1fr 1fr', gap: 24 }}>
        {/* Deals */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={mono(10, 'rgba(237,240,244,0.38)')}>Deals</span>
            <button onClick={() => setShowAddDeal(true)} style={{
              background: 'none', border: 'none', color: 'var(--color-ch-accent, #C8D1D9)',
              fontSize: 12, cursor: 'pointer',
            }}>+ Add</button>
          </div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {!contact.deals?.length ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, padding: '16px 0' }}>No deals yet.</p>
            ) : (
              contact.deals.map(d => (
                <div key={d.id} style={{
                  padding: '12px 14px', marginBottom: 6,
                  borderRadius: 6,
                  background: STAGE_COLORS[d.stage]?.bg || 'rgba(20,24,30,0.78)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  borderLeft: `3px solid ${STAGE_COLORS[d.stage]?.color || 'rgba(230,235,242,0.14)'}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>{d.title}</p>
                    <span style={{
                      ...mono(9), textTransform: 'capitalize', marginTop: 2, display: 'inline-block',
                      color: STAGE_COLORS[d.stage]?.color || 'rgba(237,240,244,0.38)',
                    }}>{d.stage}</span>
                  </div>
                  <span style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 16, color: '#EDF0F4', flexShrink: 0, marginLeft: 12,
                  }}>${d.value.toLocaleString()}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Tasks */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={mono(10, 'rgba(237,240,244,0.38)')}>Tasks</span>
            <button onClick={() => setShowAddTask(true)} style={{
              background: 'none', border: 'none', color: 'var(--color-ch-accent, #C8D1D9)',
              fontSize: 12, cursor: 'pointer',
            }}>+ Add</button>
          </div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {!contact.tasks?.length ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, padding: '16px 0' }}>No tasks yet.</p>
            ) : (
              contact.tasks.map(t => (
                <div key={t.id} style={{
                  padding: '10px 0', borderBottom: '1px solid rgba(230,235,242,0.07)',
                  display: 'flex', alignItems: 'center', gap: 10,
                  opacity: t.completed ? 0.5 : 1,
                }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                    background: t.completed ? '#8EA589' : isOverdue(t.due_date) ? '#D97757' : 'rgba(237,240,244,0.38)',
                  }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{
                      fontSize: 13, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      color: t.completed ? 'rgba(237,240,244,0.38)' : '#EDF0F4',
                      textDecoration: t.completed ? 'line-through' : 'none',
                    }}>{t.title}</p>
                    {t.due_date && (
                      <p style={{
                        fontSize: 11, marginTop: 2,
                        color: isOverdue(t.due_date) && !t.completed ? '#D97757' : 'rgba(237,240,244,0.38)',
                      }}>{t.due_date}</p>
                    )}
                  </div>
                  <PriorityBadge priority={t.priority} />
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Log activity */}
      <div style={{
        marginTop: 24, borderTop: '1px solid rgba(230,235,242,0.07)', paddingTop: 24,
      }}>
        <span style={{ ...mono(10, 'rgba(237,240,244,0.38)'), display: 'block', marginBottom: 12 }}>Log Activity</span>
        <div style={{ display: 'flex', gap: 8, marginBottom: logActivity ? 8 : 0, flexWrap: 'wrap' }}>
          {['call', 'email', 'meeting', 'note'].map(type => (
            <button key={type} onClick={() => setLogActivity(type)} style={{
              padding: '5px 12px', borderRadius: 4, fontSize: 12, textTransform: 'capitalize',
              background: logActivity === type ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
              color: logActivity === type ? '#0E1013' : 'rgba(237,240,244,0.62)',
              border: logActivity === type ? 'none' : '1px solid rgba(230,235,242,0.14)',
              cursor: 'pointer',
            }}>{type}</button>
          ))}
        </div>
        {logActivity && (
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input placeholder="Add a note..." value={logNote} onChange={e => setLogNote(e.target.value)}
              style={{
                flex: 1, background: 'rgba(34,40,48,0.55)',
                border: '1px solid rgba(230,235,242,0.14)',
                color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13, outline: 'none',
              }}
            />
            <button onClick={handleLogActivity} disabled={logging} style={{
              background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
              border: 'none', padding: '8px 16px', borderRadius: 4,
              fontSize: 13, fontWeight: 500, cursor: 'pointer',
              opacity: logging ? 0.5 : 1,
            }}>{logging ? 'Saving...' : 'Log'}</button>
          </div>
        )}
      </div>

      {/* Activity history */}
      <div style={{ marginTop: 24, borderTop: '1px solid rgba(230,235,242,0.07)', paddingTop: 24 }}>
        <span style={{ ...mono(10, 'rgba(237,240,244,0.38)'), display: 'block', marginBottom: 12 }}>Activity History</span>
        <ActivityTimeline activities={contact.activity || []} onUpdate={load} />
      </div>

      {showEdit && <ContactForm contact={contact} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); load(); }} />}
      {showAddDeal && <DealForm contactId={contact.id} onClose={() => setShowAddDeal(false)} onSaved={() => { setShowAddDeal(false); load(); }} />}
      {showAddTask && <TaskForm contactId={contact.id} onClose={() => setShowAddTask(false)} onSaved={() => { setShowAddTask(false); load(); }} />}
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const colors: Record<string, string> = {
    high: '#D97757', medium: '#D4A85A', low: 'rgba(237,240,244,0.38)',
  };
  return <span style={{ fontSize: 11, color: colors[priority] || 'rgba(237,240,244,0.38)' }}>{priority}</span>;
}

function isOverdue(date: string): boolean {
  if (!date) return false;
  return new Date(date) < new Date(new Date().toISOString().split('T')[0]);
}
