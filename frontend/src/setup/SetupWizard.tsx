/**
 * Chatty — First-login setup wizard.
 *
 * Walks user through AI provider setup and branding configuration.
 * Each step can be skipped; the entire wizard can be dismissed.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { ProviderSetup } from './ProviderSetup';
import type { BrandingConfig } from '../core/types';

type Step = 'welcome' | 'providers' | 'branding';

const STEPS: Step[] = ['welcome', 'providers', 'branding'];

export function SetupWizard() {
  const [step, setStep] = useState<Step>('welcome');
  const navigate = useNavigate();

  // Branding state
  const [companyName, setCompanyName] = useState('');
  const [accentColor, setAccentColor] = useState('#393c74');
  const [logoUploaded, setLogoUploaded] = useState(false);
  const [saving, setSaving] = useState(false);

  const stepIndex = STEPS.indexOf(step);

  function nextStep() {
    if (stepIndex < STEPS.length - 1) {
      setStep(STEPS[stepIndex + 1]);
    }
  }

  async function finish() {
    try {
      await api('/api/setup/complete', { method: 'POST' });
    } catch { /* navigate regardless */ }
    navigate('/');
  }

  async function skipAll() {
    try {
      await api('/api/setup/skip', { method: 'POST' });
    } catch { /* navigate regardless */ }
    navigate('/');
  }

  async function saveBranding() {
    setSaving(true);
    try {
      const body: Record<string, string> = {};
      if (companyName.trim()) body.company_name = companyName.trim();
      if (accentColor) body.accent_color = accentColor;

      if (Object.keys(body).length > 0) {
        const updated = await api<BrandingConfig>('/api/branding', {
          method: 'PUT',
          body: JSON.stringify(body),
        });
        document.documentElement.style.setProperty('--brand-color', updated.accent_color);
      }
      await finish();
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
    if (res.ok) setLogoUploaded(true);
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {STEPS.map((s, i) => (
            <div
              key={s}
              className={`h-1.5 rounded-full transition-all ${
                i <= stepIndex ? 'bg-brand w-10' : 'bg-gray-700 w-6'
              }`}
            />
          ))}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8">
          {/* Welcome */}
          {step === 'welcome' && (
            <div className="text-center space-y-6">
              <div className="text-5xl">&#x1f680;</div>
              <h1 className="text-2xl font-bold text-white">Welcome to your AI workspace</h1>
              <p className="text-gray-400">
                Let's get you set up. We'll connect an AI provider and customize your platform.
                You can always change these settings later.
              </p>
              <div className="space-y-3 pt-2">
                <button
                  onClick={nextStep}
                  className="w-full py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition"
                >
                  Get Started
                </button>
                <button
                  onClick={skipAll}
                  className="w-full py-3 text-gray-400 hover:text-white text-sm transition"
                >
                  Skip setup — I'll do this later
                </button>
              </div>
            </div>
          )}

          {/* AI Providers */}
          {step === 'providers' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-white">Connect an AI provider</h2>
                <p className="text-gray-400 text-sm mt-1">
                  Your agents need at least one AI provider to work. Connect one or more below.
                </p>
              </div>

              <ProviderSetup />

              <div className="flex gap-3 pt-2">
                <button
                  onClick={nextStep}
                  className="flex-1 py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition"
                >
                  Continue
                </button>
                <button
                  onClick={nextStep}
                  className="py-3 px-5 text-gray-400 hover:text-white text-sm rounded-xl hover:bg-gray-800 transition"
                >
                  Skip
                </button>
              </div>
            </div>
          )}

          {/* Branding */}
          {step === 'branding' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-white">Customize your platform</h2>
                <p className="text-gray-400 text-sm mt-1">
                  Give your workspace a name, color, and logo. All optional.
                </p>
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-2">Platform name</label>
                <input
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  placeholder="My Company"
                  className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 focus:outline-none focus:border-brand placeholder-gray-500"
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
                {logoUploaded && (
                  <p className="text-green-400 text-sm mb-2">Logo uploaded</p>
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

              <div className="flex gap-3 pt-2">
                <button
                  onClick={saveBranding}
                  disabled={saving}
                  className="flex-1 py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Finish Setup'}
                </button>
                <button
                  onClick={skipAll}
                  className="py-3 px-5 text-gray-400 hover:text-white text-sm rounded-xl hover:bg-gray-800 transition"
                >
                  Skip
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
