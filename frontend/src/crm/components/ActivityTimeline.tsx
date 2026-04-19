import type { CrmActivity } from '../../core/types';
import { IconPhone, IconMail, IconUsers, IconFile } from '../../shared/icons';

const ACTIVITY_ICONS: Record<string, React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  call: IconPhone,
  email: IconMail,
  meeting: IconUsers,
  note: IconFile,
  follow_up: IconMail,
};

export function ActivityTimeline({ activities }: { activities: CrmActivity[] }) {
  if (activities.length === 0) {
    return <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13 }}>No activity yet.</p>;
  }

  return (
    <div>
      {activities.map(a => {
        const Icon = ACTIVITY_ICONS[a.activity] || IconFile;
        return (
          <div key={a.id} style={{
            padding: '11px 0', display: 'flex', alignItems: 'center', gap: 12,
            borderBottom: '1px solid rgba(230,235,242,0.07)',
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
  );
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso + 'Z');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
      ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  } catch { return iso; }
}
