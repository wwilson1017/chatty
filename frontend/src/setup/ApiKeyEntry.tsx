import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  provider: string;
  onConnected: () => void;
}

const API_KEY_LINKS: Record<string, { url: string; label: string }> = {
  anthropic: { url: 'https://console.anthropic.com/settings/keys', label: 'Get your API key at console.anthropic.com' },
  openai: { url: 'https://platform.openai.com/api-keys', label: 'Get your API key at platform.openai.com' },
  google: { url: 'https://aistudio.google.com/apikey', label: 'Get your API key at aistudio.google.com' },
};

export function ApiKeyEntry({ provider, onConnected }: Props) {
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    if (!key.trim()) return;
    setLoading(true); setError('');
    try {
      // OpenAI and Google use /connect-key for API key auth (separate from OAuth /connect)
      const endpoint = (provider === 'openai' || provider === 'google')
        ? `/api/providers/${provider}/connect-key`
        : `/api/providers/${provider}/connect`;
      await api(endpoint, {
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
      {API_KEY_LINKS[provider] && (
        <a
          href={API_KEY_LINKS[provider].url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-indigo-400 hover:text-indigo-300 transition"
        >
          {API_KEY_LINKS[provider].label} &rarr;
        </a>
      )}
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
