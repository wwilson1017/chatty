import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmContact } from '../core/types';
import { ContactForm } from './components/ContactForm';
import { DealForm } from './components/DealForm';
import { TaskForm } from './components/TaskForm';
import { ActivityTimeline } from './components/ActivityTimeline';
import { PriorityBadge } from './components/badges';
import { STAGE_COLORS } from './constants';
import { IconArrowLeft } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';
import {
  INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, CORAL, SAGE,
  ACCENT, ACCENT_INK,
  FONT_DISPLAY, FONT_MONO,
  mono, inputStyle,
} from '../shared/styles';
import {
  cardStyle, stageCard,
  btnSecondary, btnDanger, btnPrimary, btnSmall,
} from './styles';

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

  if (!contact) return <p style={{ color: INK_MUTE, padding: 32 }}>Contact not found.</p>;

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      {/* Back link */}
      <button onClick={() => navigate('/crm/contacts')} style={{
        background: 'none', border: 'none', color: INK_DIM,
        fontSize: 13, cursor: 'pointer', marginBottom: 16,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <IconArrowLeft size={14} strokeWidth={1.85} /> Contacts
      </button>

      {/* Header */}
      <div style={{ marginBottom: isMobile ? 20 : 32 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <h1 style={{
            fontFamily: FONT_DISPLAY,
            fontSize: isMobile ? 24 : 32, fontWeight: 400, letterSpacing: '-0.02em',
            color: INK, margin: 0,
          }}>{contact.name}</h1>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <button onClick={() => setShowEdit(true)} style={{
              ...btnSecondary, ...btnSmall,
            }}>Edit</button>
            <button onClick={handleDelete} style={{
              ...btnDanger, ...btnSmall,
            }}>Delete</button>
          </div>
        </div>
        {contact.title && (
          <p style={{ fontSize: 14, color: INK_MUTE, marginTop: 4 }}>
            {contact.title}{contact.company ? ` at ${contact.company}` : ''}
          </p>
        )}
        {!contact.title && contact.company && (
          <p style={{ fontSize: 14, color: INK_MUTE, marginTop: 4 }}>{contact.company}</p>
        )}
        <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? 4 : 16, marginTop: 8, fontSize: 13, color: INK_MUTE }}>
          {contact.email && <span>{contact.email}</span>}
          {contact.phone && <span>{contact.phone}</span>}
        </div>
        {contact.tags && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            {contact.tags.split(',').map(t => t.trim()).filter(Boolean).map(tag => (
              <span key={tag} style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 3,
                background: 'rgba(245,239,227,0.06)', color: INK_MUTE,
                fontFamily: FONT_MONO,
                letterSpacing: '0.1em',
              }}>{tag}</span>
            ))}
          </div>
        )}
      </div>

      {/* Notes */}
      {contact.notes && (
        <div style={{
          ...cardStyle,
          padding: isMobile ? 14 : 16, marginBottom: isMobile ? 20 : 24,
        }}>
          <p style={{ ...mono(10), marginBottom: 6 }}>Notes</p>
          <p style={{ fontSize: 13, color: INK_MUTE, whiteSpace: 'pre-wrap', lineHeight: 1.5, margin: 0 }}>{contact.notes}</p>
        </div>
      )}

      {/* Deals + Tasks */}
      <div style={{ display: isMobile ? 'flex' : 'grid', flexDirection: isMobile ? 'column' : undefined, gridTemplateColumns: isMobile ? undefined : '1fr 1fr', gap: 24 }}>
        {/* Deals */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={mono(10, INK_DIM)}>Deals</span>
            <button onClick={() => setShowAddDeal(true)} style={{
              background: 'none', border: 'none', color: ACCENT,
              fontSize: 12, cursor: 'pointer',
            }}>+ Add</button>
          </div>
          <div style={{ borderTop: `1px solid ${LINE}` }}>
            {!contact.deals?.length ? (
              <p style={{ color: INK_DIM, fontSize: 12, padding: '16px 0' }}>No deals yet.</p>
            ) : (
              contact.deals.map(d => (
                <div key={d.id} style={{
                  ...stageCard(
                    STAGE_COLORS[d.stage]?.bg || 'rgba(20,24,30,0.78)',
                    STAGE_COLORS[d.stage]?.color || 'rgba(230,235,242,0.14)',
                  ),
                  padding: '12px 14px', marginBottom: 6,
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{ fontSize: 14, color: INK, margin: 0 }}>{d.title}</p>
                    <span style={{
                      ...mono(10), textTransform: 'capitalize', marginTop: 2, display: 'inline-block',
                      color: STAGE_COLORS[d.stage]?.color || INK_DIM,
                    }}>{d.stage}</span>
                  </div>
                  <span style={{
                    fontFamily: FONT_DISPLAY,
                    fontSize: 16, color: INK, flexShrink: 0, marginLeft: 12,
                  }}>${d.value.toLocaleString()}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Tasks */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={mono(10, INK_DIM)}>Tasks</span>
            <button onClick={() => setShowAddTask(true)} style={{
              background: 'none', border: 'none', color: ACCENT,
              fontSize: 12, cursor: 'pointer',
            }}>+ Add</button>
          </div>
          <div style={{ borderTop: `1px solid ${LINE}` }}>
            {!contact.tasks?.length ? (
              <p style={{ color: INK_DIM, fontSize: 12, padding: '16px 0' }}>No tasks yet.</p>
            ) : (
              contact.tasks.map(t => (
                <div key={t.id} style={{
                  padding: '10px 0', borderBottom: `1px solid ${LINE}`,
                  display: 'flex', alignItems: 'center', gap: 10,
                  opacity: t.completed ? 0.5 : 1,
                }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                    background: t.completed ? SAGE : isOverdue(t.due_date) ? CORAL : INK_DIM,
                  }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{
                      fontSize: 13, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      color: t.completed ? INK_DIM : INK,
                      textDecoration: t.completed ? 'line-through' : 'none',
                    }}>{t.title}</p>
                    {t.due_date && (
                      <p style={{
                        fontSize: 11, marginTop: 2,
                        color: isOverdue(t.due_date) && !t.completed ? CORAL : INK_DIM,
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
        marginTop: 24, borderTop: `1px solid ${LINE}`, paddingTop: 24,
      }}>
        <span style={{ ...mono(10, INK_DIM), display: 'block', marginBottom: 12 }}>Log Activity</span>
        <div style={{ display: 'flex', gap: 8, marginBottom: logActivity ? 8 : 0, flexWrap: 'wrap' }}>
          {['call', 'email', 'meeting', 'note'].map(type => (
            <button key={type} onClick={() => setLogActivity(type)} style={{
              padding: '5px 12px', borderRadius: 4, fontSize: 12, textTransform: 'capitalize',
              background: logActivity === type ? ACCENT : 'transparent',
              color: logActivity === type ? ACCENT_INK : INK_MUTE,
              border: logActivity === type ? 'none' : `1px solid ${LINE_STRONG}`,
              cursor: 'pointer',
            }}>{type}</button>
          ))}
        </div>
        {logActivity && (
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input placeholder="Add a note..." value={logNote} onChange={e => setLogNote(e.target.value)}
              style={{
                ...inputStyle,
                flex: 1, width: undefined, fontSize: 13,
              }}
            />
            <button onClick={handleLogActivity} disabled={logging} style={{
              ...btnPrimary,
              padding: '8px 16px', fontSize: 13,
              opacity: logging ? 0.5 : 1,
            }}>{logging ? 'Saving...' : 'Log'}</button>
          </div>
        )}
      </div>

      {/* Activity history */}
      <div style={{ marginTop: 24, borderTop: `1px solid ${LINE}`, paddingTop: 24 }}>
        <span style={{ ...mono(10, INK_DIM), display: 'block', marginBottom: 12 }}>Activity History</span>
        <ActivityTimeline activities={contact.activity || []} onUpdate={load} />
      </div>

      {showEdit && <ContactForm contact={contact} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); load(); }} />}
      {showAddDeal && <DealForm contactId={contact.id} onClose={() => setShowAddDeal(false)} onSaved={() => { setShowAddDeal(false); load(); }} />}
      {showAddTask && <TaskForm contactId={contact.id} onClose={() => setShowAddTask(false)} onSaved={() => { setShowAddTask(false); load(); }} />}
    </div>
  );
}

function isOverdue(date: string): boolean {
  if (!date) return false;
  return new Date(date) < new Date(new Date().toISOString().split('T')[0]);
}
