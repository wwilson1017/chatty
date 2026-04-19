import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDashboard } from '../core/types';
import { ActivityTimeline } from './components/ActivityTimeline';
import { WarmHalo } from '../shared/WarmHalo';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function CrmDashboardPage() {
  const [data, setData] = useState<CrmDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api<CrmDashboard>('/api/crm/dashboard')
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
        <div className="w-8 h-8 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) return <p style={{ color: 'rgba(237,240,244,0.62)', padding: 32 }}>Failed to load CRM dashboard.</p>;

  const activePipeline = data.pipeline_by_stage.filter(s => s.stage !== 'won' && s.stage !== 'lost');
  const totalPipelineValue = `$${formatNumber(data.total_pipeline_value)}`;
  const totalDeals = activePipeline.reduce((s, p) => s + p.count, 0);

  return (
    <div style={{ position: 'relative', overflow: 'auto', height: '100%' }}>
      <WarmHalo opacity={0.3} />

      {/* Hero */}
      <div style={{ padding: '36px 44px 28px', position: 'relative', zIndex: 2 }}>
        <div style={mono(10, 'rgba(237,240,244,0.38)')}>
          Week of {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </div>
        <h1 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 48, fontWeight: 400, letterSpacing: '-0.02em',
          lineHeight: 1.02, margin: '10px 0 0', color: '#EDF0F4',
        }}>
          Pipeline is <span style={{ color: '#D4A85A', fontStyle: 'italic' }}>{totalPipelineValue}</span>
          <br /><span style={{ color: 'rgba(237,240,244,0.62)', fontSize: 26 }}>across {totalDeals} open deals.</span>
        </h1>
      </div>

      {/* Stage rows */}
      <div style={{ padding: '0 44px 28px', position: 'relative', zIndex: 2 }}>
        <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
          {activePipeline.length === 0 ? (
            <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13, padding: '16px 0' }}>No active deals yet.</p>
          ) : (
            activePipeline.map(stage => {
              const pct = data.total_pipeline_value > 0 ? (stage.total_value / data.total_pipeline_value) * 100 : 0;
              return (
                <div key={stage.stage} style={{
                  padding: '16px 0', borderBottom: '1px solid rgba(230,235,242,0.07)',
                  display: 'grid', gridTemplateColumns: '150px 1fr 110px 80px',
                  gap: 20, alignItems: 'center',
                }}>
                  <div style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 20, letterSpacing: '-0.01em',
                    textTransform: 'capitalize', color: '#EDF0F4',
                  }}>{stage.stage}</div>
                  <div style={{ height: 2, background: 'rgba(230,235,242,0.07)', position: 'relative' }}>
                    <div style={{
                      position: 'absolute', inset: 0,
                      right: `${100 - Math.max(pct, 2)}%`,
                      background: 'linear-gradient(90deg, var(--color-ch-accent, #C8D1D9) 0%, #D4A85A 100%)',
                    }} />
                  </div>
                  <div style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 18, fontWeight: 400, textAlign: 'right',
                    letterSpacing: '-0.01em', color: '#EDF0F4',
                  }}>${formatNumber(stage.total_value)}</div>
                  <div style={{
                    ...mono(10, 'rgba(237,240,244,0.62)'),
                    textAlign: 'right',
                  }}>{stage.count} deals</div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Top deals + activity */}
      <div style={{
        padding: '10px 44px 40px', position: 'relative', zIndex: 2,
        display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 36,
      }}>
        <div>
          <div style={{ ...mono(10, 'rgba(237,240,244,0.38)'), marginBottom: 14 }}>Top deals</div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {data.top_deals.length === 0 ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13, padding: '16px 0' }}>No deals yet.</p>
            ) : (
              data.top_deals.map(deal => (
                <div key={deal.id} style={{
                  padding: '14px 0', display: 'flex', alignItems: 'center', gap: 14,
                  borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, letterSpacing: '-0.005em', color: '#EDF0F4' }}>
                      {deal.title} <span style={{ color: 'rgba(237,240,244,0.62)' }}>· {deal.contact_name || 'No contact'}</span>
                    </div>
                    <div style={{
                      ...mono(10, 'rgba(237,240,244,0.38)'),
                      marginTop: 3, textTransform: 'uppercase',
                    }}>{deal.stage}</div>
                  </div>
                  <div style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 17, letterSpacing: '-0.01em', color: '#EDF0F4',
                  }}>${formatNumber(deal.value)}</div>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div style={{ ...mono(10, 'rgba(237,240,244,0.38)'), marginBottom: 14 }}>Recent activity</div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            <ActivityTimeline activities={data.recent_activity} />
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <div style={{ padding: '0 44px 40px', display: 'flex', gap: 8, position: 'relative', zIndex: 2 }}>
        {[
          { label: '+ Add Contact', path: '/crm/contacts' },
          { label: '+ Add Deal', path: '/crm/pipeline' },
          { label: '+ Add Task', path: '/crm/tasks' },
        ].map(a => (
          <button
            key={a.label}
            onClick={() => navigate(a.path)}
            style={{
              background: 'transparent', color: '#EDF0F4',
              border: '1px solid rgba(230,235,242,0.14)',
              padding: '7px 14px', borderRadius: 4,
              fontSize: 13, cursor: 'pointer',
              fontFamily: "'Inter Tight', system-ui, sans-serif",
            }}
          >{a.label}</button>
        ))}
      </div>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K';
  return n.toLocaleString();
}
