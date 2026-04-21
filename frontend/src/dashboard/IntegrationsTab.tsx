import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../core/api/client';
import { getToken } from '../core/auth/tokenUtils';
import { useOAuthFlow } from '../core/hooks/useOAuthFlow';
import { GoogleIntegrationCard } from './GoogleIntegrationCard';
import type { Integration, Agent } from '../core/types';
import { IconGlobe, IconUsers, IconFunnel, IconFile, IconPhone, IconMail, IconChart, IconBook, IconZap } from '../shared/icons';
import { TelegramSettings } from '../agent/components/TelegramSettings';

const INTEGRATION_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string; strokeWidth?: number }>> = {
  quickbooks: IconChart,
  qb_csv: IconFile,
  odoo: IconGlobe,
  bamboohr: IconUsers,
  crm_lite: IconFunnel,
  hubspot: IconZap,
  salesforce: IconGlobe,
  whatsapp: IconPhone,
  telegram: IconMail,
  gmail: IconMail,
  calendar: IconBook,
};

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function IntegrationsTab() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [setupFor, setSetupFor] = useState<string | null>(null);

  const [odooUrl, setOdooUrl] = useState('');
  const [odooDb, setOdooDb] = useState('');
  const [odooUser, setOdooUser] = useState('');
  const [odooKey, setOdooKey] = useState('');
  const [odooDiscoveredDbs, setOdooDiscoveredDbs] = useState<string[]>([]);
  const [odooDiscovering, setOdooDiscovering] = useState(false);
  const [odooDiscoveryMethod, setOdooDiscoveryMethod] = useState('');
  const [odooManualMode, setOdooManualMode] = useState(false);
  const [bambooSubdomain, setBambooSubdomain] = useState('');
  const [bambooKey, setBambooKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [agents, setAgents] = useState<Agent[]>([]);
  const [waSelectedAgent, setWaSelectedAgent] = useState<string>('');
  const [waConnecting, setWaConnecting] = useState<Record<string, boolean>>({});
  const [waQrUrls, setWaQrUrls] = useState<Record<string, string>>({});
  const [waStatuses, setWaStatuses] = useState<Record<string, string>>({});
  const [waErrors, setWaErrors] = useState<Record<string, string>>({});
  const [waExpanded, setWaExpanded] = useState(false);
  const [telegramExpanded, setTelegramExpanded] = useState(false);
  const [tgSelectedAgent, setTgSelectedAgent] = useState<string>('');
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    api<{ integrations: Integration[] }>('/api/integrations')
      .then(data => setIntegrations(data.integrations))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (waExpanded || telegramExpanded) {
      api<{ agents: Agent[] }>('/api/agents').then(data => {
        setAgents(data.agents);
        if (waExpanded) {
          const statuses: Record<string, string> = {};
          for (const a of data.agents) {
            if (a.whatsapp_session_id) {
              statuses[a.slug] = 'checking...';
              api<{ status: string }>(`/api/messaging/whatsapp/session/status/${a.slug}`)
                .then(s => setWaStatuses(prev => ({ ...prev, [a.slug]: s.status })))
                .catch(() => setWaStatuses(prev => ({ ...prev, [a.slug]: 'unknown' })));
            }
          }
          setWaStatuses(statuses);
        }
      });
    }
  }, [waExpanded, telegramExpanded]);

  useEffect(() => {
    const timers = pollTimers.current;
    return () => { Object.values(timers).forEach(clearInterval); };
  }, []);

  const startQrPolling = useCallback((slug: string) => {
    if (pollTimers.current[slug]) clearInterval(pollTimers.current[slug]);
    pollTimers.current[slug] = setInterval(async () => {
      try {
        const status = await api<{ status: string }>(`/api/messaging/whatsapp/session/status/${slug}`);
        setWaStatuses(prev => ({ ...prev, [slug]: status.status }));
        if (status.status === 'connected') {
          clearInterval(pollTimers.current[slug]);
          delete pollTimers.current[slug];
          setWaConnecting(prev => ({ ...prev, [slug]: false }));
          setWaQrUrls(prev => { const n = { ...prev }; delete n[slug]; return n; });
          const data = await api<{ agents: Agent[] }>('/api/agents');
          setAgents(data.agents);
          return;
        }
        if (status.status === 'scan_qr') {
          const token = getToken();
          const resp = await fetch(`/api/messaging/whatsapp/session/qr/${slug}`, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {},
          });
          if (resp.ok) {
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            setWaQrUrls(prev => { if (prev[slug]) URL.revokeObjectURL(prev[slug]); return { ...prev, [slug]: url }; });
          }
        }
      } catch { /* ignore */ }
    }, 3000);
  }, []);

  async function connectWhatsApp(slug: string) {
    setWaConnecting(prev => ({ ...prev, [slug]: true }));
    setWaErrors(prev => { const n = { ...prev }; delete n[slug]; return n; });
    try {
      await api('/api/messaging/whatsapp/session', { method: 'POST', body: JSON.stringify({ agent_slug: slug }) });
      setWaStatuses(prev => ({ ...prev, [slug]: 'scan_qr' }));
      startQrPolling(slug);
    } catch (err: unknown) {
      setWaConnecting(prev => ({ ...prev, [slug]: false }));
      setWaErrors(prev => ({ ...prev, [slug]: err instanceof Error ? err.message : 'Connection failed' }));
    }
  }

  async function disconnectWhatsApp(slug: string) {
    try {
      await api(`/api/messaging/whatsapp/session/${slug}`, { method: 'DELETE' });
      if (pollTimers.current[slug]) { clearInterval(pollTimers.current[slug]); delete pollTimers.current[slug]; }
      setWaConnecting(prev => ({ ...prev, [slug]: false }));
      setWaStatuses(prev => ({ ...prev, [slug]: 'disconnected' }));
      setWaQrUrls(prev => { if (prev[slug]) URL.revokeObjectURL(prev[slug]); const n = { ...prev }; delete n[slug]; return n; });
      const data = await api<{ agents: Agent[] }>('/api/agents');
      setAgents(data.agents);
    } catch { /* ignore */ }
  }

  async function toggleEnable(id: string, enabled: boolean) {
    const endpoint = enabled ? 'disable' : 'enable';
    await api(`/api/integrations/${id}/${endpoint}`, { method: 'POST' });
    setIntegrations(prev => prev.map(i => i.id === id ? { ...i, enabled: !enabled } : i));
  }

  async function setToolMode(id: string, mode: string) {
    const prev = integrations.find(i => i.id === id)?.tool_mode || 'normal';
    setIntegrations(ps => ps.map(i => i.id === id ? { ...i, tool_mode: mode } : i));
    try {
      await api(`/api/integrations/${id}/tool-mode`, { method: 'POST', body: JSON.stringify({ tool_mode: mode }) });
    } catch {
      setIntegrations(ps => ps.map(i => i.id === id ? { ...i, tool_mode: prev } : i));
    }
  }

  async function setupOdoo() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/odoo/setup', { method: 'POST', body: JSON.stringify({ url: odooUrl, database: odooDb, username: odooUser, api_key: odooKey }) });
      setSetupFor(null);
      const data = await api<{ integrations: Integration[] }>('/api/integrations');
      setIntegrations(data.integrations);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Setup failed'); }
    finally { setSaving(false); }
  }

  async function discoverOdooDatabases() {
    if (!odooUrl.trim()) return;
    setOdooDiscovering(true); setError('');
    setOdooDiscoveredDbs([]); setOdooDiscoveryMethod('');
    try {
      const result = await api<{ databases: string[]; method: string | null; error: string | null }>('/api/integrations/odoo/discover-databases', {
        method: 'POST', body: JSON.stringify({ url: odooUrl }),
      });
      if (result.databases.length > 0) {
        setOdooDiscoveredDbs(result.databases);
        setOdooDiscoveryMethod(result.method || '');
        setOdooManualMode(false);
        if (result.databases.length === 1) setOdooDb(result.databases[0]);
      } else {
        setError(result.error || 'No databases found. Enter the name manually.');
      }
    } catch { setError('Could not reach the Odoo instance. Check the URL and try again.'); }
    finally { setOdooDiscovering(false); }
  }

  async function setupBambooHR() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/bamboohr/setup', { method: 'POST', body: JSON.stringify({ subdomain: bambooSubdomain, api_key: bambooKey }) });
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

  const qbOAuth = useOAuthFlow();

  useEffect(() => {
    if (qbOAuth.state.status === 'success') {
      api<{ integrations: Integration[] }>('/api/integrations').then(d => setIntegrations(d.integrations));
      qbOAuth.reset();
    } else if (qbOAuth.state.status === 'error' && qbOAuth.state.error) {
      setError(qbOAuth.state.error);
    }
  }, [qbOAuth.state.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function setupQuickBooks() {
    setError('');
    await qbOAuth.start({
      setupUrl: '/api/integrations/quickbooks/setup',
      completeUrl: '/api/integrations/quickbooks/setup/complete',
    });
  }

  async function disconnectQuickBooks() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/quickbooks/disconnect', { method: 'POST' });
      const data = await api<{ integrations: Integration[] }>('/api/integrations');
      setIntegrations(data.integrations);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Disconnect failed'); }
    finally { setSaving(false); }
  }

  async function reconnectQuickBooks() { await disconnectQuickBooks(); await setupQuickBooks(); }

  const qbConnecting = qbOAuth.state.status === 'starting' ||
                        qbOAuth.state.status === 'awaiting_user' ||
                        qbOAuth.state.status === 'completing';

  async function setupQbCsv() {
    await api('/api/integrations/qb_csv/setup', { method: 'POST' });
    const data = await api<{ integrations: Integration[] }>('/api/integrations');
    setIntegrations(data.integrations);
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box',
    background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
    color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13, outline: 'none',
    fontFamily: "'Inter Tight', system-ui, sans-serif",
  };

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '32px 0' }}>
      <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  async function refreshIntegrations() {
    const data = await api<{ integrations: Integration[] }>('/api/integrations');
    setIntegrations(data.integrations);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {integrations.map(integration => {
        if (integration.id === 'google') {
          return (
            <GoogleIntegrationCard
              key={integration.id}
              integration={integration}
              onChanged={refreshIntegrations}
            />
          );
        }
        const Icon = INTEGRATION_ICONS[integration.id] || IconGlobe;
        return (
          <div key={integration.id} style={{
            background: 'rgba(20,24,30,0.78)', borderRadius: 6, padding: 16,
            border: '1px solid rgba(230,235,242,0.07)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 4,
                  background: 'rgba(245,239,227,0.06)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'rgba(237,240,244,0.62)',
                }}>
                  <Icon size={16} strokeWidth={1.75} />
                </div>
                <div>
                  <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>{integration.name}</p>
                  <p style={{ fontSize: 11, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>{integration.description}</p>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {integration.auth_type !== 'stub' && integration.auth_type !== 'qr_session' && integration.auth_type !== 'per_agent' && (() => {
                  const isConfigured = integration.configured;
                  const isBroken = isConfigured && integration.connection_status === 'broken';
                  const isHealthy = isConfigured && !isBroken;

                  return (
                    <>
                      {/* Broken state for QuickBooks */}
                      {isBroken && integration.id === 'quickbooks' && (
                        <>
                          <span style={{ fontSize: 11, color: '#D97757', background: 'rgba(217,119,87,0.08)', padding: '2px 8px', borderRadius: 4 }}>Connection lost</span>
                          <button onClick={reconnectQuickBooks} disabled={saving} style={{
                            fontSize: 11, padding: '4px 12px', borderRadius: 4,
                            background: 'transparent', color: '#D97757', border: '1px solid rgba(217,119,87,0.25)', cursor: 'pointer',
                            opacity: saving ? 0.5 : 1,
                          }}>Reconnect</button>
                        </>
                      )}

                      {/* Setup button — only when not configured */}
                      {!isConfigured && (
                        <button onClick={() => {
                          if (integration.id === 'crm_lite') setupCRMLite();
                          else if (integration.id === 'quickbooks') setupQuickBooks();
                          else if (integration.id === 'qb_csv') setupQbCsv();
                          else { setSetupFor(integration.id); setError(''); }
                        }} disabled={saving || (integration.id === 'quickbooks' && qbConnecting)} style={{
                          fontSize: 11, padding: '4px 12px', borderRadius: 4,
                          background: 'transparent', color: 'rgba(237,240,244,0.62)',
                          border: '1px solid rgba(230,235,242,0.14)', cursor: 'pointer',
                          opacity: saving ? 0.5 : 1,
                        }}>
                          {integration.id === 'quickbooks' && qbConnecting ? 'Connecting...' : 'Setup'}
                        </button>
                      )}

                      {/* Toggle — always visible, dimmed when not configured */}
                      {!isBroken && (
                        <button
                          onClick={() => isHealthy && toggleEnable(integration.id, integration.enabled)}
                          style={{
                            position: 'relative', width: 44, height: 24, borderRadius: 12,
                            background: !isConfigured
                              ? 'rgba(230,235,242,0.06)'
                              : integration.enabled
                                ? 'var(--color-ch-accent, #C8D1D9)'
                                : 'rgba(230,235,242,0.14)',
                            border: 'none',
                            cursor: isHealthy ? 'pointer' : 'default',
                            opacity: isConfigured ? 1 : 0.4,
                            transition: 'background 0.2s, opacity 0.2s',
                          }}
                        >
                          <span style={{
                            position: 'absolute', top: 2, width: 20, height: 20,
                            borderRadius: '50%',
                            background: isConfigured ? '#fff' : 'rgba(255,255,255,0.4)',
                            boxShadow: isConfigured ? '0 1px 3px rgba(0,0,0,0.3)' : 'none',
                            left: (isHealthy && integration.enabled) ? 22 : 2,
                            transition: 'left 0.2s',
                          }} />
                        </button>
                      )}

                      {/* Disconnect for OAuth */}
                      {isHealthy && integration.auth_type === 'oauth2' && integration.id === 'quickbooks' && (
                        <button onClick={disconnectQuickBooks} disabled={saving} style={{
                          fontSize: 11, padding: '4px 8px', borderRadius: 4,
                          background: 'transparent', color: 'rgba(237,240,244,0.38)',
                          border: 'none', cursor: 'pointer',
                        }}>Disconnect</button>
                      )}
                    </>
                  );
                })()}
                {integration.auth_type === 'qr_session' && (
                  <button onClick={() => setWaExpanded(prev => !prev)} style={{
                    fontSize: 11, padding: '4px 12px', borderRadius: 4,
                    background: 'rgba(142,165,137,0.1)', color: '#8EA589',
                    border: '1px solid rgba(142,165,137,0.2)', cursor: 'pointer',
                  }}>{waExpanded ? 'Close' : 'Manage'}</button>
                )}
                {integration.auth_type === 'per_agent' && (
                  <button onClick={() => setTelegramExpanded(prev => !prev)} style={{
                    fontSize: 11, padding: '4px 12px', borderRadius: 4,
                    background: 'rgba(0,136,204,0.1)', color: '#0088cc',
                    border: '1px solid rgba(0,136,204,0.2)', cursor: 'pointer',
                  }}>{telegramExpanded ? 'Close' : 'Manage'}</button>
                )}
                {integration.auth_type === 'stub' && (
                  <span style={{ ...mono(9, 'rgba(237,240,244,0.38)') }}>Coming soon</span>
                )}
              </div>
            </div>

            {/* Permission level selector for Odoo and QuickBooks */}
            {(integration.id === 'odoo' || integration.id === 'quickbooks') && integration.enabled && integration.configured && integration.connection_status !== 'broken' && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ ...mono(9), whiteSpace: 'nowrap' }}>Permissions</span>
                <div style={{
                  display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
                  borderRadius: 3, overflow: 'hidden',
                }}>
                  {([
                    { key: 'read-only', label: 'Read' },
                    { key: 'normal', label: 'Approval' },
                    { key: 'power', label: 'Full Control' },
                  ] as const).map(m => (
                    <div
                      key={m.key}
                      onClick={() => setToolMode(integration.id, m.key)}
                      style={{
                        padding: '3px 10px',
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
                        color: (integration.tool_mode || 'normal') === m.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
                        background: (integration.tool_mode || 'normal') === m.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
                        cursor: 'pointer',
                        transition: 'background 0.15s, color 0.15s',
                      }}
                    >
                      {m.label}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {error && integration.id === 'quickbooks' && !setupFor && (
              <p style={{ marginTop: 8, color: '#D97757', fontSize: 12 }}>{error}</p>
            )}

            {/* WhatsApp panel */}
            {integration.auth_type === 'qr_session' && waExpanded && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
                {agents.length === 0 ? (
                  <p style={{ color: 'rgba(237,240,244,0.62)', fontSize: 13 }}>No agents created yet.</p>
                ) : (
                  <>
                    <div style={{ marginBottom: 12 }}>
                      <label style={{ display: 'block', ...mono(9), marginBottom: 4 }}>Select agent</label>
                      <select value={waSelectedAgent} onChange={e => setWaSelectedAgent(e.target.value)}
                        style={{ ...inputStyle }}>
                        <option value="">Choose an agent...</option>
                        {agents.map(a => (
                          <option key={a.id} value={a.slug}>
                            {a.agent_name} {a.whatsapp_session_id ? '(connected)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>

                    {waSelectedAgent && (() => {
                      const agent = agents.find(a => a.slug === waSelectedAgent);
                      if (!agent) return null;
                      const slug = agent.slug;
                      const st = waStatuses[slug] || 'disconnected';
                      const isConnecting = waConnecting[slug];
                      const qrUrl = waQrUrls[slug];
                      const errMsg = waErrors[slug];

                      return (
                        <div style={{ background: 'rgba(34,40,48,0.55)', borderRadius: 6, padding: 16 }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontSize: 14, color: '#EDF0F4' }}>{agent.agent_name}</span>
                              <span style={{
                                width: 6, height: 6, borderRadius: '50%',
                                background: st === 'connected' ? '#8EA589' : st === 'scan_qr' || st === 'connecting' ? '#D4A85A' : 'rgba(237,240,244,0.38)',
                                animation: (st === 'scan_qr' || st === 'connecting') ? 'pulse 2s infinite' : 'none',
                              }} />
                              <span style={{ ...mono(9, 'rgba(237,240,244,0.62)'), textTransform: 'capitalize' }}>{st.replace('_', ' ')}</span>
                            </div>
                            {st === 'connected' && (
                              <button onClick={() => disconnectWhatsApp(slug)} style={{
                                fontSize: 11, padding: '4px 12px', borderRadius: 4,
                                background: 'rgba(217,119,87,0.1)', color: '#D97757',
                                border: '1px solid rgba(217,119,87,0.2)', cursor: 'pointer',
                              }}>Disconnect</button>
                            )}
                            {st === 'disconnected' && !isConnecting && (
                              <button onClick={() => connectWhatsApp(slug)} style={{
                                fontSize: 11, padding: '4px 12px', borderRadius: 4,
                                background: 'rgba(142,165,137,0.1)', color: '#8EA589',
                                border: '1px solid rgba(142,165,137,0.2)', cursor: 'pointer',
                              }}>Connect WhatsApp</button>
                            )}
                          </div>
                          {errMsg && <p style={{ color: '#D97757', fontSize: 12, marginBottom: 8 }}>{errMsg}</p>}
                          {(isConnecting || st === 'scan_qr') && (
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '8px 0' }}>
                              {qrUrl ? (
                                <img src={qrUrl} alt="WhatsApp QR" style={{ width: 192, height: 192, borderRadius: 6, background: '#fff', padding: 8 }} />
                              ) : (
                                <div style={{ width: 192, height: 192, borderRadius: 6, background: 'rgba(34,40,48,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                  <div className="w-6 h-6 border-2 border-ch-sage border-t-transparent rounded-full animate-spin" />
                                </div>
                              )}
                              <div style={{ textAlign: 'center' }}>
                                <p style={{ fontSize: 13, color: '#EDF0F4' }}>Scan with WhatsApp</p>
                                <p style={{ fontSize: 11, color: 'rgba(237,240,244,0.38)', marginTop: 4 }}>
                                  Open WhatsApp &rarr; Settings &rarr; Linked Devices &rarr; Link a Device
                                </p>
                              </div>
                            </div>
                          )}
                          {st === 'connected' && (
                            <p style={{ fontSize: 12, color: '#8EA589' }}>
                              Messages to this WhatsApp number will be handled by {agent.agent_name}.
                            </p>
                          )}
                        </div>
                      );
                    })()}

                    {agents.filter(a => a.whatsapp_session_id).length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <p style={{ ...mono(9), marginBottom: 8 }}>Connected agents</p>
                        {agents.filter(a => a.whatsapp_session_id).map(a => (
                          <div key={a.id} style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            background: 'rgba(34,40,48,0.3)', borderRadius: 4, padding: '8px 12px', marginBottom: 4,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8EA589' }} />
                              <span style={{ fontSize: 13, color: '#EDF0F4' }}>{a.agent_name}</span>
                            </div>
                            <button onClick={() => setWaSelectedAgent(a.slug)} style={{
                              fontSize: 11, color: 'rgba(237,240,244,0.62)', background: 'none', border: 'none', cursor: 'pointer',
                            }}>Manage</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Telegram per-agent panel */}
            {integration.auth_type === 'per_agent' && telegramExpanded && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
                {agents.length === 0 ? (
                  <p style={{ color: 'rgba(237,240,244,0.62)', fontSize: 13 }}>No agents created yet.</p>
                ) : (
                  <>
                    <div style={{ marginBottom: 12 }}>
                      <label style={{ display: 'block', ...mono(9), marginBottom: 4 }}>Select agent</label>
                      <select value={tgSelectedAgent} onChange={e => setTgSelectedAgent(e.target.value)} style={{ ...inputStyle }}>
                        <option value="">Choose an agent...</option>
                        {agents.map(a => (
                          <option key={a.id} value={a.id}>
                            {a.agent_name} {a.telegram_bot_token ? '(connected)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    {tgSelectedAgent && (() => {
                      const agent = agents.find(a => a.id === tgSelectedAgent);
                      if (!agent) return null;
                      return (
                        <TelegramSettings
                          agentId={agent.id}
                          agentName={agent.agent_name}
                          botToken={agent.telegram_bot_token || ''}
                          botUsername={agent.telegram_bot_username || ''}
                          telegramEnabled={agent.telegram_enabled}
                          groupEnabled={agent.telegram_group_enabled}
                          respondToBots={agent.telegram_respond_to_bots}
                          maxBotTurns={agent.telegram_max_bot_turns ?? 3}
                          onUpdate={() => api<{ agents: Agent[] }>('/api/agents').then(data => setAgents(data.agents))}
                        />
                      );
                    })()}
                  </>
                )}
              </div>
            )}

            {/* Setup forms */}
            {setupFor === integration.id && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(230,235,242,0.07)', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
                {integration.id === 'odoo' && (
                  <>
                    <input placeholder="Odoo URL (https://...)" value={odooUrl} onChange={e => {
                      setOdooUrl(e.target.value);
                      if (odooDiscoveredDbs.length > 0) {
                        setOdooDiscoveredDbs([]); setOdooDiscoveryMethod(''); setOdooDb(''); setOdooManualMode(false);
                      }
                    }} style={inputStyle} />
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 2 }}>
                      <button onClick={discoverOdooDatabases} disabled={odooDiscovering || !odooUrl.trim()} style={{ background: 'none', border: 'none', color: 'var(--color-ch-accent, #C8D1D9)', fontSize: 11, cursor: 'pointer', padding: 0, opacity: odooDiscovering || !odooUrl.trim() ? 0.3 : 1 }}>
                        {odooDiscovering ? 'Searching...' : 'Find my database'}
                      </button>
                    </div>
                    {odooDiscoveredDbs.length > 0 && !odooManualMode ? (
                      <>
                        <select value={odooDb} onChange={e => setOdooDb(e.target.value)} style={{ ...inputStyle }}>
                          <option value="">Select a database...</option>
                          {odooDiscoveredDbs.map(db => <option key={db} value={db}>{db}</option>)}
                        </select>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: 'rgba(237,240,244,0.38)', fontSize: 11 }}>
                            {odooDiscoveredDbs.length === 1 ? 'Database found' : `${odooDiscoveredDbs.length} databases found`}
                            {odooDiscoveryMethod === 'url_inference' && ' (inferred from URL)'}
                          </span>
                          <button onClick={() => setOdooManualMode(true)} style={{ background: 'none', border: 'none', color: 'rgba(237,240,244,0.38)', fontSize: 11, cursor: 'pointer', padding: 0 }}>Type manually</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <input placeholder="Database name" value={odooDb} onChange={e => setOdooDb(e.target.value)} style={inputStyle} />
                        {odooDiscoveredDbs.length > 0 && odooManualMode && (
                          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                            <button onClick={() => setOdooManualMode(false)} style={{ background: 'none', border: 'none', color: 'rgba(237,240,244,0.38)', fontSize: 11, cursor: 'pointer', padding: 0 }}>Use discovered databases</button>
                          </div>
                        )}
                      </>
                    )}
                    <input placeholder="Username / email" value={odooUser} onChange={e => setOdooUser(e.target.value)} style={inputStyle} />
                    <input placeholder="API key" type="password" value={odooKey} onChange={e => setOdooKey(e.target.value)} style={inputStyle} />
                    <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                      <button onClick={() => setSetupFor(null)} style={{ flex: 1, padding: '8px 16px', fontSize: 13, borderRadius: 4, border: '1px solid rgba(230,235,242,0.14)', background: 'transparent', color: 'rgba(237,240,244,0.62)', cursor: 'pointer' }}>Cancel</button>
                      <button onClick={setupOdoo} disabled={saving} style={{ flex: 1, padding: '8px 16px', fontSize: 13, borderRadius: 4, background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013', border: 'none', cursor: 'pointer', fontWeight: 500, opacity: saving ? 0.5 : 1 }}>{saving ? 'Connecting...' : 'Connect'}</button>
                    </div>
                  </>
                )}
                {integration.id === 'bamboohr' && (
                  <>
                    <input placeholder="Subdomain (company.bamboohr.com)" value={bambooSubdomain} onChange={e => setBambooSubdomain(e.target.value)} style={inputStyle} />
                    <input placeholder="API key" value={bambooKey} onChange={e => setBambooKey(e.target.value)} style={inputStyle} />
                    <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                      <button onClick={() => setSetupFor(null)} style={{ flex: 1, padding: '8px 16px', fontSize: 13, borderRadius: 4, border: '1px solid rgba(230,235,242,0.14)', background: 'transparent', color: 'rgba(237,240,244,0.62)', cursor: 'pointer' }}>Cancel</button>
                      <button onClick={setupBambooHR} disabled={saving} style={{ flex: 1, padding: '8px 16px', fontSize: 13, borderRadius: 4, background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013', border: 'none', cursor: 'pointer', fontWeight: 500, opacity: saving ? 0.5 : 1 }}>{saving ? 'Connecting...' : 'Connect'}</button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
