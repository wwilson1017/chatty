import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { ProviderStatus } from '../core/types';
import { ApiKeyEntry } from './ApiKeyEntry';
import { SetupTokenEntry } from './SetupTokenEntry';
import { ModelSelector } from './ModelSelector';

type AuthTab = 'setup-token' | 'api-key';

export function ProviderSetup() {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [authTab, setAuthTab] = useState<Record<string, AuthTab>>({});

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
    {
      id: 'anthropic',
      name: 'Anthropic (Claude)',
      icon: '\u{1F916}',
      tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }],
      defaultTab: 'api-key' as AuthTab,
    },
    {
      id: 'openai',
      name: 'OpenAI (GPT)',
      icon: '\u26A1',
      tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }],
      defaultTab: 'api-key' as AuthTab,
    },
    {
      id: 'google',
      name: 'Google (Gemini)',
      icon: '\u2728',
      tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }],
      defaultTab: 'api-key' as AuthTab,
    },
  ];

  function getTab(providerId: string): AuthTab {
    return authTab[providerId] || providers.find(p => p.id === providerId)!.defaultTab;
  }

  function renderConnectUI(p: typeof providers[0]) {
    const tab = getTab(p.id);

    return (
      <div>
        {p.tabs.length > 1 && (
          <div className="flex gap-2 mb-3">
            {p.tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setAuthTab(prev => ({ ...prev, [p.id]: t.id }))}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition ${
                  tab === t.id
                    ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/50'
                    : 'bg-gray-700 text-gray-400 border border-gray-600 hover:bg-gray-600'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {tab === 'setup-token' && <SetupTokenEntry onConnected={reload} />}
        {tab === 'api-key' && <ApiKeyEntry provider={p.id} onConnected={reload} />}
      </div>
    );
  }

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

            {!isConnected ? renderConnectUI(p) : (
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
                        body: JSON.stringify({ provider: p.id, model: currentModel || '' }),
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
