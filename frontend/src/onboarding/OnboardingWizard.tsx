import { useState, useEffect, useMemo } from 'react';
import { api } from '../core/api/client';
import type { ProviderStatus } from '../core/types';
import { StepIndicator } from './StepIndicator';
import { ProviderStep } from './steps/ProviderStep';
import { MessagingPickerStep } from './steps/MessagingPickerStep';
import { IntegrationPickerStep } from './steps/IntegrationPickerStep';
import { CompletionStep } from './steps/CompletionStep';

interface Props {
  onComplete: () => void;
}

type Phase = 'provider' | 'pick-messaging' | 'pick-integrations' | 'done';

const INTEGRATION_ORDER = ['odoo', 'quickbooks', 'bamboohr', 'crm_lite'];

export function OnboardingWizard({ onComplete }: Props) {
  const [phase, setPhase] = useState<Phase>('provider');
  const [selectedMessaging, setSelectedMessaging] = useState<string[]>([]);
  const [selectedIntegrations, setSelectedIntegrations] = useState<string[]>([]);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    api<ProviderStatus>('/api/providers').then(data => {
      setProviderStatus(data);
      const anyConfigured = Object.values(data.profiles).some(p => p.configured);
      if (anyConfigured) setPhase('pick-messaging');
    }).catch(console.error);
  }, []);

  const steps = useMemo(() => {
    const s = [
      { id: 'provider', title: 'AI Provider' },
      { id: 'messaging', title: 'Messaging' },
      { id: 'integrations', title: 'Business Tools' },
    ];
    if (selectedMessaging.length > 0 || selectedIntegrations.length > 0) {
      s.push({ id: 'done', title: 'Done' });
    }
    return s;
  }, [selectedMessaging, selectedIntegrations]);

  const currentStepIndex = useMemo(() => {
    if (phase === 'provider') return 0;
    if (phase === 'pick-messaging') return 1;
    if (phase === 'pick-integrations') return 2;
    if (phase === 'done') return steps.length - 1;
    return 0;
  }, [phase, steps.length]);

  const activeProvider = useMemo(() => {
    if (!providerStatus) return '';
    if (providerStatus.active_provider) return providerStatus.active_provider;
    for (const [, profile] of Object.entries(providerStatus.profiles)) {
      if (profile.configured) return providerStatus.active_provider;
    }
    return '';
  }, [providerStatus]);

  async function handleProviderComplete() {
    try {
      const data = await api<ProviderStatus>('/api/providers');
      setProviderStatus(data);
    } catch { /* proceed anyway */ }
    setPhase('pick-messaging');
  }

  function handleMessagingPicked(ids: string[]) {
    setSelectedMessaging(ids);
    setPhase('pick-integrations');
  }

  function handleMessagingSkipped() {
    setPhase('pick-integrations');
  }

  async function handleIntegrationsPicked(ids: string[]) {
    const sorted = INTEGRATION_ORDER.filter(id => ids.includes(id));
    setSelectedIntegrations(sorted);

    const hasPending = selectedMessaging.length > 0 || sorted.length > 0;
    if (hasPending) {
      try {
        await api('/api/integrations/pending-setup', {
          method: 'POST',
          body: JSON.stringify({
            messaging: selectedMessaging,
            integrations: sorted,
          }),
        });
      } catch (e) {
        console.error('Failed to save pending setup:', e);
      }
      setPhase('done');
    } else {
      onComplete();
    }
  }

  async function handleIntegrationsSkipped() {
    if (selectedMessaging.length > 0) {
      try {
        await api('/api/integrations/pending-setup', {
          method: 'POST',
          body: JSON.stringify({
            messaging: selectedMessaging,
            integrations: [],
          }),
        });
      } catch (e) {
        console.error('Failed to save pending setup:', e);
      }
      setPhase('done');
    } else {
      onComplete();
    }
  }

  return (
    <div>
      <StepIndicator steps={steps} currentIndex={currentStepIndex} />

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 sm:p-8">
        {phase === 'provider' && (
          <ProviderStep onComplete={handleProviderComplete} />
        )}

        {phase === 'pick-messaging' && (
          <MessagingPickerStep
            onComplete={handleMessagingPicked}
            onSkip={handleMessagingSkipped}
          />
        )}

        {phase === 'pick-integrations' && (
          <IntegrationPickerStep
            onComplete={handleIntegrationsPicked}
            onSkip={handleIntegrationsSkipped}
          />
        )}

        {phase === 'done' && (
          <CompletionStep
            result={{
              provider: activeProvider,
              pendingMessaging: selectedMessaging,
              pendingIntegrations: selectedIntegrations,
            }}
            onComplete={onComplete}
          />
        )}
      </div>
    </div>
  );
}
