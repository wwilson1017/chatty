import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { ProviderStatus } from '../core/types';
import { ApiKeyEntry } from './ApiKeyEntry';
import { SetupTokenEntry } from './SetupTokenEntry';
import { ModelSelector } from './ModelSelector';
import { OllamaSetup } from './OllamaSetup';
import { TogetherSetup } from './TogetherSetup';
import { IconBrain, IconZap, IconSparkle, IconGlobe, IconHome } from '../shared/icons';

const PROVIDER_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string; strokeWidth?: number }>> = {
  anthropic: IconBrain,
  openai: IconZap,
  google: IconSparkle,
  together: IconGlobe,
  ollama: IconHome,
};

type AuthTab = 'setup-token' | 'api-key' | 'ollama-setup' | 'together-setup';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

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
    <div style={{ display: 'flex', justifyContent: 'center', padding: '32px 0' }}>
      <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const providers = [
    { id: 'anthropic', name: 'Anthropic (Claude)', tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }], defaultTab: 'api-key' as AuthTab },
    { id: 'openai', name: 'OpenAI (GPT)', tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }], defaultTab: 'api-key' as AuthTab },
    { id: 'google', name: 'Google (Gemini)', tabs: [{ id: 'api-key' as AuthTab, label: 'API Key' }], defaultTab: 'api-key' as AuthTab },
    { id: 'together', name: 'Together AI', tabs: [{ id: 'together-setup' as AuthTab, label: 'API Key' }], defaultTab: 'together-setup' as AuthTab },
    ...(!status?.is_railway ? [{ id: 'ollama', name: 'Ollama (Local)', tabs: [{ id: 'ollama-setup' as AuthTab, label: 'Local Setup' }], defaultTab: 'ollama-setup' as AuthTab }] : []),
  ];

  function getTab(providerId: string): AuthTab {
    return authTab[providerId] || providers.find(p => p.id === providerId)!.defaultTab;
  }

  function renderConnectUI(p: typeof providers[0]) {
    const tab = getTab(p.id);
    return (
      <div>
        {p.tabs.length > 1 && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            {p.tabs.map(t => (
              <button key={t.id} onClick={() => setAuthTab(prev => ({ ...prev, [p.id]: t.id }))}
                style={{
                  padding: '4px 12px', borderRadius: 4, fontSize: 11, fontWeight: 500,
                  background: tab === t.id ? 'rgba(200,209,217,0.12)' : 'transparent',
                  color: tab === t.id ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                  border: `1px solid ${tab === t.id ? 'rgba(200,209,217,0.3)' : 'rgba(230,235,242,0.14)'}`,
                  cursor: 'pointer',
                }}
              >{t.label}</button>
            ))}
          </div>
        )}
        {tab === 'setup-token' && <SetupTokenEntry onConnected={reload} />}
        {tab === 'api-key' && <ApiKeyEntry provider={p.id} onConnected={reload} />}
        {tab === 'together-setup' && <TogetherSetup onConnected={reload} />}
        {tab === 'ollama-setup' && <OllamaSetup onConnected={reload} />}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {providers.map(p => {
        const profile = status?.profiles?.[p.id];
        const isConnected = profile?.configured ?? false;
        const isActive = status?.active_provider === p.id;
        const currentModel = isActive ? (status?.active_model ?? '') : '';

        return (
          <div key={p.id} style={{
            background: 'rgba(20,24,30,0.78)',
            borderRadius: 6, padding: 20,
            border: `1px solid ${isActive ? 'rgba(200,209,217,0.3)' : 'rgba(230,235,242,0.07)'}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 4,
                  background: 'rgba(245,239,227,0.06)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'rgba(237,240,244,0.62)',
                }}>
                  {(() => { const Icon = PROVIDER_ICONS[p.id] || IconGlobe; return <Icon size={16} strokeWidth={1.75} />; })()}
                </div>
                <div>
                <p style={{
                  fontFamily: "'Fraunces', Georgia, serif",
                  fontSize: 16, letterSpacing: '-0.01em', color: '#EDF0F4', margin: 0,
                }}>{p.name}</p>
                {isActive && <span style={{ ...mono(9, '#D4A85A'), marginTop: 2, display: 'inline-block' }}>Active</span>}
                </div>
              </div>

              {isConnected && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {profile?.expired && (
                    <span style={{ fontSize: 11, color: '#D4A85A', border: '1px solid rgba(212,168,90,0.3)', borderRadius: 4, padding: '2px 6px' }}>Expired</span>
                  )}
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8EA589' }} />
                  <span style={{ ...mono(10, '#8EA589') }}>Connected</span>
                </div>
              )}
            </div>

            {!isConnected ? renderConnectUI(p) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <ModelSelector provider={p.id} currentModel={currentModel} onChanged={reload} />
                {!isActive && (
                  <button onClick={async () => {
                    await api('/api/providers/active', { method: 'PUT', body: JSON.stringify({ provider: p.id, model: currentModel || '' }) });
                    reload();
                  }} style={{
                    width: '100%', padding: '8px 16px', fontSize: 13, borderRadius: 4,
                    border: '1px solid rgba(200,209,217,0.3)', color: 'var(--color-ch-accent, #C8D1D9)',
                    background: 'transparent', cursor: 'pointer',
                  }}>Set as active</button>
                )}
                <button onClick={async () => {
                  await api(`/api/providers/${p.id}/disconnect`, { method: 'POST' });
                  reload();
                }} style={{
                  width: '100%', padding: '8px 16px', fontSize: 13, borderRadius: 4,
                  border: '1px solid rgba(217,119,87,0.3)', color: '#D97757',
                  background: 'transparent', cursor: 'pointer',
                }}>Disconnect</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
