import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDeal } from '../core/types';
import { DealForm } from './components/DealForm';
import { IconPlus } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';

const STAGES = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

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

interface PipelineData {
  deals: CrmDeal[];
  stage_summary: { stage: string; count: number; total_value: number }[];
  total_pipeline_value: number;
}

export function PipelinePage() {
  const [data, setData] = useState<PipelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editDeal, setEditDeal] = useState<CrmDeal | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [stageFilter, setStageFilter] = useState<string>(() => {
    const s = searchParams.get('stage');
    return s && STAGES.includes(s) ? s : '';
  });
  const [selectedDeal, setSelectedDeal] = useState<CrmDeal | null>(null);
  const isMobile = useIsMobile();

  useEffect(() => {
    const s = searchParams.get('stage');
    if (s && STAGES.includes(s)) {
      queueMicrotask(() => setStageFilter(s));
      searchParams.delete('stage');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    const d = await api<PipelineData>('/api/crm/deals');
    setData(d);
    setLoading(false);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  async function updateDealStage(deal: CrmDeal, stage: string) {
    await api(`/api/crm/deals/${deal.id}`, {
      method: 'PUT', body: JSON.stringify({ stage }),
    });
    setSelectedDeal(null);
    load();
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '80px 0' }}>
        <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const deals = data?.deals || [];
  const grouped = STAGES.reduce<Record<string, CrmDeal[]>>((acc, stage) => {
    acc[stage] = deals.filter(d => d.stage === stage);
    return acc;
  }, {});

  const filteredStages = stageFilter ? [stageFilter] : STAGES;

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <div>
          <h1 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: isMobile ? 24 : 32, fontWeight: 400, letterSpacing: '-0.02em',
            color: '#EDF0F4', margin: 0,
          }}>Pipeline</h1>
          {data && (
            <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', marginTop: 4 }}>
              ${formatNumber(data.total_pipeline_value)} total · {deals.filter(d => !['won', 'lost'].includes(d.stage)).length} open deals
            </p>
          )}
        </div>
        <button onClick={() => setShowCreate(true)} style={{
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', padding: '7px 14px', borderRadius: 4,
          fontSize: 13, fontWeight: 500, cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
          flexShrink: 0,
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Deal'}
        </button>
      </div>

      {/* Stage filter */}
      <div style={{
        display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 4, overflow: 'hidden', marginBottom: isMobile ? 16 : 24,
        overflowX: isMobile ? 'auto' : undefined,
        WebkitOverflowScrolling: 'touch' as const,
      }}>
        <button onClick={() => setStageFilter('')} style={{
          padding: isMobile ? '6px 10px' : '6px 14px', fontSize: 11, fontWeight: 500,
          color: !stageFilter ? '#0E1013' : 'rgba(237,240,244,0.62)',
          background: !stageFilter ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
          border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
        }}>All</button>
        {STAGES.map(stage => (
          <button key={stage} onClick={() => setStageFilter(stage === stageFilter ? '' : stage)} style={{
            padding: isMobile ? '6px 10px' : '6px 14px', fontSize: 11, fontWeight: 500, textTransform: 'capitalize',
            color: stageFilter === stage ? '#0E1013' : 'rgba(237,240,244,0.62)',
            background: stageFilter === stage ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
            border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
          }}>
            {stage} ({grouped[stage]?.length || 0})
          </button>
        ))}
      </div>

      {/* Grouped deals */}
      {filteredStages.map(stage => {
        const stageDeals = grouped[stage] || [];
        if (stageDeals.length === 0 && stageFilter) return null;

        return (
          <div key={stage} style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                background: STAGE_COLORS[stage]?.color || 'rgba(237,240,244,0.38)',
              }} />
              <span style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: isMobile ? 16 : 18, letterSpacing: '-0.01em', textTransform: 'capitalize',
                color: '#EDF0F4',
              }}>{stage}</span>
              <span style={{ ...mono(9, 'rgba(237,240,244,0.38)') }}>
                {stageDeals.length} deal{stageDeals.length !== 1 ? 's' : ''} · ${formatNumber(stageDeals.reduce((s, d) => s + d.value, 0))}
              </span>
            </div>

            {stageDeals.length === 0 ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, marginLeft: 8, marginBottom: 16 }}>No deals</p>
            ) : isMobile ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8 }}>
                {stageDeals.map(deal => (
                  <div key={deal.id} onClick={() => setSelectedDeal(deal)}
                    style={{
                      padding: '12px 14px', cursor: 'pointer',
                      background: STAGE_COLORS[stage]?.bg || 'rgba(20,24,30,0.78)',
                      border: '1px solid rgba(230,235,242,0.07)',
                      borderLeft: `3px solid ${STAGE_COLORS[stage]?.color || 'rgba(230,235,242,0.14)'}`,
                      borderRadius: 6,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                      <span style={{ fontSize: 14, color: '#EDF0F4' }}>{deal.title}</span>
                      <span style={{
                        fontFamily: "'Fraunces', Georgia, serif",
                        fontSize: 15, color: '#EDF0F4', flexShrink: 0, marginLeft: 8,
                      }}>${deal.value.toLocaleString()}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 12, fontSize: 12, color: 'rgba(237,240,244,0.38)' }}>
                      {deal.contact_name && <span>{deal.contact_name}</span>}
                      {deal.probability > 0 && <span>{deal.probability}%</span>}
                      {deal.expected_close_date && <span>{deal.expected_close_date}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)', marginBottom: 8 }}>
                <div style={{
                  display: 'grid', gridTemplateColumns: '2fr 1.5fr 1fr 80px 1fr',
                  gap: 16, padding: '8px 16px',
                  borderBottom: '1px solid rgba(230,235,242,0.07)',
                  ...mono(9),
                }}>
                  <span>Deal</span><span>Contact</span><span style={{ textAlign: 'right' }}>Value</span>
                  <span style={{ textAlign: 'right' }}>Prob.</span><span>Close Date</span>
                </div>
                {stageDeals.map(deal => (
                  <div key={deal.id} onClick={() => setSelectedDeal(deal)}
                    style={{
                      display: 'grid', gridTemplateColumns: '2fr 1.5fr 1fr 80px 1fr',
                      gap: 16, padding: '10px 16px', cursor: 'pointer',
                      borderBottom: '1px solid rgba(230,235,242,0.07)',
                      borderLeft: `3px solid ${STAGE_COLORS[stage]?.color || 'rgba(230,235,242,0.14)'}`,
                    }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = STAGE_COLORS[stage]?.bg || 'rgba(200,209,217,0.04)'; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                  >
                    <span style={{ fontSize: 14, color: '#EDF0F4' }}>{deal.title}</span>
                    <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)' }}>{deal.contact_name || '—'}</span>
                    <span style={{
                      fontFamily: "'Fraunces', Georgia, serif",
                      fontSize: 15, color: '#EDF0F4', textAlign: 'right',
                    }}>${deal.value.toLocaleString()}</span>
                    <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.38)', textAlign: 'right' }}>
                      {deal.probability > 0 ? `${deal.probability}%` : '—'}
                    </span>
                    <span style={{ fontSize: 13, color: 'rgba(237,240,244,0.38)' }}>{deal.expected_close_date || '—'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {showCreate && <DealForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {editDeal && <DealForm deal={editDeal} onClose={() => setEditDeal(null)} onSaved={() => { setEditDeal(null); setSelectedDeal(null); load(); }} />}

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
