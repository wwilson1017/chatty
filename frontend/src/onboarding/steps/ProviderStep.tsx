import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { ProviderStatus } from '../../core/types';
import { IconCheck, IconCircle, IconArrowRight } from '../../shared/icons';
import { useIsMobile } from '../../shared/useIsMobile';

interface Props {
  onComplete: () => void;
}

type AuthMethod = 'setup-token' | 'api-key' | 'cli-sync';

interface ProviderDef {
  id: string;
  name: string;
  subtitle: string;
  methods: { id: AuthMethod; label: string; description: string }[];
}

const PROVIDERS: ProviderDef[] = [
  {
    id: 'anthropic',
    name: 'Anthropic',
    subtitle: 'Claude Sonnet, Opus',
    methods: [
      { id: 'api-key', label: 'API Key', description: 'Paste an API key from console.anthropic.com' },
    ],
  },
  {
    id: 'openai',
    name: 'OpenAI',
    subtitle: 'GPT-4o, o1',
    methods: [
      { id: 'api-key', label: 'API Key', description: 'Paste an API key from platform.openai.com' },
      { id: 'cli-sync', label: 'Import from CLI', description: 'Import credentials from the OpenAI CLI if installed' },
    ],
  },
  {
    id: 'google',
    name: 'Google',
    subtitle: 'Gemini Pro, Flash',
    methods: [
      { id: 'api-key', label: 'API Key', description: 'Paste an API key from aistudio.google.com' },
    ],
  },
];

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function ProviderStep({ onComplete }: Props) {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeMethod, setActiveMethod] = useState<Record<string, AuthMethod>>({});
  const [tokenValue, setTokenValue] = useState('');
  const [keyValue, setKeyValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function reload() {
    api<ProviderStatus>('/api/providers').then(setStatus).catch(console.error);
  }

  useEffect(() => { reload(); }, []);

  const isMobile = useIsMobile();
  const anyConnected = status ? Object.values(status.profiles).some(p => p.configured) : false;

  function getMethod(providerId: string): AuthMethod {
    return activeMethod[providerId] || PROVIDERS.find(p => p.id === providerId)!.methods[0].id;
  }

  function clearForm() { setError(''); setKeyValue(''); setTokenValue(''); }

  async function submitSetupToken() {
    if (!tokenValue.trim()) return;
    setLoading(true); setError('');
    try {
      await api('/api/providers/anthropic/setup-token', {
        method: 'POST', body: JSON.stringify({ token: tokenValue.trim() }),
      });
      setTokenValue(''); reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid token');
    } finally { setLoading(false); }
  }

  async function submitApiKey(provider: string) {
    if (!keyValue.trim()) return;
    setLoading(true); setError('');
    try {
      const endpoint = (provider === 'openai' || provider === 'google')
        ? `/api/providers/${provider}/connect-key`
        : `/api/providers/${provider}/connect`;
      await api(endpoint, {
        method: 'POST', body: JSON.stringify({ api_key: keyValue.trim() }),
      });
      setKeyValue(''); reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid API key');
    } finally { setLoading(false); }
  }

  async function syncOpenAICli() {
    setLoading(true); setError('');
    try {
      await api('/api/providers/openai/sync-cli', { method: 'POST' });
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'No CLI credentials found');
    } finally { setLoading(false); }
  }

  function renderAuthForm(provider: ProviderDef) {
    const method = getMethod(provider.id);

    if (method === 'setup-token') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ background: 'rgba(20,24,30,0.78)', border: '1px solid rgba(230,235,242,0.07)', borderRadius: 6, padding: 16 }}>
            <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', marginBottom: 8 }}>1. Open your terminal and run:</p>
            <code style={{
              display: 'block', background: 'rgba(34,40,48,0.55)', padding: '8px 12px',
              borderRadius: 4, fontSize: 13, color: 'var(--color-ch-accent, #C8D1D9)',
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            }}>claude setup-token</code>
            <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', marginTop: 12 }}>2. Copy the token and paste it below:</p>
          </div>
          <input type="password" value={tokenValue} onChange={e => setTokenValue(e.target.value)}
            placeholder="Paste your setup token here" onKeyDown={e => e.key === 'Enter' && submitSetupToken()}
            style={{
              width: '100%', boxSizing: 'border-box', background: 'rgba(34,40,48,0.55)',
              border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4', borderRadius: 4,
              padding: '10px 14px', fontSize: 13, outline: 'none',
            }}
          />
          {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
          <button onClick={submitSetupToken} disabled={loading || !tokenValue.trim()} style={{
            width: '100%', padding: '10px 16px', background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', borderRadius: 4, fontSize: 13, fontWeight: 500, cursor: 'pointer',
            opacity: (loading || !tokenValue.trim()) ? 0.5 : 1,
          }}>{loading ? 'Validating...' : 'Connect'}</button>
        </div>
      );
    }

    if (method === 'api-key') {
      const config: Record<string, { placeholder: string; link: string; linkLabel: string }> = {
        anthropic: { placeholder: 'sk-ant-...', link: 'https://console.anthropic.com/settings/keys', linkLabel: 'Open Anthropic Console' },
        openai: { placeholder: 'sk-...', link: 'https://platform.openai.com/api-keys', linkLabel: 'Open OpenAI Platform' },
        google: { placeholder: 'AIza...', link: 'https://aistudio.google.com/apikey', linkLabel: 'Open Google AI Studio' },
      };
      const c = config[provider.id];
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <a href={c.link} target="_blank" rel="noopener noreferrer" style={{
            fontSize: 13, color: 'var(--color-ch-accent, #C8D1D9)', textDecoration: 'none',
          }}>{c.linkLabel} &rarr;</a>
          <input type="password" value={keyValue} onChange={e => setKeyValue(e.target.value)}
            placeholder={c.placeholder} onKeyDown={e => e.key === 'Enter' && submitApiKey(provider.id)}
            style={{
              width: '100%', boxSizing: 'border-box', background: 'rgba(34,40,48,0.55)',
              border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4', borderRadius: 4,
              padding: '10px 14px', fontSize: 13, outline: 'none',
            }}
          />
          {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
          <button onClick={() => submitApiKey(provider.id)} disabled={loading || !keyValue.trim()} style={{
            width: '100%', padding: '10px 16px', background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', borderRadius: 4, fontSize: 13, fontWeight: 500, cursor: 'pointer',
            opacity: (loading || !keyValue.trim()) ? 0.5 : 1,
          }}>{loading ? 'Validating...' : 'Connect'}</button>
        </div>
      );
    }

    if (method === 'cli-sync') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <p style={{ color: 'rgba(237,240,244,0.62)', fontSize: 13 }}>
            If you have the OpenAI CLI installed and signed in, Chatty can import your credentials automatically.
          </p>
          {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
          <button onClick={syncOpenAICli} disabled={loading} style={{
            width: '100%', padding: '10px 16px', background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', borderRadius: 4, fontSize: 13, fontWeight: 500, cursor: 'pointer',
            opacity: loading ? 0.5 : 1,
          }}>{loading ? 'Searching...' : 'Import from CLI'}</button>
        </div>
      );
    }

    return null;
  }

  return (
    <div>
      <div style={mono(10, 'rgba(237,240,244,0.38)')}>Connect your model</div>
      <h1 style={{
        fontFamily: "'Fraunces', Georgia, serif",
        fontSize: 44, fontWeight: 400, letterSpacing: '-0.025em',
        lineHeight: 1.05, margin: '14px 0 12px', color: '#EDF0F4',
      }}>
        Where does <span style={{ fontStyle: 'italic', color: '#D4A85A' }}>the thinking</span> happen?
      </h1>
      <p style={{ fontSize: 15, color: 'rgba(237,240,244,0.62)', lineHeight: 1.5, marginBottom: 32, maxWidth: 560 }}>
        Chatty routes agents through the model you connect. You can change this later, or run different agents on different providers.
      </p>

      {anyConnected && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 16px', marginBottom: 24,
          background: 'rgba(142,165,137,0.06)', border: '1px solid rgba(142,165,137,0.15)',
          borderRadius: 6,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#8EA589' }} />
          <p style={{ fontSize: 13, color: '#8EA589' }}>Provider connected. Connect more below or continue.</p>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, 1fr)', gap: 8, marginBottom: 28 }}>
        {PROVIDERS.map(p => {
          const profile = status?.profiles?.[p.id];
          const isConnected = profile?.configured ?? false;
          const isExpanded = expanded === p.id;

          return (
            <div key={p.id} style={{
              padding: 18,
              border: `1px solid ${isConnected ? '#8EA589' : isExpanded ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.07)'}`,
              background: isConnected ? 'rgba(142,165,137,0.06)' : isExpanded ? 'rgba(200,209,217,0.12)' : 'rgba(20,24,30,0.78)',
              borderRadius: 6, cursor: isConnected ? 'default' : 'pointer',
            }}>
              <div
                onClick={() => { if (!isConnected) { setExpanded(isExpanded ? null : p.id); clearForm(); } }}
                style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}
              >
                <div style={{
                  width: 28, height: 28, borderRadius: 4,
                  background: 'rgba(245,239,227,0.06)',
                  border: '1px solid rgba(230,235,242,0.07)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  {isConnected
                    ? <IconCheck size={15} style={{ color: '#8EA589' }} strokeWidth={2.5} />
                    : <IconCircle size={13} style={{ color: 'rgba(237,240,244,0.38)' }} />
                  }
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 18, letterSpacing: '-0.01em', color: '#EDF0F4',
                  }}>{p.name}</div>
                  <div style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)', marginTop: 2 }}>{p.subtitle}</div>
                </div>
              </div>

              {isExpanded && !isConnected && (
                <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
                  {p.methods.length > 1 && (
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                      {p.methods.map(m => {
                        const isActive = getMethod(p.id) === m.id;
                        return (
                          <button key={m.id}
                            onClick={() => { setActiveMethod(prev => ({ ...prev, [p.id]: m.id })); clearForm(); }}
                            style={{
                              padding: '4px 12px', borderRadius: 4, fontSize: 11, fontWeight: 500,
                              background: isActive ? 'rgba(200,209,217,0.12)' : 'transparent',
                              color: isActive ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                              border: `1px solid ${isActive ? 'rgba(200,209,217,0.3)' : 'rgba(230,235,242,0.14)'}`,
                              cursor: 'pointer',
                            }}
                          >{m.label}</button>
                        );
                      })}
                    </div>
                  )}
                  {renderAuthForm(p)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
        <button
          onClick={onComplete}
          disabled={!anyConnected}
          style={{
            background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', fontSize: 14, fontWeight: 500,
            padding: '9px 20px', borderRadius: 4, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 8,
            opacity: anyConnected ? 1 : 0.3,
          }}
        >
          Continue <IconArrowRight size={15} strokeWidth={2.5} />
        </button>
      </div>

      {!anyConnected && (
        <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', textAlign: 'center', marginTop: 12 }}>
          Connect at least one provider to continue
        </p>
      )}
    </div>
  );
}
