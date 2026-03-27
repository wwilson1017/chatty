import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import type { ProviderStatus } from '../../core/types';
import { ApiKeyEntry } from '../../setup/ApiKeyEntry';
import { OAuthConnect } from '../../setup/OAuthConnect';

interface Props {
  onComplete: () => void;
}

const PROVIDERS = [
  {
    id: 'anthropic',
    name: 'Anthropic (Claude)',
    icon: '🤖',
    authType: 'api_key' as const,
    guidance: 'Create an API key at console.anthropic.com',
    link: 'https://console.anthropic.com/settings/keys',
    linkLabel: 'Open Anthropic Console',
    note: 'Paste your API key below',
  },
  {
    id: 'openai',
    name: 'OpenAI (GPT)',
    icon: '⚡',
    authType: 'oauth' as const,
    guidance: 'Sign in with your OpenAI account',
    note: 'Covers GPT-4o and other ChatGPT models',
  },
  {
    id: 'google',
    name: 'Google (Gemini)',
    icon: '✨',
    authType: 'oauth' as const,
    guidance: 'Sign in with your Google account',
    note: 'Also enables Gmail + Google Calendar',
  },
];

export function ProviderStep({ onComplete }: Props) {
  const [status, setStatus] = useState<ProviderStatus | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  function reload() {
    api<ProviderStatus>('/api/providers').then(setStatus).catch(console.error);
  }

  useEffect(() => { reload(); }, []);

  const anyConnected = status
    ? Object.values(status.profiles).some(p => p.configured)
    : false;

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
                onClick={() => !isConnected && setExpanded(isExpanded ? null : p.id)}
                className="w-full p-4 flex items-center justify-between text-left"
                disabled={isConnected}
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{p.icon}</span>
                  <div>
                    <p className="text-white font-medium">{p.name}</p>
                    <p className="text-gray-400 text-xs mt-0.5">{p.note}</p>
                  </div>
                </div>

                {isConnected ? (
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 bg-green-400 rounded-full" />
                    <span className="text-green-400 text-xs font-medium">Connected</span>
                  </div>
                ) : (
                  <span className={`text-gray-400 text-sm transition ${isExpanded ? 'rotate-180' : ''}`}>
                    ▾
                  </span>
                )}
              </button>

              {isExpanded && !isConnected && (
                <div className="px-4 pb-4 border-t border-gray-700 pt-4">
                  <p className="text-gray-300 text-sm mb-3">{p.guidance}</p>

                  {p.link && (
                    <a
                      href={p.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-indigo-400 text-sm hover:text-indigo-300 transition mb-4"
                    >
                      {p.linkLabel}
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                      </svg>
                    </a>
                  )}

                  {/* Placeholder for future screenshot */}
                  <div className="bg-gray-900 border border-dashed border-gray-700 rounded-lg p-4 mb-4 text-center">
                    <p className="text-gray-500 text-xs">Screenshot guide coming soon</p>
                  </div>

                  {p.authType === 'api_key' ? (
                    <ApiKeyEntry provider={p.id} onConnected={reload} />
                  ) : (
                    <OAuthConnect provider={p.id} onConnected={reload} />
                  )}
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
