import { useState } from 'react';
import { api } from '../../core/api/client';

interface Props {
  onComplete: () => void;
  onSkip: () => void;
}

export function OdooSetupStep({ onComplete, onSkip }: Props) {
  const [url, setUrl] = useState('');
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [discoveredDbs, setDiscoveredDbs] = useState<string[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryMethod, setDiscoveryMethod] = useState('');
  const [manualMode, setManualMode] = useState(false);

  async function discoverDatabases() {
    if (!url.trim()) return;
    setDiscovering(true);
    setError('');
    setDiscoveredDbs([]);
    setDiscoveryMethod('');
    try {
      const result = await api<{
        databases: string[];
        method: string | null;
        error: string | null;
      }>('/api/integrations/odoo/discover-databases', {
        method: 'POST',
        body: JSON.stringify({ url }),
      });
      if (result.databases.length > 0) {
        setDiscoveredDbs(result.databases);
        setDiscoveryMethod(result.method || '');
        setManualMode(false);
        if (result.databases.length === 1) {
          setDatabase(result.databases[0]);
        }
      } else {
        setError(result.error || 'No databases found. Please enter the name manually.');
      }
    } catch {
      setError('Could not reach the Odoo instance. Check the URL and try again.');
    } finally {
      setDiscovering(false);
    }
  }

  async function connect() {
    setSaving(true);
    setError('');
    try {
      await api('/api/integrations/odoo/setup', {
        method: 'POST',
        body: JSON.stringify({ url, database, username, api_key: apiKey }),
      });
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setSaving(false);
    }
  }

  const isValid = url.trim() && database.trim() && username.trim() && apiKey.trim();
  const showDropdown = discoveredDbs.length > 0 && !manualMode;

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">Connect Odoo</h2>
      <p className="text-gray-400 text-sm mb-6">
        Connect your Odoo ERP to give your agents access to inventory, sales, accounting, and more.
      </p>

      <div className="space-y-4 mb-6">
        {/* URL */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Odoo URL</label>
          <input
            value={url}
            onChange={e => {
              setUrl(e.target.value);
              if (discoveredDbs.length > 0) {
                setDiscoveredDbs([]);
                setDiscoveryMethod('');
                setDatabase('');
                setManualMode(false);
              }
            }}
            placeholder="https://mycompany.odoo.com"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-amber-500"
          />
          <div className="flex items-center justify-between mt-1.5">
            <p className="text-gray-500 text-xs">Your Odoo instance URL</p>
            <button
              onClick={discoverDatabases}
              disabled={discovering || !url.trim()}
              className="text-amber-400 text-xs hover:text-amber-300 transition disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {discovering ? 'Searching...' : 'Find my database'}
            </button>
          </div>
        </div>

        {/* Database */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Database Name</label>
          {showDropdown ? (
            <>
              <select
                value={database}
                onChange={e => setDatabase(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-amber-500 appearance-none"
              >
                <option value="">Select a database...</option>
                {discoveredDbs.map(db => (
                  <option key={db} value={db}>{db}</option>
                ))}
              </select>
              <div className="flex items-center justify-between mt-1.5">
                <p className="text-gray-500 text-xs">
                  {discoveredDbs.length === 1 ? 'Database found' : `${discoveredDbs.length} databases found`}
                  {discoveryMethod === 'url_inference' && ' (inferred from URL)'}
                </p>
                <button
                  onClick={() => setManualMode(true)}
                  className="text-gray-500 text-xs hover:text-gray-400 transition"
                >
                  Type manually
                </button>
              </div>
            </>
          ) : (
            <>
              <input
                value={database}
                onChange={e => setDatabase(e.target.value)}
                placeholder="mycompany-main"
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-amber-500"
              />
              {discoveredDbs.length > 0 && manualMode && (
                <div className="flex items-center justify-between mt-1.5">
                  <p className="text-gray-500 text-xs">Enter your database name</p>
                  <button
                    onClick={() => setManualMode(false)}
                    className="text-gray-500 text-xs hover:text-gray-400 transition"
                  >
                    Use discovered databases
                  </button>
                </div>
              )}
              {discoveredDbs.length === 0 && !manualMode && (
                <p className="text-gray-500 text-xs mt-1.5">
                  Use "Find my database" above, or enter the name manually
                </p>
              )}
            </>
          )}
        </div>

        {/* Username */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Username / Email</label>
          <input
            value={username}
            onChange={e => setUsername(e.target.value)}
            placeholder="admin@mycompany.com"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-amber-500"
          />
          <p className="text-gray-500 text-xs mt-1">The email you use to log into Odoo</p>
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder="Your Odoo API key"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-amber-500"
          />
          <p className="text-gray-500 text-xs mt-1">Settings &rarr; Users &rarr; your profile &rarr; API Keys tab</p>
        </div>
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-900/20 rounded-lg px-4 py-3 mb-4">{error}</div>
      )}

      <div className="flex gap-3">
        <button
          onClick={onSkip}
          className="flex-1 py-3 rounded-xl border border-gray-700 text-gray-400 hover:bg-gray-800 transition font-medium"
        >
          Skip
        </button>
        <button
          onClick={connect}
          disabled={saving || !isValid}
          className="flex-1 py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {saving ? 'Connecting...' : 'Connect Odoo'}
        </button>
      </div>
    </div>
  );
}
