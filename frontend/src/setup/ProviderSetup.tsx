import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import { ApiKeyEntry } from './ApiKeyEntry';
import { OAuthConnect } from './OAuthConnect';
import { ModelSelector } from './ModelSelector';

// Matches CredentialStore.to_dict() response shape
interface ProviderStatus {
  active_provider: string;
  active_model: string;
  profiles: Record<string, {
    type: string;
    configured: boolean;
    key_preview?: string;
    expired?: boolean;
  }>;
}

export function ProviderSetup() {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [loading, setLoading] = useState(true);

  function reload() {
    api<ProviderStatus>('/api/providers')
      .then(setStatus)
      .catch(console.error)
      .finally(() => setLoading(false));
  }

  useEffect(() => { reload(); }, []);

  if (loading) return (
    <div className="flex justify-center py-8">
      <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const providers = [
    { id: 'anthropic', name: 'Anthropic (Claude)', icon: '🤖', authType: 'api_key' },
    { id: 'openai', name: 'OpenAI (GPT)', icon: '⚡', authType: 'oauth' },
    { id: 'google', name: 'Google Gemini', icon: '✨', authType: 'oauth' },
  ];

  return (
    <div className="space-y-4">
      {providers.map(p => {
        const profile = status?.profiles?.[p.id];
        const isConnected = profile?.configured ?? false;
        const isActive = status?.active_provider === p.id;
        const currentModel = isActive ? (status?.active_model ?? '') : '';

        return (
          <div key={p.id} className={`bg-gray-800 rounded-xl p-5 border ${isActive ? 'border-indigo-500/50' : 'border-gray-700'}`}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{p.icon}</span>
                <div>
                  <p className="text-white font-medium">{p.name}</p>
                  {isActive && <span className="text-xs text-indigo-400">Active</span>}
                </div>
              </div>

              {isConnected && (
                <div className="flex items-center gap-2">
                  {profile?.expired && (
                    <span className="text-xs text-yellow-400 border border-yellow-600/40 rounded px-1.5 py-0.5">Token expired</span>
                  )}
                  <span className="w-2 h-2 bg-green-400 rounded-full" />
                  <span className="text-green-400 text-xs">Connected</span>
                </div>
              )}
            </div>

            {!isConnected ? (
              p.authType === 'api_key' ? (
                <ApiKeyEntry provider={p.id} onConnected={reload} />
              ) : (
                <OAuthConnect provider={p.id} onConnected={reload} />
              )
            ) : (
              <div className="space-y-3">
                <ModelSelector
                  provider={p.id}
                  currentModel={currentModel}
                  onChanged={reload}
                />
                {!isActive && (
                  <button
                    onClick={async () => {
                      await api('/api/providers/active', {
                        method: 'PUT',
                        body: JSON.stringify({ provider: p.id, model: currentModel || 'default' }),
                      });
                      reload();
                    }}
                    className="w-full py-2 text-sm rounded-lg border border-indigo-500/50 text-indigo-400 hover:bg-indigo-500/10 transition"
                  >
                    Set as active
                  </button>
                )}
                <button
                  onClick={async () => {
                    await api(`/api/providers/${p.id}/disconnect`, { method: 'POST' });
                    reload();
                  }}
                  className="w-full py-2 text-sm rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/10 transition"
                >
                  Disconnect
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
