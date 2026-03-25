import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { CrmDeal } from '../core/types';
import { DealForm } from './components/DealForm';

const STAGES = ['lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost'];

const STAGE_COLORS: Record<string, string> = {
  lead: 'bg-gray-600 text-gray-200',
  qualified: 'bg-blue-600 text-blue-100',
  proposal: 'bg-yellow-600 text-yellow-100',
  negotiation: 'bg-orange-600 text-orange-100',
  won: 'bg-green-600 text-green-100',
  lost: 'bg-red-600 text-red-100',
};

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
      <div className="flex justify-center py-20">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
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
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Pipeline</h1>
          {data && (
            <p className="text-gray-400 text-sm mt-1">
              ${formatNumber(data.total_pipeline_value)} total &middot; {deals.filter(d => !['won', 'lost'].includes(d.stage)).length} open deals
            </p>
          )}
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-brand text-white font-medium px-4 py-2 rounded-lg text-sm hover:opacity-90 transition"
        >
          + Add Deal
        </button>
      </div>

      {/* Stage filter */}
      <div className="flex gap-1 mb-6 bg-gray-800 rounded-lg border border-gray-700 p-1 inline-flex">
        <button
          onClick={() => setStageFilter('')}
          className={`px-3 py-1.5 rounded text-xs font-medium transition ${!stageFilter ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
        >
          All
        </button>
        {STAGES.map(stage => (
          <button
            key={stage}
            onClick={() => setStageFilter(stage === stageFilter ? '' : stage)}
            className={`px-3 py-1.5 rounded text-xs font-medium capitalize transition ${stageFilter === stage ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
          >
            {stage} ({grouped[stage]?.length || 0})
          </button>
        ))}
      </div>

      {/* Grouped deal table */}
      {filteredStages.map(stage => {
        const stageDeals = grouped[stage] || [];
        if (stageDeals.length === 0 && stageFilter) return null;

        return (
          <div key={stage} className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-xs px-2 py-0.5 rounded capitalize font-medium ${STAGE_COLORS[stage]}`}>
                {stage}
              </span>
              <span className="text-gray-500 text-xs">
                {stageDeals.length} deal{stageDeals.length !== 1 ? 's' : ''} &middot;
                ${formatNumber(stageDeals.reduce((s, d) => s + d.value, 0))}
              </span>
            </div>

            {stageDeals.length === 0 ? (
              <p className="text-gray-600 text-xs ml-2 mb-4">No deals</p>
            ) : (
              <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden mb-2">
                <table className="w-full">
                  <thead>
                    <tr className="text-xs text-gray-500 uppercase tracking-wide border-b border-gray-800">
                      <th className="text-left px-4 py-2">Deal</th>
                      <th className="text-left px-4 py-2">Contact</th>
                      <th className="text-right px-4 py-2">Value</th>
                      <th className="text-right px-4 py-2">Probability</th>
                      <th className="text-left px-4 py-2">Close Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stageDeals.map(deal => (
                      <tr
                        key={deal.id}
                        onClick={() => setEditDeal(deal)}
                        className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition"
                      >
                        <td className="px-4 py-2.5 text-white text-sm">{deal.title}</td>
                        <td className="px-4 py-2.5 text-gray-400 text-sm">{deal.contact_name || '—'}</td>
                        <td className="px-4 py-2.5 text-white text-sm text-right font-medium">
                          ${deal.value.toLocaleString()}
                        </td>
                        <td className="px-4 py-2.5 text-gray-400 text-sm text-right">
                          {deal.probability > 0 ? `${deal.probability}%` : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-gray-400 text-sm">{deal.expected_close_date || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
