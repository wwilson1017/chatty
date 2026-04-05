import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { Integration } from '../core/types';

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

  useEffect(() => {
    api<{ integrations: Integration[] }>('/api/integrations')
      .then(data => setIntegrations(data.integrations))
      .finally(() => setLoading(false));
  }, []);

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

  async function setupQuickBooks() {
    setSaving(true); setError('');
    try {
      await api('/api/integrations/quickbooks/setup', { method: 'POST' });
      const data = await api<{ integrations: Integration[] }>('/api/integrations');
      setIntegrations(data.integrations);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Setup failed'); }
    finally { setSaving(false); }
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

  async function reconnectQuickBooks() {
    await disconnectQuickBooks();
    await setupQuickBooks();
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
              {integration.auth_type !== 'stub' && (
                <>
                  {/* Broken connection — show reconnect */}
                  {integration.configured && integration.connection_status === 'broken' && (
                    <>
                      <span className="text-xs text-red-400 bg-red-900/20 px-2 py-1 rounded">Connection lost</span>
                      <button
                        onClick={reconnectQuickBooks}
                        disabled={saving}
                        className="text-xs px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-500 transition disabled:opacity-50"
                      >
                        Reconnect
                      </button>
                    </>
                  )}

                  {/* Not configured — show setup */}
                  {!integration.configured && (
                    <button
                      onClick={() => {
                        if (integration.id === 'crm_lite') setupCRMLite();
                        else if (integration.id === 'quickbooks') setupQuickBooks();
                        else { setSetupFor(integration.id); setError(''); }
                      }}
                      disabled={saving}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50"
                    >
                      {saving && integration.id === 'quickbooks' ? 'Connecting...' : 'Setup'}
                    </button>
                  )}

                  {/* Configured and healthy — show toggle + disconnect for OAuth */}
                  {integration.configured && integration.connection_status !== 'broken' && (
                    <>
                      <button
                        onClick={() => toggleEnable(integration.id, integration.enabled)}
                        className={`relative w-11 h-6 rounded-full transition ${integration.enabled ? 'bg-brand' : 'bg-gray-600'}`}
                      >
                        <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${integration.enabled ? 'left-5' : 'left-0.5'}`} />
                      </button>
                      {integration.auth_type === 'oauth2' && (
                        <button
                          onClick={disconnectQuickBooks}
                          disabled={saving}
                          className="text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-gray-700 transition disabled:opacity-50"
                        >
                          Disconnect
                        </button>
                      )}
                    </>
                  )}
                </>
              )}
              {integration.auth_type === 'stub' && (
                <span className="text-xs text-gray-500 bg-gray-700/50 px-2 py-1 rounded">Coming soon</span>
              )}
            </div>
          </div>

          {/* QuickBooks error display */}
          {error && integration.id === 'quickbooks' && !setupFor && (
            <p className="mt-2 text-red-400 text-xs">{error}</p>
          )}

          {/* Setup forms */}
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
