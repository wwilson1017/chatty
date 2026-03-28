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
            onChange={e => setUrl(e.target.value)}
            placeholder="https://mycompany.odoo.com"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          <p className="text-gray-500 text-xs mt-1">Your Odoo instance URL</p>
        </div>

        {/* Database */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Database Name</label>
          <input
            value={database}
            onChange={e => setDatabase(e.target.value)}
            placeholder="mycompany-main"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          <div className="bg-gray-900 border border-dashed border-gray-700 rounded-lg p-3 mt-2 text-center">
            <p className="text-gray-500 text-xs">Screenshot: Odoo Settings &rarr; Database Name (coming soon)</p>
          </div>
        </div>

        {/* Username */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Username / Email</label>
          <input
            value={username}
            onChange={e => setUsername(e.target.value)}
            placeholder="admin@mycompany.com"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
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
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          <div className="bg-gray-900 border border-dashed border-gray-700 rounded-lg p-3 mt-2 text-center">
            <p className="text-gray-500 text-xs">Screenshot: Odoo Settings &rarr; Users &rarr; API Keys (coming soon)</p>
          </div>
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
