import { useState } from 'react';
import { api } from '../../core/api/client';

interface Props {
  onComplete: () => void;
  onSkip: () => void;
}

export function QuickBooksSetupStep({ onComplete, onSkip }: Props) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<'idle' | 'waiting' | 'done' | 'error'>('idle');
  const [error, setError] = useState('');

  async function startOAuth() {
    setLoading(true);
    setError('');
    setStatus('waiting');
    try {
      await api('/api/integrations/quickbooks/setup', { method: 'POST' });
      setStatus('done');
      onComplete();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Setup failed';
      setError(msg);
      setStatus('error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">Connect QuickBooks</h2>
      <p className="text-gray-400 text-sm mb-6">
        Connect QuickBooks Online to let your agents access invoices, bills, payments, and financial reports.
      </p>

      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 mb-6">
        <h3 className="text-white font-medium mb-2">How it works</h3>
        <ol className="text-gray-400 text-sm space-y-2 list-decimal list-inside">
          <li>Click "Connect QuickBooks" below</li>
          <li>A browser window will open to Intuit's login page</li>
          <li>Sign in and authorize Chatty to access your QuickBooks data</li>
          <li>You'll be redirected back automatically</li>
        </ol>
      </div>

      {status === 'waiting' && (
        <div className="flex items-center gap-3 text-sm text-ch-gold bg-indigo-900/20 rounded-lg px-4 py-3 mb-4">
          <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span>Browser opened — complete authorization to continue...</span>
        </div>
      )}

      {status === 'done' && (
        <div className="text-sm text-green-400 bg-green-900/20 rounded-lg px-4 py-3 mb-4">
          Connected successfully!
        </div>
      )}

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
        {status !== 'done' && (
          <button
            onClick={startOAuth}
            disabled={loading}
            className="flex-1 py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Waiting...
              </>
            ) : (
              'Connect QuickBooks'
            )}
          </button>
        )}
      </div>
    </div>
  );
}
