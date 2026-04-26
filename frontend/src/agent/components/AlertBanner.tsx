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

export default function AlertBanner({ alerts, onDismiss, onDiscuss }: Props) {
  const [expanded, setExpanded] = useState(true);

  if (alerts.length === 0) return null;

  return (
    <div style={{
      margin: '8px 16px',
      border: '1px solid rgba(212,168,90,0.25)',
      borderRadius: 8,
      background: 'rgba(212,168,90,0.06)',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          width: '100%',
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'none',
          border: 'none',
          color: '#D4A85A',
          cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        <span>{alerts.length} unresolved alert{alerts.length !== 1 ? 's' : ''}</span>
        <svg
          width={14} height={14}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
          style={{ transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : '' }}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

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
