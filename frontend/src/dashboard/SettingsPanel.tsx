import { useState } from 'react';
import { api } from '../core/api/client';
import type { BrandingConfig } from '../core/types';
import { ProviderSetup } from '../setup/ProviderSetup';
import { IntegrationsTab } from './IntegrationsTab';
import { DataTab } from './DataTab';

interface Props {
  branding: BrandingConfig | null;
  onBrandingUpdate: (b: BrandingConfig) => void;
  onClose: () => void;
}

type Tab = 'providers' | 'branding' | 'integrations' | 'chat' | 'data';

export function SettingsPanel({ branding, onBrandingUpdate, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('providers');
  const [companyName, setCompanyName] = useState(branding?.company_name || '');
  const [accentColor, setAccentColor] = useState(branding?.accent_color || '#393c74');
  const [saving, setSaving] = useState(false);
  const [showToolCalls, setShowToolCalls] = useState(() =>
    localStorage.getItem('chatty_show_tool_calls') === 'true'
  );

  async function saveBranding() {
    setSaving(true);
    try {
      const updated = await api<BrandingConfig>('/api/branding', {
        method: 'PUT',
        body: JSON.stringify({ company_name: companyName, accent_color: accentColor }),
      });
      onBrandingUpdate(updated);
      document.documentElement.style.setProperty('--brand-color', updated.accent_color);
    } finally {
      setSaving(false);
    }
  }

  async function uploadLogo(file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/branding/logo', {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionStorage.getItem('chatty_token')}` },
      body: form,
    });
    if (!res.ok) throw new Error('Upload failed');
    onBrandingUpdate({ ...branding!, has_logo: true });
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'providers', label: 'AI Providers' },
    { id: 'branding', label: 'Branding' },
    { id: 'integrations', label: 'Integrations' },
    { id: 'chat', label: 'Chat' },
    { id: 'data', label: 'Data' },
  ];

  return (
    <div className="fixed inset-0 bg-black/60 flex items-start justify-end z-50">
      <div className="bg-gray-900 border-l border-gray-800 w-full max-w-xl h-full flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <h2 className="text-white font-bold text-lg">Settings</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none transition">×</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex-1 py-3 text-sm font-medium transition ${
                tab === t.id
                  ? 'text-white border-b-2 border-brand'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'providers' && <ProviderSetup />}

          {tab === 'branding' && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Company / Platform name</label>
                <input
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-2">Accent color</label>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    value={accentColor}
                    onChange={e => setAccentColor(e.target.value)}
                    className="w-12 h-12 rounded-lg border-0 cursor-pointer bg-transparent"
                  />
                  <span className="text-gray-300 font-mono text-sm">{accentColor}</span>
                </div>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-2">Logo</label>
                {branding?.has_logo && (
                  <div className="mb-3">
                    <img src="/api/branding/logo" alt="Logo" className="h-12 rounded-lg" />
                  </div>
                )}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                  onChange={e => {
                    const file = e.target.files?.[0];
                    if (file) uploadLogo(file).catch(console.error);
                  }}
                  className="text-sm text-gray-400"
                />
              </div>

              <button
                onClick={saveBranding}
                disabled={saving}
                className="w-full py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save Branding'}
              </button>
            </div>
          )}

          {tab === 'integrations' && <IntegrationsTab />}

          {tab === 'chat' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white text-sm font-medium">Show tool calls</p>
                  <p className="text-gray-500 text-xs mt-0.5">Display tool call details in chat messages</p>
                </div>
                <button
                  onClick={() => {
                    const next = !showToolCalls;
                    setShowToolCalls(next);
                    localStorage.setItem('chatty_show_tool_calls', String(next));
                  }}
                  className={`relative w-11 h-6 rounded-full transition ${showToolCalls ? 'bg-indigo-600' : 'bg-gray-600'}`}
                >
                  <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${showToolCalls ? 'left-5' : 'left-0.5'}`} />
                </button>
              </div>
            </div>
          )}

          {tab === 'data' && <DataTab />}
        </div>
      </div>
    </div>
  );
}
