import { useState } from 'react';
import type { ActivityRecord } from '../../hooks/useHeartbeat';
import { FONT_SANS, FONT_MONO, INK, INK_DIM, INK_MUTE, BG_ELEV, LINE_STRONG, SAGE, GOLD, CORAL } from '../../../shared/styles';

const statusColors: Record<string, string> = {
  ok: SAGE,
  action_taken: GOLD,
  error: CORAL,
  skipped: INK_DIM,
};

function timeAgo(iso: string): string {
  const d = new Date(iso + 'Z');
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

interface Props {
  history: ActivityRecord[];
}

export function HeartbeatHistory({ history }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div style={{ padding: '16px 24px' }}>
      <span style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase', color: INK_DIM, display: 'block', marginBottom: 12 }}>
        RECENT RUNS
      </span>

      {history.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <p style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK_DIM }}>No heartbeat runs yet.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {history.map(rec => {
            const isExpanded = expanded === rec.id;
            const color = statusColors[rec.status] || INK_DIM;

            return (
              <div key={rec.id} style={{ background: BG_ELEV, border: `1px solid ${LINE_STRONG}`, borderRadius: 6 }}>
                <button
                  onClick={() => setExpanded(isExpanded ? null : rec.id)}
                  style={{
                    width: '100%', padding: '10px 14px', border: 'none', background: 'none',
                    display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', textAlign: 'left',
                  }}
                >
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500, color: INK, textTransform: 'capitalize' }}>
                        {rec.status.replace('_', ' ')}
                      </span>
                      <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: INK_DIM }}>{timeAgo(rec.started_at)}</span>
                    </div>
                    {rec.result_summary && (
                      <p style={{
                        fontFamily: FONT_SANS, fontSize: 12, color: INK_MUTE, marginTop: 2,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>{rec.result_summary}</p>
                    )}
                  </div>

                  <div style={{ fontFamily: FONT_SANS, fontSize: 11, color: INK_DIM, flexShrink: 0, textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {rec.duration_ms ? `${(rec.duration_ms / 1000).toFixed(1)}s` : ''}
                    {Array.isArray(rec.tool_calls) && rec.tool_calls.filter(tc => tc && typeof tc === 'object' && tc.tool).length > 0
                      ? ` · ${rec.tool_calls.filter(tc => tc && typeof tc === 'object' && tc.tool).length} tools`
                      : ''}
                  </div>

                  <svg
                    width="14" height="14" viewBox="0 0 24 24" fill="none"
                    stroke={INK_DIM} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    style={{ flexShrink: 0, transition: 'transform 0.2s', transform: isExpanded ? 'rotate(180deg)' : 'none' }}
                  >
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </button>

                {isExpanded && (
                  <div style={{ padding: '0 14px 14px', borderTop: `1px solid ${LINE_STRONG}` }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 10, fontFamily: FONT_SANS, fontSize: 11, color: INK_DIM }}>
                      {rec.model_used && <span>Model: {rec.model_used.split('-').slice(-2).join('-')}</span>}
                      <span>Tokens: {formatTokens(rec.input_tokens + rec.output_tokens)}</span>
                      <span>{new Date(rec.started_at + 'Z').toLocaleString()}</span>
                    </div>

                    {rec.result_full && (
                      <div style={{
                        marginTop: 10, fontFamily: FONT_SANS, fontSize: 12, color: INK_MUTE,
                        background: 'rgba(34,40,48,0.35)', padding: '8px 12px', borderRadius: 4,
                        maxHeight: 160, overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.5,
                      }}>
                        {rec.result_full}
                      </div>
                    )}

                    {Array.isArray(rec.tool_calls) && rec.tool_calls.length > 0 && (
                      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {rec.tool_calls.filter(tc => tc && typeof tc === 'object' && tc.tool).map((tc, i) => (
                          <div key={i} style={{
                            fontFamily: FONT_SANS, fontSize: 12,
                            background: 'rgba(34,40,48,0.35)', padding: '6px 12px', borderRadius: 4,
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontWeight: 500, color: INK }}>{tc.tool}</span>
                              {tc.duration_ms != null && <span style={{ color: INK_DIM, fontSize: 11 }}>{tc.duration_ms}ms</span>}
                            </div>
                            {tc.result && (
                              <div style={{ color: INK_DIM, marginTop: 4, maxHeight: 64, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
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
            );
          })}
        </div>
      )}
    </div>
  );
}
