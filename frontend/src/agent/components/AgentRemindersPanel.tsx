/**
 * Chatty — AgentRemindersPanel.
 * Read-only view of all reminders for an agent.
 */

import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { Reminder } from '../../core/types';

function toUTC(iso: string): Date {
  return new Date(iso.replace(' ', 'T') + 'Z');
}

function timeAgo(iso: string): string {
  const d = toUTC(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 0) return formatFuture(-diff);
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function formatFuture(diff: number): string {
  if (diff < 60000) return 'In <1m';
  if (diff < 3600000) return `In ${Math.floor(diff / 60000)}m`;
  if (diff < 86400000) return `In ${Math.floor(diff / 3600000)}h`;
  return `In ${Math.floor(diff / 86400000)}d`;
}

function formatDate(iso: string): string {
  return toUTC(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function describeRecurrence(ruleJson: string | null): string | null {
  if (!ruleJson) return null;
  try {
    const rule = JSON.parse(ruleJson);
    const dayNames: Record<number, string> = { 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat', 7: 'Sun' };
    switch (rule.type) {
      case 'daily': return 'Daily';
      case 'weekly': {
        const days = (rule.days || []).map((d: number) => dayNames[d] || d).join(', ');
        return `Weekly: ${days}`;
      }
      case 'monthly': return `Monthly: day ${rule.day ?? '?'}`;
      case 'interval': {
        if (rule.hours && !rule.minutes) return `Every ${rule.hours}h`;
        if (rule.minutes && !rule.hours) return `Every ${rule.minutes}m`;
        return `Every ${rule.hours || 0}h ${rule.minutes || 0}m`;
      }
      case 'cron': return `Cron: ${rule.expression || '?'}`;
      default: return null;
    }
  } catch { return null; }
}

const statusColors: Record<string, string> = {
  pending: '#6DBF5B',
  fired: '#8B8F96',
  cancelled: '#D97757',
};

interface SeriesCache {
  [seriesId: string]: Reminder[];
}

export default function AgentRemindersPanel({ agentSlug }: { agentSlug: string }) {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [seriesCache, setSeriesCache] = useState<SeriesCache>({});
  const [loadingSeries, setLoadingSeries] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api<{ reminders: Reminder[] }>(`/api/reminders?agent=${agentSlug}&limit=100`);
        if (!cancelled) setReminders(result.reminders);
      } catch {
        // Supplementary — fail silently
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [agentSlug]);

  const toggleSection = (section: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section); else next.add(section);
      return next;
    });
  };

  const loadSeries = async (seriesId: string) => {
    if (seriesCache[seriesId]) return;
    setLoadingSeries(seriesId);
    try {
      const result = await api<{ history: Reminder[] }>(`/api/reminders/series/${seriesId}?limit=20`);
      setSeriesCache(prev => ({ ...prev, [seriesId]: result.history }));
    } catch { /* ignore */ }
    setLoadingSeries(null);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-ch-ink-dim py-8 justify-center">
        <div className="animate-spin w-4 h-4 border-2 border-ch-accent border-t-transparent rounded-full" />
        Loading reminders...
      </div>
    );
  }

  if (reminders.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-sm text-ch-ink-dim">No reminders yet.</p>
        <p className="text-xs text-ch-ink-dim mt-1">Ask your agent to set a reminder and it will appear here.</p>
      </div>
    );
  }

  const pending = reminders.filter(r => r.status === 'pending')
    .sort((a, b) => a.due_at.localeCompare(b.due_at));
  const fired = reminders.filter(r => r.status === 'fired').slice(0, 20);
  const cancelled = reminders.filter(r => r.status === 'cancelled').slice(0, 10);

  const sections: { key: string; label: string; items: Reminder[]; emptyText: string }[] = [
    { key: 'upcoming', label: `Upcoming (${pending.length})`, items: pending, emptyText: 'No pending reminders.' },
    { key: 'completed', label: `Completed (${fired.length})`, items: fired, emptyText: 'No fired reminders yet.' },
    { key: 'cancelled', label: `Cancelled (${cancelled.length})`, items: cancelled, emptyText: '' },
  ];

  return (
    <div className="space-y-4 p-4">
      {sections.map(section => {
        if (section.items.length === 0 && !section.emptyText) return null;
        const isCollapsed = collapsedSections.has(section.key);
        return (
          <div key={section.key}>
            <button
              onClick={() => toggleSection(section.key)}
              className="flex items-center gap-2 mb-2 text-sm font-semibold text-ch-ink hover:text-ch-accent transition-colors w-full text-left"
            >
              <svg
                className={`w-3 h-3 text-ch-ink-dim transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
              {section.label}
            </button>

            {!isCollapsed && (
              section.items.length === 0 ? (
                <p className="text-xs text-ch-ink-dim pl-5">{section.emptyText}</p>
              ) : (
                <div className="space-y-2">
                  {section.items.map(rem => (
                    <ReminderRow
                      key={rem.id}
                      reminder={rem}
                      isExpanded={expanded === rem.id}
                      onToggle={() => setExpanded(expanded === rem.id ? null : rem.id)}
                      seriesHistory={rem.series_id ? seriesCache[rem.series_id] : undefined}
                      loadingSeries={loadingSeries === rem.series_id}
                      onLoadSeries={() => rem.series_id && loadSeries(rem.series_id)}
                    />
                  ))}
                </div>
              )
            )}
          </div>
        );
      })}
    </div>
  );
}

function ReminderRow({
  reminder: rem,
  isExpanded,
  onToggle,
  seriesHistory,
  loadingSeries,
  onLoadSeries,
}: {
  reminder: Reminder;
  isExpanded: boolean;
  onToggle: () => void;
  seriesHistory?: Reminder[];
  loadingSeries: boolean;
  onLoadSeries: () => void;
}) {
  const recurrenceDesc = describeRecurrence(rem.recurrence_rule);

  return (
    <div className="border border-ch-line-strong rounded-lg bg-ch-bg-elev">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-ch-bg-raised/50 transition-colors rounded-lg"
      >
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: statusColors[rem.status] || '#8B8F96' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium text-ch-ink">{rem.message.length > 60 ? rem.message.slice(0, 60) + '...' : rem.message}</span>
            {recurrenceDesc && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                backgroundColor: 'rgba(109,191,91,0.12)', color: '#6DBF5B',
                fontFamily: 'JetBrains Mono, monospace',
              }}>
                {recurrenceDesc}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xs text-ch-ink-dim">
              {rem.status === 'pending' ? timeAgo(rem.due_at) : timeAgo(rem.fired_at || rem.due_at)}
            </span>
            {rem.status === 'pending' && (
              <span className="text-xs text-ch-ink-dim">
                ({formatDate(rem.due_at)})
              </span>
            )}
          </div>
        </div>
        <svg
          className={`w-4 h-4 text-ch-ink-dim shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 border-t border-ch-line-strong/50">
          <div className="mt-3 space-y-2">
            <div className="text-xs text-ch-ink">
              <span className="text-ch-ink-dim">Message: </span>{rem.message}
            </div>
            {rem.context && (
              <div className="text-xs text-ch-ink">
                <span className="text-ch-ink-dim">Context: </span>{rem.context}
              </div>
            )}
            <div className="flex flex-wrap gap-3 text-xs text-ch-ink-dim">
              <span>Due: {formatDate(rem.due_at)}</span>
              <span>Created: {formatDate(rem.created_at)}</span>
              {rem.fired_at && <span>Fired: {formatDate(rem.fired_at)}</span>}
              <span className="capitalize">Status: {rem.status}</span>
            </div>

            {rem.result && (
              <div className="mt-2">
                <div className="text-xs text-ch-ink-dim mb-1">Result:</div>
                <div className="text-xs text-ch-ink-mute bg-ch-bg-raised/50 px-3 py-2 rounded max-h-32 overflow-auto whitespace-pre-wrap">
                  {rem.result}
                </div>
              </div>
            )}

            {rem.is_recurring && rem.series_id && (
              <div className="mt-2">
                {seriesHistory ? (
                  <div>
                    <div className="text-xs text-ch-ink-dim mb-1">Series History ({seriesHistory.length})</div>
                    <div className="space-y-1 max-h-32 overflow-auto">
                      {seriesHistory.map(h => (
                        <div key={h.id} className="flex items-center gap-2 text-xs">
                          <div
                            className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ backgroundColor: statusColors[h.status] || '#8B8F96' }}
                          />
                          <span className="text-ch-ink-dim">{formatDate(h.due_at)}</span>
                          <span className="text-ch-ink-dim capitalize">{h.status}</span>
                          {h.result && (
                            <span className="text-ch-ink-mute truncate">{h.result.slice(0, 60)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={onLoadSeries}
                    disabled={loadingSeries}
                    className="text-xs text-ch-accent hover:underline"
                  >
                    {loadingSeries ? 'Loading...' : 'View series history'}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
