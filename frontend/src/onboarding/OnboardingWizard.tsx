import { useState, useEffect, useMemo } from 'react';
import { api } from '../core/api/client';
import type { ProviderStatus } from '../core/types';
import { StepIndicator } from './StepIndicator';
import { ProviderStep } from './steps/ProviderStep';
import { MessagingPickerStep } from './steps/MessagingPickerStep';
import { IntegrationPickerStep } from './steps/IntegrationPickerStep';
import { OdooSetupStep } from './steps/OdooSetupStep';
import { QuickBooksSetupStep } from './steps/QuickBooksSetupStep';
import { BambooHRSetupStep } from './steps/BambooHRSetupStep';
import { CrmLiteSetupStep } from './steps/CrmLiteSetupStep';
import { CompletionStep } from './steps/CompletionStep';

interface Props {
  onComplete: () => void;
}

type Phase = 'provider' | 'pick-messaging' | 'pick-integrations' | 'integration-setup' | 'done';

const INTEGRATION_ORDER = ['odoo', 'quickbooks', 'bamboohr', 'crm_lite'];

const INTEGRATION_TITLES: Record<string, string> = {
  odoo: 'Odoo',
  quickbooks: 'QuickBooks',
  bamboohr: 'BambooHR',
  crm_lite: 'CRM',
};

export function OnboardingWizard({ onComplete }: Props) {
  const [phase, setPhase] = useState<Phase>('provider');
  const [selectedMessaging, setSelectedMessaging] = useState<string[]>([]);
  const [selectedIntegrations, setSelectedIntegrations] = useState<string[]>([]);
  const [completedIntegrations, setCompletedIntegrations] = useState<string[]>([]);
  const [currentIntegrationIndex, setCurrentIntegrationIndex] = useState(0);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    api<ProviderStatus>('/api/providers').then(data => {
      setProviderStatus(data);
      // Skip provider step if already configured
      const anyConfigured = Object.values(data.profiles).some(p => p.configured);
      if (anyConfigured) setPhase('pick-messaging');
    }).catch(console.error);
  }, []);

  // Build step list for the indicator
  const steps = useMemo(() => {
    const s = [
      { id: 'provider', title: 'AI Provider' },
      { id: 'messaging', title: 'Messaging' },
      { id: 'integrations', title: 'Business Tools' },
    ];
    for (const id of selectedIntegrations) {
      s.push({ id, title: INTEGRATION_TITLES[id] || id });
    }
    if (selectedIntegrations.length > 0) {
      s.push({ id: 'done', title: 'Done' });
    }
    return s;
  }, [selectedIntegrations]);

  // Current step index for the indicator
  const currentStepIndex = useMemo(() => {
    if (phase === 'provider') return 0;
    if (phase === 'pick-messaging') return 1;
    if (phase === 'pick-integrations') return 2;
    if (phase === 'integration-setup') return 3 + currentIntegrationIndex;
    if (phase === 'done') return steps.length - 1;
    return 0;
  }, [phase, currentIntegrationIndex, steps.length]);

  // Get the active provider name for the completion screen
  const activeProvider = useMemo(() => {
    if (!providerStatus) return '';
    if (providerStatus.active_provider) return providerStatus.active_provider;
    // Find first configured provider
    for (const [name, profile] of Object.entries(providerStatus.profiles)) {
      if (profile.configured) return name;
    }
    return '';
  }, [providerStatus]);

  async function handleProviderComplete() {
    // Refresh provider status so completion screen shows accurate provider name
    try {
      const data = await api<ProviderStatus>('/api/providers');
      setProviderStatus(data);
    } catch { /* proceed anyway */ }
    setPhase('pick-messaging');
  }

  function handleMessagingPicked(ids: string[]) {
    setSelectedMessaging(ids);
    // Messaging setup is per-agent, so just record the selection and move on
    setPhase('pick-integrations');
  }

  function handleMessagingSkipped() {
    setPhase('pick-integrations');
  }

  function handleIntegrationsPicked(ids: string[]) {
    // Sort by our canonical order
    const sorted = INTEGRATION_ORDER.filter(id => ids.includes(id));
    setSelectedIntegrations(sorted);
    if (sorted.length === 0) {
      // Skip pressed or nothing selected — go straight to done/dashboard
      onComplete();
      return;
    }
    setCurrentIntegrationIndex(0);
    setPhase('integration-setup');
  }

  function handleIntegrationsSkipped() {
    onComplete();
  }

  function advanceIntegration(completed: boolean) {
    if (completed) {
      setCompletedIntegrations(prev => [...prev, selectedIntegrations[currentIntegrationIndex]]);
    }
    const nextIndex = currentIntegrationIndex + 1;
    if (nextIndex < selectedIntegrations.length) {
      setCurrentIntegrationIndex(nextIndex);
    } else {
      setPhase('done');
    }
  }

  // Render current integration setup step
  function renderIntegrationStep() {
    const integrationId = selectedIntegrations[currentIntegrationIndex];
    const stepProps = {
      onComplete: () => advanceIntegration(true),
      onSkip: () => advanceIntegration(false),
    };

    switch (integrationId) {
      case 'odoo': return <OdooSetupStep {...stepProps} />;
      case 'quickbooks': return <QuickBooksSetupStep {...stepProps} />;
      case 'bamboohr': return <BambooHRSetupStep {...stepProps} />;
      case 'crm_lite': return <CrmLiteSetupStep {...stepProps} />;
      default: return null;
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

        {phase === 'integration-setup' && renderIntegrationStep()}

        {phase === 'done' && (
          <CompletionStep
            result={{
              provider: activeProvider,
              integrations: [...selectedMessaging, ...completedIntegrations],
            }}
            onComplete={onComplete}
          />
        )}
      </div>
    </div>
  );
}
