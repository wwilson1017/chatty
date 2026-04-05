import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../core/api/client';
import { getToken } from '../core/auth/AuthContext';
import type { Integration, Agent } from '../core/types';

export function IntegrationsTab() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [setupFor, setSetupFor] = useState<string | null>(null);

  // Setup form state
  const [odooUrl, setOdooUrl] = useState('');
  const [odooDb, setOdooDb] = useState('');
  const [odooUser, setOdooUser] = useState('');
  const [odooKey, setOdooKey] = useState('');
  const [bambooSubdomain, setBambooSubdomain] = useState('');
  const [bambooKey, setBambooKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // WhatsApp state
  const [agents, setAgents] = useState<Agent[]>([]);
  const [waSelectedAgent, setWaSelectedAgent] = useState<string>('');
  const [waConnecting, setWaConnecting] = useState<Record<string, boolean>>({});
  const [waQrUrls, setWaQrUrls] = useState<Record<string, string>>({});
  const [waStatuses, setWaStatuses] = useState<Record<string, string>>({});
  const [waErrors, setWaErrors] = useState<Record<string, string>>({});
  const [waExpanded, setWaExpanded] = useState(false);
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    api<{ integrations: Integration[] }>('/api/integrations')
      .then(data => setIntegrations(data.integrations))
      .finally(() => setLoading(false));
  }, []);

  // Load agents when WhatsApp panel is expanded
  useEffect(() => {
    if (waExpanded) {
      api<{ agents: Agent[] }>('/api/agents')
        .then(data => {
          setAgents(data.agents);
          // Initialize statuses for agents with active sessions
          const statuses: Record<string, string> = {};
          for (const a of data.agents) {
            if (a.whatsapp_session_id) {
              statuses[a.slug] = 'checking...';
              // Fetch actual status
              api<{ status: string }>(`/api/messaging/whatsapp/session/status/${a.slug}`)
                .then(s => setWaStatuses(prev => ({ ...prev, [a.slug]: s.status })))
                .catch(() => setWaStatuses(prev => ({ ...prev, [a.slug]: 'unknown' })));
            }
          }
          setWaStatuses(statuses);
        });
    }
  }, [waExpanded]);

  // Cleanup poll timers on unmount
  useEffect(() => {
    return () => {
      Object.values(pollTimers.current).forEach(clearInterval);
    };
  }, []);

  const startQrPolling = useCallback((slug: string) => {
    // Clear existing timer for this slug
    if (pollTimers.current[slug]) clearInterval(pollTimers.current[slug]);

    pollTimers.current[slug] = setInterval(async () => {
      try {
        // Check status
        const status = await api<{ status: string }>(`/api/messaging/whatsapp/session/status/${slug}`);
        setWaStatuses(prev => ({ ...prev, [slug]: status.status }));

        if (status.status === 'connected') {
          // Connected! Stop polling, refresh agents
          clearInterval(pollTimers.current[slug]);
          delete pollTimers.current[slug];
          setWaConnecting(prev => ({ ...prev, [slug]: false }));
          setWaQrUrls(prev => { const n = { ...prev }; delete n[slug]; return n; });
          // Refresh agent list to get updated whatsapp_session_id
          const data = await api<{ agents: Agent[] }>('/api/agents');
          setAgents(data.agents);
          return;
        }

        if (status.status === 'scan_qr') {
          // Fetch QR code as binary
          const token = getToken();
          const resp = await fetch(`/api/messaging/whatsapp/session/qr/${slug}`, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
          });
          if (resp.ok) {
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            setWaQrUrls(prev => {
              // Revoke old URL to prevent memory leak
              if (prev[slug]) URL.revokeObjectURL(prev[slug]);
              return { ...prev, [slug]: url };
            });
          }
        }
      } catch {
        // Ignore polling errors
      }
    }, 3000);
  }, []);

  async function connectWhatsApp(slug: string) {
    setWaConnecting(prev => ({ ...prev, [slug]: true }));
    setWaErrors(prev => { const n = { ...prev }; delete n[slug]; return n; });
    try {
      await api('/api/messaging/whatsapp/session', {
        method: 'POST',
        body: JSON.stringify({ agent_slug: slug }),
      });
      setWaStatuses(prev => ({ ...prev, [slug]: 'scan_qr' }));
      startQrPolling(slug);
    } catch (err: unknown) {
      setWaConnecting(prev => ({ ...prev, [slug]: false }));
      setWaErrors(prev => ({
        ...prev,
        [slug]: err instanceof Error ? err.message : 'Connection failed',
      }));
    }
  }

  async function disconnectWhatsApp(slug: string) {
    try {
      await api(`/api/messaging/whatsapp/session/${slug}`, { method: 'DELETE' });
      if (pollTimers.current[slug]) {
        clearInterval(pollTimers.current[slug]);
        delete pollTimers.current[slug];
      }
      setWaConnecting(prev => ({ ...prev, [slug]: false }));
      setWaStatuses(prev => ({ ...prev, [slug]: 'disconnected' }));
      setWaQrUrls(prev => {
        if (prev[slug]) URL.revokeObjectURL(prev[slug]);
        const n = { ...prev }; delete n[slug]; return n;
      });
      // Refresh agents
      const data = await api<{ agents: Agent[] }>('/api/agents');
      setAgents(data.agents);
    } catch {
      // Ignore disconnect errors
    }
  }

  async function toggleEnable(id: string, enabled: boolean) {
    const endpoint = enabled ? 'disable' : 'enable';
    await api(`/api/integrations/${id}/${endpoint}`, { method: 'POST' });
    setIntegrations(prev => prev.map(i => i.id === id ? { ...i, enabled: !enabled } : i));
  }

  async function setupOdoo() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/odoo/setup', {
        method: 'POST',
        body: JSON.stringify({ url: odooUrl, database: odooDb, username: odooUser, api_key: odooKey }),
      });
      setSetupFor(null);
      const data = await api<{ integrations: Integration[] }>('/api/integrations');
      setIntegrations(data.integrations);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Setup failed'); }
    finally { setSaving(false); }
  }

  async function setupBambooHR() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/bamboohr/setup', {
        method: 'POST',
        body: JSON.stringify({ subdomain: bambooSubdomain, api_key: bambooKey }),
      });
      setSetupFor(null);
      const data = await api<{ integrations: Integration[] }>('/api/integrations');
      setIntegrations(data.integrations);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Setup failed'); }
    finally { setSaving(false); }
  }

  async function setupCRMLite() {
    await api('/api/integrations/crm_lite/setup', { method: 'POST' });
    const data = await api<{ integrations: Integration[] }>('/api/integrations');
    setIntegrations(data.integrations);
  }

  async function setupQbCsv() {
    await api('/api/integrations/qb_csv/setup', { method: 'POST' });
    const data = await api<{ integrations: Integration[] }>('/api/integrations');
    setIntegrations(data.integrations);
  }

  if (loading) return <div className="flex justify-center py-8"><div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div className="space-y-4">
      {integrations.map(integration => (
        <div key={integration.id} className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{integration.icon}</span>
              <div>
                <p className="text-white font-medium">{integration.name}</p>
                <p className="text-gray-400 text-xs mt-0.5">{integration.description}</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {integration.auth_type !== 'stub' && integration.auth_type !== 'qr_session' && (
                <>
                  {!integration.configured && (
                    <button
                      onClick={() => {
                        if (integration.id === 'crm_lite') setupCRMLite();
                        else if (integration.id === 'qb_csv') setupQbCsv();
                        else { setSetupFor(integration.id); setError(''); }
                      }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition"
                    >
                      Setup
                    </button>
                  )}
                  {integration.configured && (
                    <button
                      onClick={() => toggleEnable(integration.id, integration.enabled)}
                      className={`relative w-11 h-6 rounded-full transition ${integration.enabled ? 'bg-brand' : 'bg-gray-600'}`}
                    >
                      <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${integration.enabled ? 'left-5' : 'left-0.5'}`} />
                    </button>
                  )}
                </>
              )}
              {integration.auth_type === 'qr_session' && (
                <button
                  onClick={() => setWaExpanded(prev => !prev)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-green-700/30 text-green-300 hover:bg-green-700/50 transition"
                >
                  {waExpanded ? 'Close' : 'Manage'}
                </button>
              )}
              {integration.auth_type === 'stub' && (
                <span className="text-xs text-gray-500 bg-gray-700/50 px-2 py-1 rounded">Coming soon</span>
              )}
            </div>
          </div>

          {/* WhatsApp QR session panel */}
          {integration.auth_type === 'qr_session' && waExpanded && (
            <div className="mt-4 pt-4 border-t border-gray-700 space-y-4">
              {agents.length === 0 ? (
                <p className="text-gray-400 text-sm">No agents created yet. Create an agent first.</p>
              ) : (
                <>
                  {/* Agent selector */}
                  <div>
                    <label className="block text-gray-400 text-xs mb-1.5">Select agent to connect</label>
                    <select
                      value={waSelectedAgent}
                      onChange={e => setWaSelectedAgent(e.target.value)}
                      className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                    >
                      <option value="">Choose an agent...</option>
                      {agents.map(a => (
                        <option key={a.id} value={a.slug}>
                          {a.agent_name} {a.whatsapp_session_id ? '(connected)' : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Per-agent status when selected */}
                  {waSelectedAgent && (() => {
                    const agent = agents.find(a => a.slug === waSelectedAgent);
                    if (!agent) return null;
                    const slug = agent.slug;
                    const status = waStatuses[slug] || 'disconnected';
                    const isConnecting = waConnecting[slug];
                    const qrUrl = waQrUrls[slug];
                    const errMsg = waErrors[slug];

                    return (
                      <div className="bg-gray-900/50 rounded-lg p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-white text-sm font-medium">{agent.agent_name}</span>
                            <span className={`inline-block w-2 h-2 rounded-full ${
                              status === 'connected' ? 'bg-green-400' :
                              status === 'scan_qr' || status === 'connecting' ? 'bg-yellow-400 animate-pulse' :
                              'bg-gray-500'
                            }`} />
                            <span className="text-gray-400 text-xs capitalize">{status.replace('_', ' ')}</span>
                          </div>

                          {status === 'connected' && (
                            <button
                              onClick={() => disconnectWhatsApp(slug)}
                              className="text-xs px-3 py-1.5 rounded-lg bg-red-700/30 text-red-300 hover:bg-red-700/50 transition"
                            >
                              Disconnect
                            </button>
                          )}
                          {status === 'disconnected' && !isConnecting && (
                            <button
                              onClick={() => connectWhatsApp(slug)}
                              className="text-xs px-3 py-1.5 rounded-lg bg-green-700/30 text-green-300 hover:bg-green-700/50 transition"
                            >
                              Connect WhatsApp
                            </button>
                          )}
                        </div>

                        {errMsg && <p className="text-red-400 text-xs">{errMsg}</p>}

                        {/* QR Code display */}
                        {(isConnecting || status === 'scan_qr') && (
                          <div className="flex flex-col items-center gap-3 py-2">
                            {qrUrl ? (
                              <img src={qrUrl} alt="WhatsApp QR Code" className="w-48 h-48 rounded-lg bg-white p-2" />
                            ) : (
                              <div className="w-48 h-48 rounded-lg bg-gray-700 flex items-center justify-center">
                                <div className="w-6 h-6 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                              </div>
                            )}
                            <div className="text-center">
                              <p className="text-gray-300 text-sm">Scan with WhatsApp</p>
                              <p className="text-gray-500 text-xs mt-1">
                                Open WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device
                              </p>
                            </div>
                          </div>
                        )}

                        {status === 'connected' && (
                          <p className="text-green-400/80 text-xs">
                            Messages to this WhatsApp number will be handled by {agent.agent_name}.
                          </p>
                        )}
                      </div>
                    );
                  })()}

                  {/* Connected agents summary */}
                  {agents.filter(a => a.whatsapp_session_id).length > 0 && (
                    <div className="space-y-2">
                      <p className="text-gray-400 text-xs font-medium">Connected agents</p>
                      {agents.filter(a => a.whatsapp_session_id).map(a => (
                        <div key={a.id} className="flex items-center justify-between bg-gray-900/30 rounded-lg px-3 py-2">
                          <div className="flex items-center gap-2">
                            <span className="inline-block w-2 h-2 rounded-full bg-green-400" />
                            <span className="text-white text-sm">{a.agent_name}</span>
                          </div>
                          <button
                            onClick={() => { setWaSelectedAgent(a.slug); }}
                            className="text-xs text-gray-400 hover:text-white transition"
                          >
                            Manage
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Standard setup forms */}
          {setupFor === integration.id && (
            <div className="mt-4 pt-4 border-t border-gray-700 space-y-3">
              {error && <p className="text-red-400 text-xs">{error}</p>}

              {integration.id === 'odoo' && (
                <>
                  <input placeholder="Odoo URL (https://...)" value={odooUrl} onChange={e => setOdooUrl(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <input placeholder="Database name" value={odooDb} onChange={e => setOdooDb(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <input placeholder="Username / email" value={odooUser} onChange={e => setOdooUser(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <input placeholder="API key" value={odooKey} onChange={e => setOdooKey(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <div className="flex gap-2">
                    <button onClick={() => setSetupFor(null)} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition">Cancel</button>
                    <button onClick={setupOdoo} disabled={saving} className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50">{saving ? 'Connecting...' : 'Connect'}</button>
                  </div>
                </>
              )}

              {integration.id === 'bamboohr' && (
                <>
                  <input placeholder="Subdomain (company.bamboohr.com)" value={bambooSubdomain} onChange={e => setBambooSubdomain(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <input placeholder="API key" value={bambooKey} onChange={e => setBambooKey(e.target.value)} className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500" />
                  <div className="flex gap-2">
                    <button onClick={() => setSetupFor(null)} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition">Cancel</button>
                    <button onClick={setupBambooHR} disabled={saving} className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50">{saving ? 'Connecting...' : 'Connect'}</button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
