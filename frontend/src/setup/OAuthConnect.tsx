import { useState } from 'react';
import { api } from '../core/api/client';

interface Props {
  provider: string;
  onConnected: () => void;
}

export function OAuthConnect({ provider, onConnected }: Props) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<'idle' | 'waiting' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');

  async function startFlow() {
    setLoading(true); setError(''); setStatus('waiting');
    try {
      // This call opens the browser and blocks until OAuth completes (backend handles it)
      await api(`/api/providers/${provider}/connect`, { method: 'POST' });
      setStatus('done');
      onConnected();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'OAuth flow failed');
      setStatus('error');
    } finally {
      setLoading(false);
    }
  }

  const providerLabel = provider === 'google' ? 'Google' : 'OpenAI';

  return (
    <div className="space-y-3">
      {status === 'waiting' && (
        <div className="flex items-center gap-3 text-sm text-ch-gold bg-indigo-900/20 rounded-lg px-4 py-3">
          <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span>Browser opened — complete authorization to continue...</span>
        </div>
      )}

      {status === 'done' && (
        <div className="text-sm text-green-400 bg-green-900/20 rounded-lg px-4 py-3">
          ✓ Connected successfully!
        </div>
      )}

      {error && <p className="text-red-400 text-xs">{error}</p>}

      {status !== 'done' && (
        <button
          onClick={startFlow}
          disabled={loading}
          className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              Waiting for browser...
            </>
          ) : (
            `Connect ${providerLabel}`
          )}
        </button>
      )}

      {provider === 'google' && (
        <p className="text-ch-ink-dim text-xs text-center">
          Covers Gemini AI + Gmail + Google Calendar in one step
        </p>
      )}
    </div>
  );
}
