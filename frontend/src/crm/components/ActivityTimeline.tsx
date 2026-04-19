import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../core/api/client';
import { useIsMobile } from '../../shared/useIsMobile';
import type { CrmActivity } from '../../core/types';
import { IconPhone, IconMail, IconUsers, IconFile } from '../../shared/icons';

const ACTIVITY_ICONS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  call: IconPhone,
  email: IconMail,
  meeting: IconUsers,
  note: IconFile,
  follow_up: IconMail,
};

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

interface Props {
  activities: CrmActivity[];
  onUpdate?: () => void;
}

export function ActivityTimeline({ activities, onUpdate }: Props) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [selected, setSelected] = useState<CrmActivity | null>(null);
  const [editActivity, setEditActivity] = useState('');
  const [editNote, setEditNote] = useState('');
  const [saving, setSaving] = useState(false);

  if (activities.length === 0) {
    return <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13 }}>No activity yet.</p>;
  }

  function handleClick(a: CrmActivity) {
    setSelected(a);
    setEditActivity(a.activity);
    setEditNote(a.note || '');
  }

  function handleNavigateToContact() {
    if (selected?.contact_id) {
      setSelected(null);
      navigate(`/crm/contacts/${selected.contact_id}`);
    }
  }

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    try {
      await api(`/api/crm/activity/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({ activity: editActivity, note: editNote }),
      });
      setSelected(null);
      onUpdate?.();
    } catch { /* ignore */ }
    setSaving(false);
  }

  async function handleDelete() {
    if (!selected || !confirm('Delete this activity entry?')) return;
    try {
      await api(`/api/crm/activity/${selected.id}`, { method: 'DELETE' });
      setSelected(null);
      onUpdate?.();
    } catch { /* ignore */ }
  }

  return (
    <>
      <div>
        {activities.map(a => {
          const Icon = ACTIVITY_ICONS[a.activity] || IconFile;
          return (
            <div key={a.id} onClick={() => handleClick(a)} style={{
              padding: '11px 0', display: 'flex', alignItems: 'center', gap: 12,
              borderBottom: '1px solid rgba(230,235,242,0.07)',
              cursor: 'pointer',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 4,
                background: 'rgba(245,239,227,0.06)',
                border: '1px solid rgba(230,235,242,0.07)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'rgba(237,240,244,0.62)', flexShrink: 0,
              }}>
                <Icon size={13} strokeWidth={1.75} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13 }}>
                  <span style={{ color: '#EDF0F4', textTransform: 'capitalize' }}>{a.activity.replace('_', ' ')}</span>
                  {a.contact_name && <span style={{ color: 'rgba(237,240,244,0.62)' }}> · {a.contact_name}</span>}
                </div>
                {a.note && <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.note}</p>}
              </div>
              <div style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 10, color: 'rgba(237,240,244,0.38)', flexShrink: 0,
              }}>{formatDate(a.created_at)}</div>
            </div>
          );
        })}
      </div>

      {/* Activity detail/edit modal */}
      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            zIndex: 50, display: 'flex',
            alignItems: isMobile ? 'flex-end' : 'center',
            justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#11141A',
              borderRadius: isMobile ? '12px 12px 0 0' : 8,
              border: '1px solid rgba(230,235,242,0.14)',
              borderBottom: isMobile ? 'none' : undefined,
              padding: isMobile ? '20px 20px 28px' : 28,
              width: '100%', maxWidth: 440, margin: isMobile ? 0 : '0 16px',
              boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
            }}
          >
            {isMobile && (
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(230,235,242,0.14)' }} />
              </div>
            )}

            <h3 style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 18, fontWeight: 400, color: '#EDF0F4', margin: '0 0 16px',
            }}>Edit Activity</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Activity</label>
                <textarea
                  value={editActivity}
                  onChange={e => setEditActivity(e.target.value)}
                  rows={2}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
                    color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13,
                    outline: 'none', resize: 'none',
                    fontFamily: "'Inter Tight', system-ui, sans-serif",
                  }}
                />
              </div>
              <div>
                <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Note</label>
                <textarea
                  value={editNote}
                  onChange={e => setEditNote(e.target.value)}
                  rows={3}
                  placeholder="Add a note..."
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
                    color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13,
                    outline: 'none', resize: 'none',
                    fontFamily: "'Inter Tight', system-ui, sans-serif",
                  }}
                />
              </div>

              {/* Meta info */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {selected.contact_name && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ ...mono(9) }}>Contact</span>
                    <span
                      onClick={handleNavigateToContact}
                      style={{ fontSize: 13, color: 'var(--color-ch-accent, #C8D1D9)', cursor: 'pointer' }}
                    >{selected.contact_name}</span>
                  </div>
                )}
                {selected.deal_title && (
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ ...mono(9) }}>Deal</span>
                    <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selected.deal_title}</span>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9) }}>Logged</span>
                  <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)' }}>{formatDate(selected.created_at)}</span>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
              <button onClick={() => setSelected(null)} style={{
                padding: '10px 16px', borderRadius: 6,
                border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
                color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleDelete} style={{
                padding: '10px 16px', borderRadius: 6,
                background: 'rgba(217,119,87,0.1)', color: '#D97757',
                border: '1px solid rgba(217,119,87,0.2)',
                fontSize: 13, cursor: 'pointer',
              }}>Delete</button>
              <button onClick={handleSave} disabled={saving} style={{
                flex: 1, padding: '10px 16px', borderRadius: 6,
                background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
                border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
                opacity: saving ? 0.5 : 1,
              }}>{saving ? 'Saving...' : 'Save'}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso + 'Z');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch { return iso; }
}
