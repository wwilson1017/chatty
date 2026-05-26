import { useState, useEffect, useRef } from 'react';
import type { AgentNotification } from '../../core/types';
import { api } from '../../core/api/client';

interface Props {
  agentSlug: string;
}

function timeAgo(iso: string): string {
  const d = new Date(iso + 'Z');
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export default function NotificationLog({ agentSlug }: Props) {
  const [notifications, setNotifications] = useState<AgentNotification[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const fetchRef = useRef<() => Promise<void>>();
  fetchRef.current = async () => {
    try {
      const data = await api<AgentNotification[]>(
        `/api/notifications?agent=${agentSlug}&status=active&limit=10`
      );
      setNotifications(data);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchRef.current?.();
    const interval = setInterval(() => fetchRef.current?.(), 30000);
    return () => clearInterval(interval);
  }, [agentSlug]);

  const dismiss = async (id: string) => {
    try {
      await api(`/api/notifications/${id}/dismiss`, { method: 'POST' });
      setNotifications(prev => prev.filter(n => n.id !== id));
    } catch { /* ignore */ }
  };

  const dismissAll = async () => {
    try {
      await api('/api/notifications/dismiss-all', {
        method: 'POST',
        body: JSON.stringify({ agent: agentSlug }),
      });
      setNotifications([]);
    } catch { /* ignore */ }
  };

  const toggleExpand = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (notifications.length === 0) return null;

  const latest = notifications[0];

  return (
    <div style={{
      margin: '8px 16px',
      border: '1px solid rgba(140,160,200,0.2)',
      borderRadius: 8,
      background: 'rgba(140,160,200,0.04)',
      overflow: 'hidden',
    }}>
      {/* Collapsed: single-line summary */}
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
          stroke="#8CA0C8" strokeWidth="1.5" strokeLinecap="round"
          style={{ flexShrink: 0, transition: 'transform 0.2s', transform: expanded ? 'rotate(90deg)' : 'none' }}
        >
          <path d="M3 1l4 4-4 4" />
        </svg>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
          color: '#8CA0C8',
          fontWeight: 600,
          flexShrink: 0,
        }}>
          {notifications.length}
        </span>
        {!expanded && (
          <span style={{
            fontFamily: "'Inter', sans-serif",
            fontSize: 12,
            color: 'rgba(200,209,217,0.5)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
            minWidth: 0,
          }}>
            {latest.title} — {timeAgo(latest.created_at)}
          </span>
        )}
        {expanded && (
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: '#8CA0C8',
            fontWeight: 600,
          }}>
            notification{notifications.length !== 1 ? 's' : ''}
          </span>
        )}
        {expanded && (
          <button
            onClick={(e) => { e.stopPropagation(); dismissAll(); }}
            style={{
              marginLeft: 'auto',
              background: 'none',
              border: 'none',
              color: 'rgba(140,160,200,0.5)',
              cursor: 'pointer',
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              padding: '0 2px',
            }}
          >
            Clear all
          </button>
        )}
      </div>

      {/* Expanded: full list */}
      {expanded && (
        <div style={{ padding: '0 12px 8px' }}>
          {notifications.map(n => {
            const isItemExpanded = expandedIds.has(n.id);
            const preview = n.message.length > 120 && !isItemExpanded
              ? n.message.slice(0, 120) + '...'
              : n.message;

            return (
              <div key={n.id} style={{
                padding: '8px 0',
                borderTop: '1px solid rgba(140,160,200,0.1)',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontFamily: "'Inter', sans-serif",
                      fontSize: 13,
                      fontWeight: 600,
                      color: '#C8D1D9',
                      marginBottom: 2,
                    }}>
                      {n.title}
                    </div>
                    <div
                      onClick={() => n.message.length > 120 && toggleExpand(n.id)}
                      style={{
                        fontFamily: "'Inter', sans-serif",
                        fontSize: 12,
                        color: 'rgba(200,209,217,0.6)',
                        lineHeight: 1.4,
                        cursor: n.message.length > 120 ? 'pointer' : 'default',
                        whiteSpace: isItemExpanded ? 'pre-wrap' : undefined,
                      }}
                    >
                      {preview}
                    </div>
                    <div style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: 10,
                      color: 'rgba(140,160,200,0.4)',
                      marginTop: 4,
                    }}>
                      {timeAgo(n.created_at)}
                      {n.channels_sent.length > 0 && ` · ${n.channels_sent.join(', ')}`}
                    </div>
                  </div>
                  <button
                    onClick={() => dismiss(n.id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'rgba(140,160,200,0.4)',
                      cursor: 'pointer',
                      fontSize: 16,
                      lineHeight: 1,
                      padding: '0 4px',
                      marginLeft: 8,
                    }}
                    title="Dismiss"
                  >
                    ×
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
