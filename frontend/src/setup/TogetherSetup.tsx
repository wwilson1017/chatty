import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  onConnected: () => void;
}

export function TogetherSetup({ onConnected }: Props) {
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    if (!key.trim()) return;
    setLoading(true);
    setError('');
    try {
      await api('/api/providers/together/connect', {
        method: 'POST',
        body: JSON.stringify({ api_key: key.trim() }),
      });
      onConnected();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid API key');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="bg-gray-700/50 rounded-lg px-4 py-3 space-y-2">
        <p className="text-sm text-gray-300">
          Run open-weight AI models in the cloud for a fraction of the cost.
        </p>
        <ol className="text-xs text-gray-400 space-y-1 list-decimal list-inside">
          <li>Create a free account at together.ai ($25 free credits, no credit card)</li>
          <li>Go to Settings &gt; API Keys and create a key</li>
          <li>Paste it below</li>
        </ol>
      </div>

      <input
        type="password"
        value={key}
        onChange={e => setKey(e.target.value)}
        placeholder="together_..."
        onKeyDown={e => e.key === 'Enter' && connect()}
        className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
      />

      {error && <p className="text-red-400 text-xs">{error}</p>}

      <a
        href="https://api.together.xyz/settings/api-keys"
        target="_blank"
        rel="noopener noreferrer"
        className="block text-xs text-indigo-400 hover:text-indigo-300 transition"
      >
        Get your API key at api.together.xyz &rarr;
      </a>

      <button
        onClick={connect}
        disabled={loading || !key.trim()}
        className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
      >
        {loading ? 'Validating...' : 'Connect'}
      </button>
    </div>
  );
}
