/**
 * Chatty — AgentActivityPanel.
 * Shows recent heartbeat / scheduled activity for an agent.
 */

import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';

interface ActivityRecord {
  id: string;
  agent: string;
  action_type: string;
  started_at: string;
  status: string;
  result_summary: string | null;
  result_full: string | null;
  tool_calls: { tool: string; args: Record<string, unknown>; result: string; duration_ms: number }[] | null;
  model_used: string | null;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function timeAgo(iso: string): string {
  const d = new Date(iso + 'Z');
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export default function AgentActivityPanel({ apiPrefix }: { apiPrefix: string }) {
  const [records, setRecords] = useState<ActivityRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api<{ activities: ActivityRecord[] }>(`${apiPrefix}/activity?limit=20`);
        if (!cancelled) setRecords(result.activities);
      } catch {
        // Silently handle -- activity is supplementary
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [apiPrefix]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 py-8 justify-center">
        <div className="animate-spin w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full" />
        Loading activity...
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-sm text-gray-500">No recent heartbeat activity.</p>
        <p className="text-xs text-gray-600 mt-1">Actions taken during periodic checks will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2 p-4">
      <h3 className="text-sm font-semibold text-gray-200 mb-3">Recent Activity</h3>
      {records.map(rec => (
        <div key={rec.id} className="border border-gray-700 rounded-lg bg-gray-900">
          <button
            onClick={() => setExpanded(expanded === rec.id ? null : rec.id)}
            className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-gray-800/50 transition-colors rounded-lg"
          >
            <div className="w-2 h-2 rounded-full bg-indigo-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-200 capitalize">{rec.action_type}</span>
                <span className="text-xs text-gray-500">{timeAgo(rec.started_at)}</span>
              </div>
              {rec.result_summary && (
                <p className="text-xs text-gray-500 truncate mt-0.5">{rec.result_summary}</p>
              )}
            </div>
            <div className="text-xs text-gray-500 shrink-0 text-right">
              {rec.duration_ms ? `${(rec.duration_ms / 1000).toFixed(1)}s` : ''}
              {rec.tool_calls && ` | ${rec.tool_calls.length} tools`}
            </div>
            <svg
              className={`w-4 h-4 text-gray-500 shrink-0 transition-transform ${expanded === rec.id ? 'rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {expanded === rec.id && (
            <div className="px-4 pb-4 border-t border-gray-700/50">
              <div className="flex flex-wrap gap-3 mt-3 text-xs text-gray-500">
                {rec.model_used && <span>Model: {rec.model_used.split('-').slice(-2).join('-')}</span>}
                <span>Tokens: {formatTokens(rec.input_tokens + rec.output_tokens)}</span>
                <span>{new Date(rec.started_at + 'Z').toLocaleString()}</span>
              </div>

              {rec.result_full && (
                <div className="mt-3">
                  <div className="text-xs text-gray-400 bg-gray-800/50 px-3 py-2 rounded max-h-40 overflow-auto whitespace-pre-wrap">
                    {rec.result_full}
                  </div>
                </div>
              )}

              {rec.tool_calls && rec.tool_calls.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {rec.tool_calls.map((tc, i) => (
                    <div key={i} className="text-xs bg-gray-800/50 px-3 py-2 rounded">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-gray-200">{tc.tool}</span>
                        <span className="text-gray-500">{tc.duration_ms}ms</span>
                      </div>
                      {tc.result && (
                        <div className="text-gray-500 mt-1 max-h-16 overflow-auto whitespace-pre-wrap">{tc.result}</div>
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
  );
}
