import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDeal } from '../core/types';
import { DealForm } from './components/DealForm';
import { DealDetailSheet } from './components/DealDetailSheet';
import { STAGE_COLORS, STAGE_ORDER } from './constants';
import { IconPlus } from '../shared/icons';
import { useIsMobile } from '../shared/useIsMobile';
import {
  INK, INK_MUTE, INK_DIM, LINE, BG_CARD,
  FONT_DISPLAY, mono, formatNumber,
} from '../shared/styles';
import {
  pageHeading, filterBar, filterTab, tableHeader, tableRow,
  btnPrimary, stageCard,
} from './styles';

const STAGES = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

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
    try {
      await api(`/api/crm/deals/${deal.id}`, {
        method: 'PUT', body: JSON.stringify({ stage }),
      });
      setSelectedDeal(null);
      load();
    } catch (err) {
      console.error('Failed to update deal stage:', err);
    }
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
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <div>
          <h1 style={pageHeading(isMobile)}>Pipeline</h1>
          {data && (
            <p style={{ fontSize: isMobile ? 14 : 20, color: INK_MUTE, marginTop: 6 }}>
              ${formatNumber(data.total_pipeline_value)} total · {deals.filter(d => !['won', 'lost'].includes(d.stage)).length} open deals
            </p>
          )}
        </div>
        <button onClick={() => setShowCreate(true)} style={{
          ...btnPrimary,
          padding: '7px 14px', fontSize: 13,
          flexShrink: 0, marginTop: 8,
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'Add' : 'Add Deal'}
        </button>
      </div>

      {/* Stage filter */}
      <div style={filterBar(isMobile)}>
        {[{ stage: '', label: 'All' }, ...STAGE_ORDER.map(s => ({ stage: s, label: s }))].map(({ stage, label }) => {
          const isActive = stageFilter === stage;
          const stageColor = stage ? (STAGE_COLORS[stage]?.color || INK_DIM) : undefined;
          return (
            <button key={label} onClick={() => setStageFilter(stage === stageFilter ? '' : stage)} style={filterTab(isMobile, isActive, stageColor)}>
              <span style={{ color: isActive ? (stageColor || INK) : INK_MUTE }}>{label}</span>
              {stage && (
                <span style={{ marginLeft: 6, fontSize: 12, color: isActive ? INK_MUTE : INK_DIM }}>
                  {grouped[stage]?.length || 0}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Grouped deals */}
      {filteredStages.map(stage => {
        const stageDeals = grouped[stage] || [];
        if (stageDeals.length === 0 && stageFilter) return null;

        const stageBg = STAGE_COLORS[stage]?.bg || BG_CARD;
        const stageColor = STAGE_COLORS[stage]?.color || INK_DIM;

        return (
          <div key={stage} style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                background: stageColor,
              }} />
              <span style={{
                fontFamily: FONT_DISPLAY,
                fontSize: isMobile ? 16 : 18, letterSpacing: '-0.01em', textTransform: 'capitalize',
                color: INK,
              }}>{stage}</span>
              <span style={{ ...mono(10, INK_DIM) }}>
                {stageDeals.length} deal{stageDeals.length !== 1 ? 's' : ''} · ${formatNumber(stageDeals.reduce((s, d) => s + d.value, 0))}
              </span>
            </div>

            {stageDeals.length === 0 ? (
              <p style={{ color: INK_DIM, fontSize: 12, marginLeft: 8, marginBottom: 16 }}>No deals</p>
            ) : isMobile ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8 }}>
                {stageDeals.map(deal => (
                  <div key={deal.id} onClick={() => setSelectedDeal(deal)}
                    style={{
                      padding: '12px 14px', cursor: 'pointer',
                      ...stageCard(stageBg, stageColor),
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                      <span style={{ fontSize: 14, color: INK }}>{deal.title}</span>
                      <span style={{
                        fontFamily: FONT_DISPLAY,
                        fontSize: 15, color: INK, flexShrink: 0, marginLeft: 8,
                      }}>${deal.value.toLocaleString()}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 12, fontSize: 12, color: INK_DIM }}>
                      {deal.contact_name && <span>{deal.contact_name}</span>}
                      {deal.probability > 0 && <span>{deal.probability}%</span>}
                      {deal.expected_close_date && <span>{deal.expected_close_date}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ borderTop: `1px solid ${LINE}`, marginBottom: 8 }}>
                <div style={tableHeader('2fr 1.5fr 1fr 80px 1fr')}>
                  <span>Deal</span><span>Contact</span><span style={{ textAlign: 'right' }}>Value</span>
                  <span style={{ textAlign: 'right' }}>Prob.</span><span>Close Date</span>
                </div>
                {stageDeals.map(deal => (
                  <div key={deal.id} onClick={() => setSelectedDeal(deal)}
                    style={{
                      ...tableRow('2fr 1.5fr 1fr 80px 1fr'),
                      borderLeft: `3px solid ${stageColor}`,
                    }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = stageBg; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                  >
                    <span style={{ fontSize: 14, color: INK }}>{deal.title}</span>
                    <span style={{ fontSize: 13, color: INK_MUTE }}>{deal.contact_name || '—'}</span>
                    <span style={{
                      fontFamily: FONT_DISPLAY,
                      fontSize: 15, color: INK, textAlign: 'right',
                    }}>${deal.value.toLocaleString()}</span>
                    <span style={{ fontSize: 13, color: INK_DIM, textAlign: 'right' }}>
                      {deal.probability > 0 ? `${deal.probability}%` : '—'}
                    </span>
                    <span style={{ fontSize: 13, color: INK_DIM }}>{deal.expected_close_date || '—'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {showCreate && <DealForm onClose={() => setShowCreate(false)} onSaved={() => { setShowCreate(false); load(); }} />}
      {editDeal && <DealForm deal={editDeal} onClose={() => setEditDeal(null)} onSaved={() => { setEditDeal(null); setSelectedDeal(null); load(); }} />}

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
