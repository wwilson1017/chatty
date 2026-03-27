import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { AgentCard } from './AgentCard';
import { CreateAgentModal } from './CreateAgentModal';
import { SettingsPanel } from './SettingsPanel';
import type { Agent, BrandingConfig, Integration } from '../core/types';

export function DashboardPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [loading, setLoading] = useState(true);
  const [crmEnabled, setCrmEnabled] = useState(false);
  const navigate = useNavigate();
  const setupChecked = useRef(false);

  // Check if setup wizard should be shown (first login)
  useEffect(() => {
    if (setupChecked.current) return;
    setupChecked.current = true;
    api<{ setup_complete: boolean }>('/api/setup/status')
      .then(s => {
        if (!s.setup_complete) navigate('/setup', { replace: true });
      })
      .catch(() => {}); // if endpoint fails, just show dashboard
  }, [navigate]);

  useEffect(() => {
    Promise.all([
      api<{ agents: Agent[] }>('/api/agents'),
      api<BrandingConfig>('/api/branding'),
      api<{ integrations: Integration[] }>('/api/integrations'),
    ]).then(([agentsData, brandingData, intData]) => {
      setAgents(agentsData.agents);
      setBranding(brandingData);
      setCrmEnabled(intData.integrations.some(i => i.id === 'crm_lite' && i.enabled));
      // Apply brand color
      if (brandingData.accent_color) {
        document.documentElement.style.setProperty('--brand-color', brandingData.accent_color);
      }
    }).finally(() => setLoading(false));
  }, []);

  async function handleDelete(id: string) {
    if (!confirm('Delete this agent? This cannot be undone.')) return;
    await api(`/api/agents/${id}`, { method: 'DELETE' });
    setAgents(prev => prev.filter(a => a.id !== id));
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {branding?.has_logo && (
            <img src="/api/branding/logo" alt="Logo" className="h-8 w-auto" />
          )}
          <span className="text-white font-semibold text-lg">
            {branding?.company_name || 'Chatty'}
          </span>
        </div>

        <button
          onClick={() => setShowSettings(true)}
          className="text-gray-400 hover:text-white transition p-2 rounded-lg hover:bg-gray-800"
          title="Settings"
        >
          ⚙️
        </button>
      </header>

      {/* Main */}
      <main className="max-w-6xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Your Agents</h1>
            <p className="text-gray-400 mt-1">Create and manage your AI agents</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="bg-brand text-white font-semibold px-5 py-2.5 rounded-xl hover:opacity-90 transition flex items-center gap-2"
          >
            <span className="text-lg">+</span>
            New Agent
          </button>
        </div>

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-6xl mb-4">🤖</div>
            <p className="text-gray-400 text-lg mb-6">No agents yet. Create your first one!</p>
            <button
              onClick={() => setShowCreate(true)}
              className="bg-brand text-white font-semibold px-6 py-3 rounded-xl hover:opacity-90 transition"
            >
              Create Agent
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {agents.map(agent => (
              <AgentCard key={agent.id} agent={agent} onDelete={handleDelete} />
            ))}
          </div>
        )}

        {/* CRM Card */}
        {!loading && (
          <div className="mt-10">
            {crmEnabled ? (
              <button
                onClick={() => navigate('/crm')}
                className="w-full bg-gray-900 border border-gray-800 rounded-2xl p-5 text-left hover:border-gray-700 transition group"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-white font-semibold">CRM</h3>
                    <p className="text-gray-400 text-sm mt-0.5">Manage contacts, deals, tasks, and pipeline</p>
                  </div>
                  <span className="text-gray-500 group-hover:text-gray-300 transition">&rarr;</span>
                </div>
              </button>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-white font-semibold">CRM</h3>
                    <p className="text-gray-400 text-sm mt-0.5">Lightweight CRM for contacts, deals, and pipeline tracking</p>
                  </div>
                  <button
                    onClick={async () => {
                      await api('/api/integrations/crm_lite/setup', { method: 'POST' });
                      setCrmEnabled(true);
                    }}
                    className="bg-brand text-white text-sm font-medium px-4 py-2 rounded-lg hover:opacity-90 transition"
                  >
                    Setup CRM
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {showCreate && (
        <CreateAgentModal
          onClose={() => setShowCreate(false)}
          onCreated={agent => {
            setAgents(prev => [...prev, agent]);
            setShowCreate(false);
          }}
        />
      )}

      {showSettings && (
        <SettingsPanel
          branding={branding}
          onBrandingUpdate={setBranding}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
