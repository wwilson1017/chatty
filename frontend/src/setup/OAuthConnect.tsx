import { useEffect } from 'react';
import { useOAuthFlow } from '../core/hooks/useOAuthFlow';

interface Props {
  provider: string;
  onConnected: () => void;
}

export function OAuthConnect({ provider, onConnected }: Props) {
  const { state, start } = useOAuthFlow();

  useEffect(() => {
    if (state.status === 'success') onConnected();
  }, [state.status, onConnected]);

  const providerLabel = provider === 'google' ? 'Google' : 'OpenAI';

  async function startFlow() {
    await start({
      setupUrl: `/api/providers/${provider}/connect`,
      completeUrl: `/api/providers/${provider}/connect/complete`,
    });
  }

  const isWaiting = state.status === 'awaiting_user' || state.status === 'starting' || state.status === 'completing';
  const isDone = state.status === 'success';

  return (
    <div className="space-y-3">
      {isWaiting && (
        <div className="flex items-center gap-3 text-sm text-ch-gold bg-indigo-900/20 rounded-lg px-4 py-3">
          <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span>
            {state.status === 'starting' && 'Preparing authorization...'}
            {state.status === 'awaiting_user' && 'Complete authorization in the popup window...'}
            {state.status === 'completing' && 'Finalizing connection...'}
          </span>
        </div>
      )}

      {isDone && (
        <div className="text-sm text-green-400 bg-green-900/20 rounded-lg px-4 py-3">
          ✓ Connected successfully!
        </div>
      )}

      {state.status === 'error' && state.error && (
        <p className="text-red-400 text-xs">{state.error}</p>
      )}

      {!isDone && (
        <button
          onClick={startFlow}
          disabled={isWaiting}
          className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {isWaiting ? (
            <>
              <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              Waiting for authorization...
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
