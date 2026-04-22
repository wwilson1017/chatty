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

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
  color: '#EDF0F4', borderRadius: 4, padding: '10px 14px', fontSize: 13, outline: 'none',
};

export function ApiKeyEntry({ provider, onConnected }: Props) {
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function connect() {
    if (!key.trim()) return;
    setLoading(true); setError('');
    try {
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <input
        type="password"
        value={key}
        onChange={e => setKey(e.target.value)}
        placeholder="sk-ant-..."
        onKeyDown={e => e.key === 'Enter' && connect()}
        style={inputStyle}
      />
      {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
      {API_KEY_LINKS[provider] && (
        <a
          href={API_KEY_LINKS[provider].url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 12, color: 'var(--color-ch-accent, #C8D1D9)', textDecoration: 'none' }}
        >
          {API_KEY_LINKS[provider].label} &rarr;
        </a>
      )}
      <button
        onClick={connect}
        disabled={loading || !key.trim()}
        style={{
          width: '100%', padding: '9px 16px', borderRadius: 4,
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', fontSize: 13, fontWeight: 500,
          cursor: 'pointer', opacity: (loading || !key.trim()) ? 0.5 : 1,
        }}
      >
        {loading ? 'Validating...' : 'Connect'}
      </button>
    </div>
  );
}
