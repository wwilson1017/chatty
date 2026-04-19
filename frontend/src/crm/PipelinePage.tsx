import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { CrmDeal } from '../core/types';
import { DealForm } from './components/DealForm';
import { IconPlus } from '../shared/icons';

const STAGES = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

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
  const [stageFilter, setStageFilter] = useState<string>('');

  async function load() {
    setLoading(true);
    const d = await api<PipelineData>('/api/crm/deals');
    setData(d);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

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
    <div style={{ padding: '32px 44px', maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 32, fontWeight: 400, letterSpacing: '-0.02em',
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
        }}>
          <IconPlus size={13} strokeWidth={2.25} /> Add Deal
        </button>
      </div>

      {/* Stage filter */}
      <div style={{
        display: 'inline-flex', border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 4, overflow: 'hidden', marginBottom: 24,
      }}>
        <button onClick={() => setStageFilter('')} style={{
          padding: '6px 14px', fontSize: 11, fontWeight: 500,
          color: !stageFilter ? '#0E1013' : 'rgba(237,240,244,0.62)',
          background: !stageFilter ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
          border: 'none', cursor: 'pointer',
        }}>All</button>
        {STAGES.map(stage => (
          <button key={stage} onClick={() => setStageFilter(stage === stageFilter ? '' : stage)} style={{
            padding: '6px 14px', fontSize: 11, fontWeight: 500, textTransform: 'capitalize',
            color: stageFilter === stage ? '#0E1013' : 'rgba(237,240,244,0.62)',
            background: stageFilter === stage ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
            border: 'none', cursor: 'pointer',
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
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 18, letterSpacing: '-0.01em', textTransform: 'capitalize',
                color: '#EDF0F4',
              }}>{stage}</span>
              <span style={{ ...mono(9, 'rgba(237,240,244,0.38)') }}>
                {stageDeals.length} deal{stageDeals.length !== 1 ? 's' : ''} · ${formatNumber(stageDeals.reduce((s, d) => s + d.value, 0))}
              </span>
            </div>

            {stageDeals.length === 0 ? (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, marginLeft: 8, marginBottom: 16 }}>No deals</p>
            ) : (
              <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)', marginBottom: 8 }}>
                {/* Header */}
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
                  <div key={deal.id} onClick={() => setEditDeal(deal)}
                    style={{
                      display: 'grid', gridTemplateColumns: '2fr 1.5fr 1fr 80px 1fr',
                      gap: 16, padding: '10px 16px', cursor: 'pointer',
                      borderBottom: '1px solid rgba(230,235,242,0.07)',
                    }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
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
      {editDeal && <DealForm deal={editDeal} onClose={() => setEditDeal(null)} onSaved={() => { setEditDeal(null); load(); }} />}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K';
  return n.toLocaleString();
}
