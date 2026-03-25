import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import type { CrmDashboard } from '../core/types';
import { ActivityTimeline } from './components/ActivityTimeline';

const STAGE_COLORS: Record<string, string> = {
  lead: 'bg-gray-500',
  qualified: 'bg-blue-500',
  proposal: 'bg-yellow-500',
  negotiation: 'bg-orange-500',
  won: 'bg-green-500',
  lost: 'bg-red-500',
};

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
      <div className="flex justify-center py-20">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) return <p className="text-gray-400 p-8">Failed to load CRM dashboard.</p>;

  const activePipeline = data.pipeline_by_stage.filter(s => s.stage !== 'won' && s.stage !== 'lost');

  return (
    <div className="p-8 max-w-5xl">
      <h1 className="text-2xl font-bold text-white mb-8">CRM Dashboard</h1>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total Contacts"
          value={data.total_contacts.toString()}
          sub={`${data.contacts_by_status.active || 0} active`}
        />
        <StatCard
          label="Pipeline Value"
          value={`$${formatNumber(data.total_pipeline_value)}`}
          sub={`${activePipeline.reduce((s, p) => s + p.count, 0)} open deals`}
        />
        <StatCard
          label="Pending Tasks"
          value={data.pending_tasks.toString()}
          sub={data.overdue_tasks > 0 ? `${data.overdue_tasks} overdue` : 'None overdue'}
          alert={data.overdue_tasks > 0}
        />
        <StatCard
          label="Won Deals"
          value={(data.pipeline_by_stage.find(s => s.stage === 'won')?.count || 0).toString()}
          sub={`$${formatNumber(data.pipeline_by_stage.find(s => s.stage === 'won')?.total_value || 0)}`}
        />
      </div>

      {/* Pipeline breakdown */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6 mb-8">
        <h2 className="text-white font-semibold mb-4">Pipeline by Stage</h2>
        {activePipeline.length === 0 ? (
          <p className="text-gray-500 text-sm">No active deals yet.</p>
        ) : (
          <div className="space-y-3">
            {activePipeline.map(stage => {
              const pct = data.total_pipeline_value > 0
                ? (stage.total_value / data.total_pipeline_value) * 100
                : 0;
              return (
                <div key={stage.stage} className="flex items-center gap-3">
                  <span className="text-gray-400 text-sm w-24 capitalize">{stage.stage}</span>
                  <div className="flex-1 bg-gray-800 rounded-full h-5 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${STAGE_COLORS[stage.stage] || 'bg-indigo-500'}`}
                      style={{ width: `${Math.max(pct, 2)}%` }}
                    />
                  </div>
                  <span className="text-white text-sm w-28 text-right">
                    {stage.count} &middot; ${formatNumber(stage.total_value)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Top deals */}
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-white font-semibold">Top Deals</h2>
            <button
              onClick={() => navigate('/crm/pipeline')}
              className="text-indigo-400 text-xs hover:text-indigo-300"
            >
              View all
            </button>
          </div>
          {data.top_deals.length === 0 ? (
            <p className="text-gray-500 text-sm">No deals yet.</p>
          ) : (
            <div className="space-y-3">
              {data.top_deals.map(deal => (
                <div key={deal.id} className="flex items-center justify-between">
                  <div>
                    <p className="text-white text-sm">{deal.title}</p>
                    <p className="text-gray-500 text-xs">{deal.contact_name || 'No contact'}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-white text-sm font-medium">${formatNumber(deal.value)}</p>
                    <span className={`text-xs px-1.5 py-0.5 rounded capitalize ${STAGE_COLORS[deal.stage]?.replace('bg-', 'bg-') || 'bg-gray-700'} text-white`}>
                      {deal.stage}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent activity */}
        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6">
          <h2 className="text-white font-semibold mb-4">Recent Activity</h2>
          <ActivityTimeline activities={data.recent_activity} />
        </div>
      </div>

      {/* Quick actions */}
      <div className="flex gap-3 mt-8">
        <button
          onClick={() => navigate('/crm/contacts')}
          className="bg-gray-800 text-white px-4 py-2 rounded-lg text-sm hover:bg-gray-700 transition"
        >
          + Add Contact
        </button>
        <button
          onClick={() => navigate('/crm/pipeline')}
          className="bg-gray-800 text-white px-4 py-2 rounded-lg text-sm hover:bg-gray-700 transition"
        >
          + Add Deal
        </button>
        <button
          onClick={() => navigate('/crm/tasks')}
          className="bg-gray-800 text-white px-4 py-2 rounded-lg text-sm hover:bg-gray-700 transition"
        >
          + Add Task
        </button>
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, alert }: { label: string; value: string; sub: string; alert?: boolean }) {
  return (
    <div className="bg-gray-900 rounded-2xl border border-gray-800 p-5">
      <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
      <p className="text-white text-2xl font-bold mt-1">{value}</p>
      <p className={`text-xs mt-1 ${alert ? 'text-red-400' : 'text-gray-500'}`}>{sub}</p>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K';
  return n.toLocaleString();
}
