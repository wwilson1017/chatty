import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../core/api/client';
import { useIsMobile } from '../../shared/useIsMobile';
import type { CrmActivity } from '../../core/types';
import { IconPhone, IconMail, IconUsers, IconFile } from '../../shared/icons';
import { mono, INK, INK_MUTE, INK_SOFT, INK_DIM, LINE, LINE_STRONG, BG_RAISED, ACCENT, ACCENT_INK, FONT_DISPLAY, FONT_SANS } from '../../shared/styles';
import { modalOverlay, modalContent, mobileDragHandle, btnDanger } from '../styles';

const ACTIVITY_ICONS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  call: IconPhone,
  email: IconMail,
  meeting: IconUsers,
  note: IconFile,
  follow_up: IconMail,
};

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
    return <p style={{ color: INK_DIM, fontSize: 13 }}>No activity yet.</p>;
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
              borderBottom: `1px solid ${LINE}`,
              cursor: 'pointer',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 4,
                background: 'rgba(245,239,227,0.06)',
                border: `1px solid ${LINE}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: INK_MUTE, flexShrink: 0,
              }}>
                <Icon size={13} strokeWidth={1.75} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15 }}>
                  <span style={{ color: INK, textTransform: 'capitalize' }}>{a.activity.replace('_', ' ')}</span>
                  {a.contact_name && <span style={{ color: INK_MUTE }}> · {a.contact_name}</span>}
                </div>
                {a.note && <p style={{ color: INK_SOFT, fontSize: 14, marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.note}</p>}
              </div>
              <div style={{
                ...mono(11),
                flexShrink: 0,
              }}>{formatDate(a.created_at)}</div>
            </div>
          );
        })}
      </div>

      {/* Activity detail/edit modal */}
      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={modalOverlay(isMobile)}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={modalContent(isMobile, 440)}
          >
            {isMobile && (
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={mobileDragHandle} />
              </div>
            )}

            <h3 style={{
              fontFamily: FONT_DISPLAY,
              fontSize: 18, fontWeight: 400, color: INK, margin: '0 0 16px',
            }}>Edit Activity</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <label style={{ ...mono(10), display: 'block', marginBottom: 6 }}>Activity</label>
                <textarea
                  value={editActivity}
                  onChange={e => setEditActivity(e.target.value)}
                  rows={2}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
                    color: INK, borderRadius: 4, padding: '8px 12px', fontSize: 13,
                    outline: 'none', resize: 'none',
                    fontFamily: FONT_SANS,
                  }}
                />
              </div>
              <div>
                <label style={{ ...mono(10), display: 'block', marginBottom: 6 }}>Note</label>
                <textarea
                  value={editNote}
                  onChange={e => setEditNote(e.target.value)}
                  rows={3}
                  placeholder="Add a note..."
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
                    color: INK, borderRadius: 4, padding: '8px 12px', fontSize: 13,
                    outline: 'none', resize: 'none',
                    fontFamily: FONT_SANS,
                  }}
                />
              </div>

              {/* Meta info */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {selected.contact_name && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ ...mono(10) }}>Contact</span>
                    <span
                      onClick={handleNavigateToContact}
                      style={{ fontSize: 13, color: ACCENT, cursor: 'pointer' }}
                    >{selected.contact_name}</span>
                  </div>
                )}
                {selected.deal_title && (
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ ...mono(10) }}>Deal</span>
                    <span style={{ fontSize: 13, color: INK }}>{selected.deal_title}</span>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(10) }}>Logged</span>
                  <span style={{ fontSize: 12, color: INK_MUTE }}>{formatDate(selected.created_at)}</span>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
              <button onClick={() => setSelected(null)} style={{
                padding: '10px 16px', borderRadius: 6,
                border: `1px solid ${LINE_STRONG}`, background: 'transparent',
                color: INK_MUTE, fontSize: 13, cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleDelete} style={{
                ...btnDanger,
                padding: '10px 16px', borderRadius: 6, fontSize: 13,
              }}>Delete</button>
              <button onClick={handleSave} disabled={saving} style={{
                flex: 1, padding: '10px 16px', borderRadius: 6,
                background: ACCENT, color: ACCENT_INK,
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
