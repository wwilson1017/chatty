import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { ProviderStatus } from '../../core/types';

interface Props {
  onComplete: () => void;
}

type AuthMethod = 'setup-token' | 'api-key' | 'cli-sync';

interface ProviderDef {
  id: string;
  name: string;
  icon: string;
  methods: { id: AuthMethod; label: string; description: string }[];
}

const PROVIDERS: ProviderDef[] = [
  {
    id: 'anthropic',
    name: 'Anthropic (Claude)',
    icon: '\u{1F916}',
    methods: [
      {
        id: 'api-key',
        label: 'API Key',
        description: 'Paste an API key from console.anthropic.com',
      },
    ],
  },
  {
    id: 'openai',
    name: 'OpenAI (GPT)',
    icon: '\u26A1',
    methods: [
      {
        id: 'api-key',
        label: 'API Key',
        description: 'Paste an API key from platform.openai.com',
      },
      {
        id: 'cli-sync',
        label: 'Import from CLI',
        description: 'Import credentials from the OpenAI CLI if installed',
      },
    ],
  },
  {
    id: 'google',
    name: 'Google (Gemini)',
    icon: '\u2728',
    methods: [
      {
        id: 'api-key',
        label: 'API Key',
        description: 'Paste an API key from aistudio.google.com',
      },
    ],
  },
];

export function ProviderStep({ onComplete }: Props) {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activeMethod, setActiveMethod] = useState<Record<string, AuthMethod>>({});

  // Form state
  const [tokenValue, setTokenValue] = useState('');
  const [keyValue, setKeyValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function reload() {
    api<ProviderStatus>('/api/providers').then(setStatus).catch(console.error);
  }

  useEffect(() => { reload(); }, []);

  const anyConnected = status
    ? Object.values(status.profiles).some(p => p.configured)
    : false;

  function getMethod(providerId: string): AuthMethod {
    return activeMethod[providerId] || PROVIDERS.find(p => p.id === providerId)!.methods[0].id;
  }

  function clearForm() {
    setError('');
    setKeyValue('');
    setTokenValue('');
  }

  async function submitSetupToken() {
    if (!tokenValue.trim()) return;
    setLoading(true); setError('');
    try {
      await api('/api/providers/anthropic/setup-token', {
        method: 'POST',
        body: JSON.stringify({ token: tokenValue.trim() }),
      });
      setTokenValue('');
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid token');
    } finally {
      setLoading(false);
    }
  }

  async function submitApiKey(provider: string) {
    if (!keyValue.trim()) return;
    setLoading(true); setError('');
    try {
      const endpoint = (provider === 'openai' || provider === 'google')
        ? `/api/providers/${provider}/connect-key`
        : `/api/providers/${provider}/connect`;
      await api(endpoint, {
        method: 'POST',
        body: JSON.stringify({ api_key: keyValue.trim() }),
      });
      setKeyValue('');
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Invalid API key');
    } finally {
      setLoading(false);
    }
  }

  async function syncOpenAICli() {
    setLoading(true); setError('');
    try {
      await api('/api/providers/openai/sync-cli', { method: 'POST' });
      reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'No CLI credentials found');
    } finally {
      setLoading(false);
    }
  }

  function renderAuthForm(provider: ProviderDef) {
    const method = getMethod(provider.id);

    if (method === 'setup-token') {
      return (
        <div className="space-y-3">
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <p className="text-gray-300 text-sm mb-2">1. Open your terminal and run:</p>
            <code className="block bg-gray-800 text-indigo-400 px-3 py-2 rounded text-sm font-mono select-all">
              claude setup-token
            </code>
            <p className="text-gray-300 text-sm mt-3">2. Copy the token and paste it below:</p>
          </div>
          <input
            type="password"
            value={tokenValue}
            onChange={e => setTokenValue(e.target.value)}
            placeholder="Paste your setup token here"
            onKeyDown={e => e.key === 'Enter' && submitSetupToken()}
            className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            onClick={submitSetupToken}
            disabled={loading || !tokenValue.trim()}
            className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
          >
            {loading ? 'Validating...' : 'Connect'}
          </button>
        </div>
      );
    }

    if (method === 'api-key') {
      const config: Record<string, { placeholder: string; link: string; linkLabel: string }> = {
        anthropic: {
          placeholder: 'sk-ant-...',
          link: 'https://console.anthropic.com/settings/keys',
          linkLabel: 'Open Anthropic Console',
        },
        openai: {
          placeholder: 'sk-...',
          link: 'https://platform.openai.com/api-keys',
          linkLabel: 'Open OpenAI Platform',
        },
        google: {
          placeholder: 'AIza...',
          link: 'https://aistudio.google.com/apikey',
          linkLabel: 'Open Google AI Studio',
        },
      };
      const c = config[provider.id];
      return (
        <div className="space-y-3">
          <a
            href={c.link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-indigo-400 text-sm hover:text-indigo-300 transition"
          >
            {c.linkLabel}
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
          <input
            type="password"
            value={keyValue}
            onChange={e => setKeyValue(e.target.value)}
            placeholder={c.placeholder}
            onKeyDown={e => e.key === 'Enter' && submitApiKey(provider.id)}
            className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            onClick={() => submitApiKey(provider.id)}
            disabled={loading || !keyValue.trim()}
            className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
          >
            {loading ? 'Validating...' : 'Connect'}
          </button>
        </div>
      );
    }

    if (method === 'cli-sync') {
      return (
        <div className="space-y-3">
          <p className="text-gray-400 text-sm">
            If you have the OpenAI CLI (Codex) installed and signed in, Chatty can import your credentials automatically.
          </p>
          <a
            href="https://github.com/openai/codex"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-indigo-400 text-sm hover:text-indigo-300 transition"
          >
            Install the OpenAI CLI
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            onClick={syncOpenAICli}
            disabled={loading}
            className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
          >
            {loading ? 'Searching...' : 'Import from CLI'}
          </button>
        </div>
      );
    }

    return null;
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">Connect an AI Provider</h2>
      <p className="text-gray-400 text-sm mb-6">
        Your agents need an AI provider to work. Connect at least one to continue.
      </p>

      <div className="space-y-3 mb-8">
        {PROVIDERS.map(p => {
          const profile = status?.profiles?.[p.id];
          const isConnected = profile?.configured ?? false;
          const isExpanded = expanded === p.id;

          return (
            <div
              key={p.id}
              className={`bg-gray-800 rounded-xl border transition ${
                isConnected
                  ? 'border-green-500/40'
                  : isExpanded
                    ? 'border-indigo-500/50'
                    : 'border-gray-700'
              }`}
            >
              <button
                onClick={() => {
                  if (!isConnected) {
                    setExpanded(isExpanded ? null : p.id);
                    clearForm();
                  }
                }}
                className="w-full p-4 flex items-center justify-between text-left"
                disabled={isConnected}
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{p.icon}</span>
                  <div>
                    <p className="text-white font-medium">{p.name}</p>
                    <p className="text-gray-400 text-xs mt-0.5">
                      {p.methods.map(m => m.label).join(' / ')}
                    </p>
                  </div>
                </div>

                {isConnected ? (
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 bg-green-400 rounded-full" />
                    <span className="text-green-400 text-xs font-medium">Connected</span>
                  </div>
                ) : (
                  <span className={`text-gray-400 text-sm transition ${isExpanded ? 'rotate-180' : ''}`}>
                    &#9662;
                  </span>
                )}
              </button>

              {isExpanded && !isConnected && (
                <div className="px-4 pb-4 border-t border-gray-700 pt-4">
                  {/* Method selector (only if multiple methods) */}
                  {p.methods.length > 1 && (
                    <div className="flex gap-2 mb-4">
                      {p.methods.map(m => {
                        const isActive = getMethod(p.id) === m.id;
                        return (
                          <button
                            key={m.id}
                            onClick={() => {
                              setActiveMethod(prev => ({ ...prev, [p.id]: m.id }));
                              clearForm();
                            }}
                            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                              isActive
                                ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/50'
                                : 'bg-gray-700 text-gray-400 border border-gray-600 hover:bg-gray-600'
                            }`}
                          >
                            {m.label}
                          </button>
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

      <button
        onClick={onComplete}
        disabled={!anyConnected}
        className="w-full py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
      >
        Continue
      </button>

      {!anyConnected && (
        <p className="text-gray-500 text-xs text-center mt-3">
          Connect at least one provider to continue
        </p>
      )}
    </div>
  );
}
