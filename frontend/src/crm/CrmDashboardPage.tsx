import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDashboard, CrmDeal } from '../core/types';
import { ActivityTimeline } from './components/ActivityTimeline';
import { DealForm } from './components/DealForm';
import { DealDetailSheet } from './components/DealDetailSheet';
import { STAGE_COLORS, STAGE_ORDER } from './constants';
import { WarmHalo } from '../shared/WarmHalo';
import { useIsMobile } from '../shared/useIsMobile';
import {
  INK, INK_MUTE, INK_SOFT, INK_DIM, LINE,
  GOLD, FONT_DISPLAY, FONT_SANS,
  mono, formatNumber,
} from '../shared/styles';
import { sectionHeading, btnSecondary } from './styles';

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
    try {
      await api(`/api/crm/deals/${deal.id}`, {
        method: 'PUT', body: JSON.stringify({ stage }),
      });
      setSelectedDeal(null);
      reload();
    } catch (err) {
      console.error('Failed to update deal stage:', err);
    }
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

  if (!data) return <p style={{ color: INK_MUTE, padding: 32 }}>Failed to load CRM dashboard.</p>;

  const activePipeline = data.pipeline_by_stage
    .filter(s => s.stage !== 'won' && s.stage !== 'lost')
    .sort((a, b) => STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage));
  const totalPipelineValue = `$${formatNumber(data.total_pipeline_value)}`;
  const totalDeals = activePipeline.reduce((s, p) => s + p.count, 0);

  const px = isMobile ? '20px' : '44px';

  return (
    <div style={{ position: 'relative', overflow: 'auto', height: '100%' }}>
      <WarmHalo opacity={0.3} />

      {/* Hero */}
      <div style={{ padding: isMobile ? '24px 20px 20px' : '36px 44px 28px', position: 'relative', zIndex: 2 }}>
        <div style={mono(10, INK_DIM)}>
          Week of {new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </div>
        <h1 style={{
          fontFamily: FONT_DISPLAY,
          fontSize: isMobile ? 30 : 48, fontWeight: 400, letterSpacing: '-0.02em',
          lineHeight: 1.1, margin: '10px 0 0', color: INK,
        }}>
          Pipeline is <span style={{ color: GOLD, fontStyle: 'italic' }}>{totalPipelineValue}</span>
          <br /><span style={{ color: INK_MUTE, fontSize: isMobile ? 16 : 26 }}>across {totalDeals} open deals.</span>
        </h1>
      </div>

      {/* Stage rows */}
      <div style={{ padding: `0 ${px} 28px`, position: 'relative', zIndex: 2 }}>
        <div style={{ borderTop: `1px solid ${LINE}` }}>
          {activePipeline.length === 0 ? (
            <p style={{ color: INK_DIM, fontSize: 13, padding: '16px 0' }}>No active deals yet.</p>
          ) : (
            activePipeline.map(stage => {
              const pct = data.total_pipeline_value > 0 ? (stage.total_value / data.total_pipeline_value) * 100 : 0;
              return (
                <div key={stage.stage} onClick={() => navigate(`/crm/pipeline?stage=${stage.stage}`)} style={{
                  padding: '16px 0', borderBottom: `1px solid ${LINE}`,
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
                            background: STAGE_COLORS[stage.stage]?.color || INK_DIM,
                          }} />
                          <span style={{
                            fontFamily: FONT_DISPLAY,
                            fontSize: 16, letterSpacing: '-0.01em',
                            textTransform: 'capitalize', color: INK,
                          }}>{stage.stage}</span>
                        </div>
                        <div style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
                          <span style={{
                            fontFamily: FONT_DISPLAY,
                            fontSize: 16, color: INK,
                          }}>${formatNumber(stage.total_value)}</span>
                          <span style={{ ...mono(10, INK_MUTE) }}>{stage.count} deals</span>
                        </div>
                      </div>
                      <div style={{ height: 2, background: LINE, position: 'relative' }}>
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
                          background: STAGE_COLORS[stage.stage]?.color || INK_DIM,
                        }} />
                        <span style={{
                          fontFamily: FONT_DISPLAY,
                          fontSize: 20, letterSpacing: '-0.01em',
                          textTransform: 'capitalize', color: INK,
                        }}>{stage.stage}</span>
                      </div>
                      <div style={{ height: 2, background: LINE, position: 'relative' }}>
                        <div style={{
                          position: 'absolute', inset: 0,
                          right: `${100 - Math.max(pct, 2)}%`,
                          background: STAGE_COLORS[stage.stage]?.color || 'var(--color-ch-accent, #C8D1D9)',
                        }} />
                      </div>
                      <div style={{
                        fontFamily: FONT_DISPLAY,
                        fontSize: 22, fontWeight: 400, textAlign: 'right',
                        letterSpacing: '-0.01em', color: INK,
                      }}>${formatNumber(stage.total_value)}</div>
                      <div style={{
                        ...mono(11, INK_MUTE),
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
          <div style={sectionHeading(INK_SOFT)}>Top deals</div>
          <div style={{ borderTop: `1px solid ${LINE}` }}>
            {data.top_deals.length === 0 ? (
              <p style={{ color: INK_DIM, fontSize: 15, padding: '16px 0' }}>No deals yet.</p>
            ) : (
              data.top_deals.map(deal => (
                <div key={deal.id} onClick={() => setSelectedDeal(deal)} style={{
                  padding: '14px 16px', marginBottom: 6,
                  display: 'flex', alignItems: 'center', gap: 14,
                  cursor: 'pointer',
                  background: STAGE_COLORS[deal.stage]?.bg || 'rgba(20,24,30,0.78)',
                  border: `1px solid ${LINE}`,
                  borderLeft: `3px solid ${STAGE_COLORS[deal.stage]?.color || 'rgba(230,235,242,0.14)'}`,
                  borderRadius: 6,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 16, letterSpacing: '-0.005em', color: INK }}>
                      {deal.title}
                      {!isMobile && <span style={{ color: INK_MUTE }}> · {deal.contact_name || 'No contact'}</span>}
                    </div>
                    <div style={{
                      ...mono(11, STAGE_COLORS[deal.stage]?.color || INK_DIM),
                      marginTop: 3, textTransform: 'uppercase',
                    }}>{deal.stage}{isMobile && deal.contact_name ? ` · ${deal.contact_name}` : ''}</div>
                  </div>
                  <div style={{
                    fontFamily: FONT_DISPLAY,
                    fontSize: isMobile ? 17 : 20, letterSpacing: '-0.01em', color: INK,
                    flexShrink: 0,
                  }}>${formatNumber(deal.value)}</div>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div style={sectionHeading(INK_SOFT)}>Recent activity</div>
          <div style={{ borderTop: `1px solid ${LINE}` }}>
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
              ...btnSecondary,
              padding: '9px 16px', fontSize: 14,
            }}
          >{a.label}</button>
        ))}
      </div>

      {editDeal && <DealForm deal={editDeal} onClose={() => setEditDeal(null)} onSaved={() => { setEditDeal(null); setSelectedDeal(null); reload(); }} />}

      {selectedDeal && (
        <DealDetailSheet
          deal={selectedDeal}
          isMobile={isMobile}
          onClose={() => setSelectedDeal(null)}
          onEdit={setEditDeal}
          onStageChange={updateDealStage}
        />
      )}
    </div>
  );
}
