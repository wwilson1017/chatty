/**
 * Chatty — Usage & estimated cost dashboard.
 * Aggregated token/cost data from /api/usage/summary, bucketed daily
 * in the browser's timezone. Costs are estimates from published prices.
 */

import { useEffect, useRef, useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { api } from '../core/api/client';
import { LoadError } from '../shared/LoadError';
import { IconChart } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';
import {
  INK, INK_MUTE, INK_DIM, LINE, BG_ELEV,
  FONT_DISPLAY, FONT_SANS, FONT_MONO, mono, formatNumber,
  SAGE_HEX, GOLD_HEX,
} from '../shared/styles';

interface DailyUsage {
  date: string;
  chat_cost: number;
  background_cost: number;
  chat_tokens: number;
  background_tokens: number;
  events: number;
}

interface AgentUsage {
  slug: string;
  name: string;
  primary_model: string;
  input_tokens: number;
  output_tokens: number;
  events: number;
  chat_events: number;
  background_events: number;
  cost: number;
}

interface UsageSummary {
  days: number;
  timezone: string;
  estimated: boolean;
  totals: { cost: number; input_tokens: number; output_tokens: number; events: number };
  daily: DailyUsage[];
  agents: AgentUsage[];
}

const RANGES = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: 'All time', days: 0 },
];

function formatCost(n: number): string {
  return `$${n.toFixed(2)}`;
}

function formatDay(date: string): string {
  // Parse "YYYY-MM-DD" manually — new Date(string) parses as UTC midnight
  // and shifts the day in negative-offset timezones.
  const [y, m, d] = date.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const cardStyle = {
  background: BG_ELEV,
  border: `1px solid ${LINE}`,
  borderRadius: 6,
  padding: '18px 20px',
};

export function UsagePage() {
  const [days, setDays] = useState(7);
  const [metric, setMetric] = useState<'cost' | 'tokens'>('cost');
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const isMobile = useIsMobile();

  const abortRef = useRef<AbortController | null>(null);

  function load() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    api<UsageSummary>(`/api/usage/summary?days=${days}&tz=${encodeURIComponent(tz)}`, { signal: ctrl.signal })
      .then(d => { if (!ctrl.signal.aborted) { setData(d); setError(false); } })
      .catch((err) => { if (!ctrl.signal.aborted) { console.error('[UsagePage] load failed:', err); setError(true); } })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
  }

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [days]);

  const px = isMobile ? '20px' : '44px';

  if (loading && !data) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <div className="w-8 h-8 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (error && !data) {
    return <LoadError label="Couldn't load usage data" onRetry={() => { setLoading(true); load(); }} />;
  }

  if (!data) return null;

  const hasUsage = data.totals.events > 0;
  const chartKeys = metric === 'cost'
    ? { chat: 'chat_cost', background: 'background_cost' }
    : { chat: 'chat_tokens', background: 'background_tokens' };
  const formatMetric = metric === 'cost' ? formatCost : formatNumber;

  return (
    <div style={{ overflow: 'auto', height: '100%', background: '#0A0C0F' }}>
      {/* Header */}
      <div style={{
        padding: isMobile ? '24px 20px 16px' : '36px 44px 20px',
        display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 16,
      }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={mono(10, INK_DIM)}>Usage &amp; Cost</div>
          <h1 style={{
            fontFamily: FONT_DISPLAY, fontSize: isMobile ? 28 : 38, fontWeight: 400,
            letterSpacing: '-0.02em', lineHeight: 1.1, margin: '8px 0 0', color: INK,
          }}>
            Usage
          </h1>
        </div>

        {/* Range tabs */}
        <div style={{ display: 'flex', gap: 6 }}>
          {RANGES.map(r => {
            const active = days === r.days;
            return (
              <button
                key={r.days}
                onClick={() => { setLoading(true); setDays(r.days); }}
                style={{
                  fontFamily: FONT_MONO, fontSize: 11, letterSpacing: '0.06em',
                  padding: '6px 14px', borderRadius: 999, cursor: 'pointer',
                  background: active ? 'rgba(200,209,217,0.12)' : 'transparent',
                  border: `1px solid ${active ? 'rgba(230,235,242,0.2)' : LINE}`,
                  color: active ? INK : 'rgba(237,240,244,0.5)',
                }}
              >
                {r.label}
              </button>
            );
          })}
        </div>
      </div>

      {!hasUsage ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: 14, padding: '80px 20px',
          color: 'rgba(237,240,244,0.25)',
        }}>
          <IconChart size={36} strokeWidth={1.5} />
          <div style={{ fontFamily: FONT_SANS, fontSize: 14, color: 'rgba(237,240,244,0.38)' }}>
            No usage recorded yet.
          </div>
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)',
            gap: 12, padding: `0 ${px} 16px`,
          }}>
            <div style={cardStyle}>
              <div style={mono(10, INK_DIM)}>Estimated Cost</div>
              <div style={{
                fontFamily: FONT_DISPLAY, fontSize: 34, fontWeight: 400,
                color: INK, marginTop: 8, lineHeight: 1,
              }}>
                {formatCost(data.totals.cost)}
              </div>
            </div>
            <div style={cardStyle}>
              <div style={mono(10, INK_DIM)}>Total Tokens</div>
              <div style={{
                fontFamily: FONT_DISPLAY, fontSize: 34, fontWeight: 400,
                color: INK, marginTop: 8, lineHeight: 1,
              }}>
                {formatNumber(data.totals.input_tokens + data.totals.output_tokens)}
              </div>
              <div style={{ fontFamily: FONT_MONO, fontSize: 10, color: INK_DIM, marginTop: 8 }}>
                {formatNumber(data.totals.input_tokens)} in / {formatNumber(data.totals.output_tokens)} out
              </div>
            </div>
            <div style={cardStyle}>
              <div style={mono(10, INK_DIM)}>Events</div>
              <div style={{
                fontFamily: FONT_DISPLAY, fontSize: 34, fontWeight: 400,
                color: INK, marginTop: 8, lineHeight: 1,
              }}>
                {data.totals.events.toLocaleString()}
              </div>
            </div>
          </div>

          {/* Daily chart */}
          <div style={{ padding: `0 ${px} 16px` }}>
            <div style={{ ...cardStyle, padding: '18px 14px 10px 6px' }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0 8px 14px 22px',
              }}>
                <div style={mono(10, INK_DIM)}>Daily {metric === 'cost' ? 'Cost' : 'Tokens'}</div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {(['cost', 'tokens'] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => setMetric(m)}
                      style={{
                        fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.08em',
                        textTransform: 'uppercase', padding: '4px 10px', borderRadius: 4,
                        cursor: 'pointer', border: 'none',
                        background: metric === m ? 'rgba(200,209,217,0.12)' : 'transparent',
                        color: metric === m ? INK : 'rgba(237,240,244,0.4)',
                      }}
                    >
                      {m === 'cost' ? 'Cost' : 'Tokens'}
                    </button>
                  ))}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data.daily} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(230,235,242,0.07)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDay}
                    tick={{ fontSize: 10, fill: '#6B7280', fontFamily: FONT_MONO }}
                    axisLine={{ stroke: 'rgba(230,235,242,0.07)' }}
                    tickLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tickFormatter={(v: number) => formatMetric(v)}
                    tick={{ fontSize: 10, fill: '#6B7280', fontFamily: FONT_MONO }}
                    axisLine={false}
                    tickLine={false}
                    width={56}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(230,235,242,0.04)' }}
                    labelFormatter={(label) => formatDay(String(label))}
                    formatter={(value, name) => [
                      formatMetric(Number(value)),
                      name === chartKeys.chat ? 'Chat' : 'Background',
                    ]}
                    contentStyle={{
                      backgroundColor: '#1A1D24',
                      border: '1px solid rgba(230,235,242,0.14)',
                      borderRadius: 6,
                      fontFamily: FONT_MONO,
                      fontSize: 11,
                    }}
                    labelStyle={{ color: '#EDF0F4' }}
                    itemStyle={{ color: 'rgba(237,240,244,0.78)' }}
                  />
                  <Bar dataKey={chartKeys.chat} stackId="usage" fill={SAGE_HEX} />
                  <Bar dataKey={chartKeys.background} stackId="usage" fill={GOLD_HEX} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              {/* Legend */}
              <div style={{ display: 'flex', gap: 16, padding: '8px 0 4px 22px' }}>
                {[{ label: 'Chat', color: SAGE_HEX }, { label: 'Background', color: GOLD_HEX }].map(item => (
                  <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2, background: item.color }} />
                    <span style={{ fontFamily: FONT_MONO, fontSize: 10, color: INK_DIM }}>{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Per-agent table */}
          <div style={{ padding: `0 ${px} 8px` }}>
            <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT_SANS, fontSize: 13 }}>
                  <thead>
                    <tr>
                      {['Agent', 'Model', 'Tokens', 'Events', 'Est. Cost'].map((h, i) => (
                        <th
                          key={h}
                          style={{
                            ...mono(9, INK_DIM),
                            textAlign: i >= 2 ? 'right' : 'left',
                            padding: '12px 16px',
                            borderBottom: `1px solid ${LINE}`,
                            fontWeight: 400,
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.agents.map(a => (
                      <tr key={a.slug}>
                        <td style={{ padding: '11px 16px', color: INK, borderBottom: `1px solid ${LINE}` }}>
                          {a.name}
                        </td>
                        <td style={{
                          padding: '11px 16px', color: INK_MUTE, borderBottom: `1px solid ${LINE}`,
                          fontFamily: FONT_MONO, fontSize: 11,
                        }}>
                          {a.primary_model || '—'}
                        </td>
                        <td style={{
                          padding: '11px 16px', textAlign: 'right', color: INK_MUTE,
                          borderBottom: `1px solid ${LINE}`, fontFamily: FONT_MONO, fontSize: 11,
                          whiteSpace: 'nowrap',
                        }}>
                          {formatNumber(a.input_tokens)} in / {formatNumber(a.output_tokens)} out
                        </td>
                        <td style={{
                          padding: '11px 16px', textAlign: 'right', color: INK_MUTE,
                          borderBottom: `1px solid ${LINE}`, fontFamily: FONT_MONO, fontSize: 11,
                        }}>
                          {a.events.toLocaleString()}
                        </td>
                        <td style={{
                          padding: '11px 16px', textAlign: 'right', color: INK,
                          borderBottom: `1px solid ${LINE}`, fontFamily: FONT_MONO, fontSize: 11,
                        }}>
                          {formatCost(a.cost)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Disclaimer */}
      <div style={{
        padding: `8px ${px} 28px`,
        fontFamily: FONT_SANS, fontSize: 11, color: 'rgba(237,240,244,0.38)',
      }}>
        Costs are estimates based on published API prices. Unpriced and local models show $0.00.
      </div>
    </div>
  );
}
