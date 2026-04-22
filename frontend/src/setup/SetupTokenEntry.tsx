import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  onConnected: () => void;
}

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
  color: '#EDF0F4', borderRadius: 4, padding: '10px 14px', fontSize: 13, outline: 'none',
};

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)', margin: 0 }}>
        Run <code style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: 12, color: 'var(--color-ch-accent, #C8D1D9)',
          background: 'rgba(34,40,48,0.55)', padding: '2px 6px', borderRadius: 3,
        }}>claude setup-token</code> in your terminal, then paste below.
      </p>
      <input
        type="password"
        value={token}
        onChange={e => setToken(e.target.value)}
        placeholder="Paste your setup token"
        onKeyDown={e => e.key === 'Enter' && connect()}
        style={inputStyle}
      />
      {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
      <button
        onClick={connect}
        disabled={loading || !token.trim()}
        style={{
          width: '100%', padding: '9px 16px', borderRadius: 4,
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', fontSize: 13, fontWeight: 500,
          cursor: 'pointer', opacity: (loading || !token.trim()) ? 0.5 : 1,
        }}
      >
        {loading ? 'Validating...' : 'Connect'}
      </button>
    </div>
  );
}
