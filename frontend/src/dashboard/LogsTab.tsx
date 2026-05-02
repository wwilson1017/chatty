import { useState, useEffect, useRef } from 'react';
import { api } from '../core/api/client';

interface LogRecord {
  id: string;
  agent: string;
  action_type: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  result_summary: string | null;
  result_full: string | null;
  tool_calls: { tool: string; args: string; result: string; duration_ms: number }[] | null;
  model_used: string | null;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
}

type StatusFilter = 'all' | 'ok' | 'error' | 'action_taken';

const STATUS_COLORS: Record<string, string> = {
  ok: '#8EA589',
  action_taken: '#D4A85A',
  error: '#D97757',
  lease_lost: '#D97757',
  skipped: '#6B7280',
  running: '#60A5FA',
};

function formatTime(iso: string): string {
  const d = new Date(iso + 'Z');
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export function LogsTab() {
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  async function fetchLogs(statusFilter: StatusFilter) {
    try {
      setError(null);
      const params = statusFilter !== 'all' ? `?status=${statusFilter}` : '';
      const result = await api<{ logs: LogRecord[] }>(`/api/scheduled-actions/logs${params}`);
      setLogs(result.logs);
    } catch {
      setError('Failed to load logs.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    fetchLogs(filter);
  }, [filter]);

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = window.setInterval(() => fetchLogs(filter), 30000);
    }
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [autoRefresh, filter]);

  const filters: { id: StatusFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'ok', label: 'OK' },
    { id: 'action_taken', label: 'Activity' },
    { id: 'error', label: 'Errors' },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {filters.map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                filter === f.id
                  ? 'bg-ch-accent/20 text-ch-accent font-medium'
                  : 'text-ch-ink-dim hover:text-ch-ink hover:bg-ch-bg-raised/50'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-ch-ink-dim cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
            className="accent-ch-accent"
          />
          Auto-refresh
        </label>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-ch-ink-dim py-8 justify-center">
          <div className="animate-spin w-4 h-4 border-2 border-ch-accent border-t-transparent rounded-full" />
          Loading logs...
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-ch-ink-dim">No scheduled action logs yet.</p>
        </div>
      ) : (
        <div className="space-y-1">
          {logs.map(rec => (
            <div key={rec.id} className="border border-ch-line-strong/50 rounded bg-ch-bg-elev">
              <button
                onClick={() => setExpanded(expanded === rec.id ? null : rec.id)}
                className="w-full px-3 py-2 flex items-center gap-3 text-left hover:bg-ch-bg-raised/30 transition-colors rounded text-xs"
              >
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: STATUS_COLORS[rec.status] || '#6B7280' }}
                />
                <span className="text-ch-ink-dim w-[130px] shrink-0 font-mono">
                  {formatTime(rec.started_at)}
                </span>
                <span className="text-ch-ink font-medium w-[100px] shrink-0 truncate">
                  {rec.agent}
                </span>
                <span className="text-ch-ink-dim w-[70px] shrink-0">
                  {rec.action_type}
                </span>
                <span
                  className="w-[80px] shrink-0 font-medium"
                  style={{ color: STATUS_COLORS[rec.status] || '#6B7280' }}
                >
                  {rec.status}
                </span>
                <span className="text-ch-ink-dim flex-1 truncate">
                  {rec.result_summary || ''}
                </span>
                <span className="text-ch-ink-dim shrink-0">
                  {rec.duration_ms ? `${(rec.duration_ms / 1000).toFixed(1)}s` : ''}
                </span>
                <span className="text-ch-ink-dim shrink-0 w-[50px] text-right">
                  {rec.input_tokens + rec.output_tokens > 0
                    ? formatTokens(rec.input_tokens + rec.output_tokens)
                    : ''}
                </span>
                <svg
                  className={`w-3 h-3 text-ch-ink-dim shrink-0 transition-transform ${expanded === rec.id ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {expanded === rec.id && (
                <div className="px-3 pb-3 border-t border-ch-line-strong/30 mt-0">
                  <div className="flex flex-wrap gap-3 mt-2 text-xs text-ch-ink-dim">
                    {rec.model_used && <span>Model: {rec.model_used}</span>}
                    <span>In: {formatTokens(rec.input_tokens)} / Out: {formatTokens(rec.output_tokens)}</span>
                    {rec.completed_at && <span>Completed: {formatTime(rec.completed_at)}</span>}
                  </div>

                  {rec.result_full && (
                    <pre className="mt-2 text-xs text-ch-ink-mute bg-ch-bg-raised/50 px-3 py-2 rounded max-h-48 overflow-auto whitespace-pre-wrap font-mono">
                      {rec.result_full}
                    </pre>
                  )}

                  {Array.isArray(rec.tool_calls) && rec.tool_calls.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="text-xs text-ch-ink-dim font-medium">Tool Calls ({rec.tool_calls.length})</div>
                      {rec.tool_calls.map((tc, i) => (
                        <div key={i} className="text-xs bg-ch-bg-raised/50 px-3 py-1.5 rounded font-mono">
                          <div className="flex items-center justify-between">
                            <span className="text-ch-ink">{tc.tool}</span>
                            <span className="text-ch-ink-dim">{tc.duration_ms}ms</span>
                          </div>
                          {tc.result && (
                            <div className="text-ch-ink-dim mt-0.5 max-h-12 overflow-auto whitespace-pre-wrap">
                              {tc.result}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
