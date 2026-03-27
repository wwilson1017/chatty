import { useState } from 'react';
import { api } from '../../core/api/client';

interface Props {
  onComplete: () => void;
  onSkip: () => void;
}

export function BambooHRSetupStep({ onComplete, onSkip }: Props) {
  const [subdomain, setSubdomain] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    setSaving(true);
    setError('');
    try {
      await api('/api/integrations/bamboohr/setup', {
        method: 'POST',
        body: JSON.stringify({ subdomain, api_key: apiKey }),
      });
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setSaving(false);
    }
  }

  const isValid = subdomain.trim() && apiKey.trim();

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">Connect BambooHR</h2>
      <p className="text-gray-400 text-sm mb-6">
        Connect BambooHR to give your agents access to employee directory, time tracking, and HR data.
      </p>

      <div className="space-y-4 mb-6">
        {/* Subdomain */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">Company Subdomain</label>
          <div className="flex items-center">
            <input
              value={subdomain}
              onChange={e => setSubdomain(e.target.value)}
              placeholder="your-company"
              className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-l-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
            />
            <span className="bg-gray-700 border border-l-0 border-gray-700 text-gray-400 rounded-r-lg px-3 py-3 text-sm">
              .bamboohr.com
            </span>
          </div>
          <p className="text-gray-500 text-xs mt-1">
            The subdomain from your BambooHR URL (e.g. "acme" from acme.bamboohr.com)
          </p>
        </div>

        {/* API Key */}
        <div>
          <label className="block text-sm text-gray-300 mb-1.5">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder="Your BambooHR API key"
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          <div className="bg-gray-900 border border-dashed border-gray-700 rounded-lg p-3 mt-2 text-center">
            <p className="text-gray-500 text-xs">Screenshot: BambooHR Account &rarr; API Keys &rarr; Add New Key (coming soon)</p>
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
          {saving ? 'Connecting...' : 'Connect BambooHR'}
        </button>
      </div>
    </div>
  );
}
