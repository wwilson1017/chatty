import { useState } from 'react';
import type { AgentAlert } from '../../core/types';

interface Props {
  alerts: AgentAlert[];
  onDismiss: (alertId: string) => void;
  onDiscuss: (alertId: string) => void;
}

function timeAgo(iso: string): string {
  const d = new Date(iso + 'Z');
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'heartbeat_failure': return 'Heartbeat failing';
    case 'heartbeat': return 'Heartbeat';
    case 'cron': return 'Scheduled action';
    case 'post_message': return 'Agent message';
    case 'reminder': return 'Reminder';
    default: return 'Alert';
  }
}

export default function AlertBanner({ alerts, onDismiss, onDiscuss }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (alerts.length === 0) return null;

  const latest = alerts[0];

  return (
    <div style={{
      margin: '8px 16px',
      border: '1px solid rgba(212,168,90,0.25)',
      borderRadius: 8,
      background: 'rgba(212,168,90,0.06)',
      overflow: 'hidden',
    }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '7px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: 'pointer',
        }}
      >
        <svg
          width="10" height="10" viewBox="0 0 10 10" fill="none"
          stroke="#D4A85A" strokeWidth="1.5" strokeLinecap="round"
          style={{ flexShrink: 0, transition: 'transform 0.2s', transform: expanded ? 'rotate(90deg)' : 'none' }}
        >
          <path d="M3 1l4 4-4 4" />
        </svg>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          color: '#D4A85A',
          fontWeight: 600,
          flexShrink: 0,
        }}>
          {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
        </span>
        {!expanded && (
          <span style={{
            fontFamily: "'Inter', sans-serif",
            fontSize: 12,
            color: 'rgba(212,168,90,0.5)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
            minWidth: 0,
          }}>
            {sourceLabel(latest.source)}: {latest.title} — {timeAgo(latest.created_at)}
          </span>
        )}
      </div>

      {expanded && (
        <div style={{ padding: '0 12px 8px' }}>
          {alerts.map(alert => (
            <div key={alert.id} style={{
              padding: '6px 0',
              borderTop: '1px solid rgba(212,168,90,0.12)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 10, color: 'rgba(212,168,90,0.6)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  marginBottom: 2,
                }}>
                  {sourceLabel(alert.source)}
                </div>
                <div style={{
                  fontSize: 12, color: '#EDF0F4',
                  fontWeight: 500, lineHeight: 1.3,
                }}>
                  {alert.title}
                </div>
                <div style={{
                  fontSize: 11, color: 'rgba(237,240,244,0.5)',
                  marginTop: 2, lineHeight: 1.3,
                }}>
                  {alert.message.slice(0, 120)}{alert.message.length > 120 ? '...' : ''}
                </div>
                <div style={{
                  fontSize: 10, color: 'rgba(237,240,244,0.3)',
                  marginTop: 2,
                  fontFamily: "'JetBrains Mono', monospace",
                }}>
                  {timeAgo(alert.created_at)}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 4, flexShrink: 0, paddingTop: 2 }}>
                <button
                  onClick={(e) => { e.stopPropagation(); onDiscuss(alert.id); }}
                  style={{
                    fontSize: 10, padding: '3px 8px',
                    borderRadius: 4, border: '1px solid rgba(212,168,90,0.3)',
                    background: 'rgba(212,168,90,0.1)', color: '#D4A85A',
                    cursor: 'pointer',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                  }}
                >
                  Discuss
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onDismiss(alert.id); }}
                  style={{
                    fontSize: 10, padding: '3px 8px',
                    borderRadius: 4, border: '1px solid rgba(237,240,244,0.1)',
                    background: 'transparent', color: 'rgba(237,240,244,0.4)',
                    cursor: 'pointer',
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
