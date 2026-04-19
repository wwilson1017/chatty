import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDashboard, CrmDeal } from '../core/types';
import { ActivityTimeline } from './components/ActivityTimeline';
import { DealForm } from './components/DealForm';
import { WarmHalo } from '../shared/WarmHalo';
import { useIsMobile } from '../shared/useIsMobile';

const STAGE_COLORS: Record<string, { color: string; bg: string }> = {
  lead: { color: '#7B9EC4', bg: 'rgba(123,158,196,0.10)' },
  qualified: { color: '#C8D1D9', bg: 'rgba(200,209,217,0.10)' },
  proposal: { color: '#D4A85A', bg: 'rgba(212,168,90,0.10)' },
  negotiation: { color: '#D4855A', bg: 'rgba(212,133,90,0.10)' },
  won: { color: '#8EA589', bg: 'rgba(142,165,137,0.10)' },
  lost: { color: '#D97757', bg: 'rgba(217,119,87,0.10)' },
};

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function CrmDashboardPage() {
  const [data, setData] = useState<CrmDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedDeal, setSelectedDeal] = useState<CrmDeal | null>(null);
  const [editDeal, setEditDeal] = useState<CrmDeal | null>(null);
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  function reload() {
    api<CrmDashboard>('/api/crm/dashboard').then(setData);
  }

  async function updateDealStage(deal: CrmDeal, stage: string) {
    await api(`/api/crm/deals/${deal.id}`, {
      method: 'PUT', body: JSON.stringify({ stage }),
    });
    setSelectedDeal(null);
    reload();
  }

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

  const px = isMobile ? '20px' : '44px';

  return (
    <div style={{ position: 'relative', overflow: 'auto', height: '100%' }}>
      <WarmHalo opacity={0.3} />

      {/* Hero */}
      <div style={{ padding: isMobile ? '24px 20px 20px' : '36px 44px 28px', position: 'relative', zIndex: 2 }}>
        <div style={mono(10, 'rgba(237,240,244,0.38)')}>
          Week of {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </div>
        <h1 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: isMobile ? 30 : 48, fontWeight: 400, letterSpacing: '-0.02em',
          lineHeight: 1.1, margin: '10px 0 0', color: '#EDF0F4',
        }}>
          Pipeline is <span style={{ color: '#D4A85A', fontStyle: 'italic' }}>{totalPipelineValue}</span>
          <br /><span style={{ color: 'rgba(237,240,244,0.62)', fontSize: isMobile ? 16 : 26 }}>across {totalDeals} open deals.</span>
        </h1>
      </div>

      {/* Stage rows */}
      <div style={{ padding: `0 ${px} 28px`, position: 'relative', zIndex: 2 }}>
        <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
          {activePipeline.length === 0 ? (
            <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13, padding: '16px 0' }}>No active deals yet.</p>
          ) : (
            activePipeline.map(stage => {
              const pct = data.total_pipeline_value > 0 ? (stage.total_value / data.total_pipeline_value) * 100 : 0;
              return (
                <div key={stage.stage} onClick={() => navigate(`/crm/pipeline?stage=${stage.stage}`)} style={{
                  padding: '16px 0', borderBottom: '1px solid rgba(230,235,242,0.07)',
                  cursor: 'pointer',
                  ...(isMobile ? {
                    display: 'flex', flexDirection: 'column' as const, gap: 8,
                  } : {
                    display: 'grid', gridTemplateColumns: '150px 1fr 110px 80px',
                    gap: 20, alignItems: 'center',
                  }),
                }}>
                  {isMobile ? (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{
                            width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                            background: STAGE_COLORS[stage.stage]?.color || 'rgba(237,240,244,0.38)',
                          }} />
                          <span style={{
                            fontFamily: "'Fraunces', Georgia, serif",
                            fontSize: 16, letterSpacing: '-0.01em',
                            textTransform: 'capitalize', color: '#EDF0F4',
                          }}>{stage.stage}</span>
                        </div>
                        <div style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
                          <span style={{
                            fontFamily: "'Fraunces', Georgia, serif",
                            fontSize: 16, color: '#EDF0F4',
                          }}>${formatNumber(stage.total_value)}</span>
                          <span style={{ ...mono(9, 'rgba(237,240,244,0.62)') }}>{stage.count} deals</span>
                        </div>
                      </div>
                      <div style={{ height: 2, background: 'rgba(230,235,242,0.07)', position: 'relative' }}>
                        <div style={{
                          position: 'absolute', inset: 0,
                          right: `${100 - Math.max(pct, 2)}%`,
                          background: STAGE_COLORS[stage.stage]?.color || 'var(--color-ch-accent, #C8D1D9)',
                        }} />
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                          background: STAGE_COLORS[stage.stage]?.color || 'rgba(237,240,244,0.38)',
                        }} />
                        <span style={{
                          fontFamily: "'Fraunces', Georgia, serif",
                          fontSize: 20, letterSpacing: '-0.01em',
                          textTransform: 'capitalize', color: '#EDF0F4',
                        }}>{stage.stage}</span>
                      </div>
                      <div style={{ height: 2, background: 'rgba(230,235,242,0.07)', position: 'relative' }}>
                        <div style={{
                          position: 'absolute', inset: 0,
                          right: `${100 - Math.max(pct, 2)}%`,
                          background: STAGE_COLORS[stage.stage]?.color || 'var(--color-ch-accent, #C8D1D9)',
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
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Top deals + activity */}
      <div style={{
        padding: `10px ${px} 40px`, position: 'relative', zIndex: 2,
        display: isMobile ? 'flex' : 'grid',
        flexDirection: isMobile ? 'column' as const : undefined,
        gridTemplateColumns: isMobile ? undefined : '1.4fr 1fr',
        gap: isMobile ? 28 : 36,
      }}>
        <div>
          <div style={{ ...mono(10, 'rgba(237,240,244,0.38)'), marginBottom: 14 }}>Top deals</div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            {data.top_deals.length === 0 ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13, padding: '16px 0' }}>No deals yet.</p>
            ) : (
              data.top_deals.map(deal => (
                <div key={deal.id} onClick={() => setSelectedDeal(deal)} style={{
                  padding: '12px 14px', marginBottom: 6,
                  display: 'flex', alignItems: 'center', gap: 14,
                  cursor: 'pointer', borderRadius: 6,
                  background: STAGE_COLORS[deal.stage]?.bg || 'rgba(20,24,30,0.78)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  borderLeft: `3px solid ${STAGE_COLORS[deal.stage]?.color || 'rgba(230,235,242,0.14)'}`,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, letterSpacing: '-0.005em', color: '#EDF0F4' }}>
                      {deal.title}
                      {!isMobile && <span style={{ color: 'rgba(237,240,244,0.62)' }}> · {deal.contact_name || 'No contact'}</span>}
                    </div>
                    <div style={{
                      ...mono(10, STAGE_COLORS[deal.stage]?.color || 'rgba(237,240,244,0.38)'),
                      marginTop: 3, textTransform: 'uppercase',
                    }}>{deal.stage}{isMobile && deal.contact_name ? ` · ${deal.contact_name}` : ''}</div>
                  </div>
                  <div style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: isMobile ? 15 : 17, letterSpacing: '-0.01em', color: '#EDF0F4',
                    flexShrink: 0,
                  }}>${formatNumber(deal.value)}</div>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div style={{ ...mono(10, 'rgba(237,240,244,0.38)'), marginBottom: 14 }}>Recent activity</div>
          <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)' }}>
            <ActivityTimeline activities={data.recent_activity} onUpdate={reload} />
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <div style={{ padding: `0 ${px} 40px`, display: 'flex', gap: 8, position: 'relative', zIndex: 2, flexWrap: 'wrap' }}>
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

      {editDeal && <DealForm deal={editDeal} onClose={() => setEditDeal(null)} onSaved={() => { setEditDeal(null); setSelectedDeal(null); reload(); }} />}

      {/* Deal detail sheet */}
      {selectedDeal && (
        <div
          onClick={() => setSelectedDeal(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            zIndex: 50, display: 'flex',
            alignItems: isMobile ? 'flex-end' : 'center',
            justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#11141A',
              borderRadius: isMobile ? '12px 12px 0 0' : 8,
              border: '1px solid rgba(230,235,242,0.14)',
              borderBottom: isMobile ? 'none' : undefined,
              padding: isMobile ? '20px 20px 28px' : 28,
              width: '100%', maxWidth: 480, margin: isMobile ? 0 : '0 16px',
              boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
            }}
          >
            {isMobile && (
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(230,235,242,0.14)' }} />
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <h3 style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 20, fontWeight: 400, letterSpacing: '-0.01em',
                color: '#EDF0F4', margin: 0, flex: 1,
              }}>{selectedDeal.title}</h3>
              <span style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 20, color: '#D4A85A', flexShrink: 0, marginLeft: 12,
              }}>${selectedDeal.value.toLocaleString()}</span>
            </div>

            <div style={{
              fontSize: 12, color: 'rgba(237,240,244,0.62)', marginBottom: 16,
              textTransform: 'capitalize',
            }}>
              Stage: <span style={{ color: STAGE_COLORS[selectedDeal.stage]?.color || '#EDF0F4' }}>{selectedDeal.stage}</span>
            </div>

            {selectedDeal.notes && (
              <p style={{ fontSize: 14, color: 'rgba(237,240,244,0.62)', marginBottom: 16, lineHeight: 1.5 }}>
                {selectedDeal.notes}
              </p>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
              {selectedDeal.contact_name && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Contact</span>
                  <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selectedDeal.contact_name}</span>
                </div>
              )}
              {selectedDeal.probability > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Probability</span>
                  <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selectedDeal.probability}%</span>
                </div>
              )}
              {selectedDeal.expected_close_date && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Expected Close</span>
                  <span style={{ fontSize: 13, color: '#EDF0F4' }}>{selectedDeal.expected_close_date}</span>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button onClick={() => setSelectedDeal(null)} style={{
                padding: '10px 16px', borderRadius: 6,
                border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
                color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
              }}>Close</button>
              <button onClick={() => setEditDeal(selectedDeal)} style={{
                padding: '10px 16px', borderRadius: 6,
                border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
                color: '#EDF0F4', fontSize: 13, cursor: 'pointer',
              }}>Edit</button>
              {selectedDeal.stage !== 'won' && selectedDeal.stage !== 'lost' && (
                <>
                  <button onClick={() => updateDealStage(selectedDeal, 'won')} style={{
                    padding: '10px 16px', borderRadius: 6,
                    background: '#8EA589', color: '#0E1013',
                    border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
                    flex: 1,
                  }}>Mark Won</button>
                  <button onClick={() => updateDealStage(selectedDeal, 'lost')} style={{
                    padding: '10px 16px', borderRadius: 6,
                    background: 'rgba(217,119,87,0.1)', color: '#D97757',
                    border: '1px solid rgba(217,119,87,0.2)',
                    fontSize: 13, cursor: 'pointer',
                  }}>Mark Lost</button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K';
  return n.toLocaleString();
}
