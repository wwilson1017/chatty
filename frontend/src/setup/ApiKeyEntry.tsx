import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  provider: string;
  onConnected: () => void;
}

export function ApiKeyEntry({ provider, onConnected }: Props) {
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    if (!key.trim()) return;
    setLoading(true); setError('');
    try {
      await api(`/api/providers/${provider}/connect`, {
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
      <input
        type="password"
        value={key}
        onChange={e => setKey(e.target.value)}
        placeholder="sk-ant-..."
        onKeyDown={e => e.key === 'Enter' && connect()}
        className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
      />
      {error && <p className="text-red-400 text-xs">{error}</p>}
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
