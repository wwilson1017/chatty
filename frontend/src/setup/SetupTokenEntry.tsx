import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  onConnected: () => void;
}

export function SetupTokenEntry({ onConnected }: Props) {
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    if (!token.trim()) return;
    setLoading(true); setError('');
    try {
      await api('/api/providers/anthropic/setup-token', {
        method: 'POST',
        body: JSON.stringify({ token: token.trim() }),
      });
      onConnected();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid setup token');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-gray-400 text-xs">
        Run <code className="text-indigo-400 bg-gray-900 px-1.5 py-0.5 rounded">claude setup-token</code> in your terminal, then paste the result below.
      </p>
      <input
        type="password"
        value={token}
        onChange={e => setToken(e.target.value)}
        placeholder="Paste your setup token"
        onKeyDown={e => e.key === 'Enter' && connect()}
        className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
      />
      {error && <p className="text-red-400 text-xs">{error}</p>}
      <button
        onClick={connect}
        disabled={loading || !token.trim()}
        className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
      >
        {loading ? 'Validating...' : 'Connect'}
      </button>
    </div>
  );
}
