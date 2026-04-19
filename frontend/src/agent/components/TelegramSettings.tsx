/**
 * Chatty — TelegramSettings.
 * Guided onboarding wizard + management view for connecting
 * an agent to a Telegram bot.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../../core/api/client';

interface Props {
  agentId: string;
  agentName: string;
  botToken: string;
  botUsername: string;
  telegramEnabled: boolean;
  onUpdate: () => void;
}

type WizardStep = 'create-bot' | 'paste-token' | 'link-account' | 'all-set';

interface RegistrationWindow {
  agent_id: string;
  opened_at: string;
  expires_at: string;
  registered_user_id: string | null;
}

const TELEGRAM_BLUE = '#0088cc';

export function TelegramSettings({ agentId, agentName, botToken, botUsername, telegramEnabled, onUpdate }: Props) {
  // If already connected, show management view
  if (botToken) {
    return (
      <ManagementView
        agentId={agentId}
        agentName={agentName}
        botUsername={botUsername}
        telegramEnabled={telegramEnabled}
        onUpdate={onUpdate}
      />
    );
  }

  // Otherwise show onboarding wizard
  return (
    <OnboardingWizard
      agentId={agentId}
      agentName={agentName}
      onUpdate={onUpdate}
    />
  );
}


// ── Onboarding Wizard ─────────────────────────────────────────────────────────

function OnboardingWizard({ agentId, agentName, onUpdate }: {
  agentId: string;
  agentName: string;
  onUpdate: () => void;
}) {
  const [step, setStep] = useState<WizardStep>('create-bot');
  const [tokenInput, setTokenInput] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');
  const [connectedUsername, setConnectedUsername] = useState('');
  const [registrationExpires, setRegistrationExpires] = useState('');
  const [, setRegistrationComplete] = useState(false);

  const steps: WizardStep[] = ['create-bot', 'paste-token', 'link-account', 'all-set'];
  const currentIndex = steps.indexOf(step);

  async function handleConnect() {
    if (!tokenInput.trim()) return;
    setConnecting(true);
    setError('');
    try {
      const result = await api<{
        bot_username: string;
        webhook_ok: boolean;
        registration_expires_at: string;
      }>('/api/telegram/bot-token', {
        method: 'POST',
        body: JSON.stringify({ agent_id: agentId, bot_token: tokenInput.trim() }),
      });
      setConnectedUsername(result.bot_username);
      setRegistrationExpires(result.registration_expires_at);
      onUpdate();
      setStep('link-account');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to validate token');
    } finally {
      setConnecting(false);
    }
  }

  function handleRegistrationDone() {
    setRegistrationComplete(true);
    setStep('all-set');
  }

  return (
    <div className="max-w-lg mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl" style={{ backgroundColor: `${TELEGRAM_BLUE}20` }}>
          <TelegramIcon size={32} />
        </div>
        <h2 className="text-xl font-bold text-white">Connect to Telegram</h2>
        <p className="text-gray-400 text-sm">
          Let people message <span className="text-white font-medium">{agentName}</span> directly on Telegram
        </p>
      </div>

      {/* Progress dots */}
      <div className="flex justify-center gap-2">
        {steps.map((s, i) => (
          <div
            key={s}
            className={`w-2 h-2 rounded-full transition-all ${
              i === currentIndex
                ? 'w-6 bg-[#0088cc]'
                : i < currentIndex
                  ? 'bg-[#0088cc]/60'
                  : 'bg-gray-700'
            }`}
          />
        ))}
      </div>

      {/* Step content */}
      {step === 'create-bot' && (
        <StepCreateBot onNext={() => setStep('paste-token')} />
      )}

      {step === 'paste-token' && (
        <StepPasteToken
          tokenInput={tokenInput}
          setTokenInput={setTokenInput}
          connecting={connecting}
          error={error}
          onConnect={handleConnect}
          onBack={() => setStep('create-bot')}
        />
      )}

      {step === 'link-account' && (
        <StepLinkAccount
          botUsername={connectedUsername}
          expiresAt={registrationExpires}
          agentId={agentId}
          agentName={agentName}
          onDone={handleRegistrationDone}
        />
      )}

      {step === 'all-set' && (
        <StepAllSet
          agentName={agentName}
          botUsername={connectedUsername}
        />
      )}
    </div>
  );
}


// ── Step 1: Create Your Telegram Bot ──────────────────────────────────────────

function StepCreateBot({ onNext }: { onNext: () => void }) {
  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 space-y-4">
        <h3 className="text-white font-semibold text-base">Step 1: Create Your Telegram Bot</h3>

        <ol className="space-y-3 text-sm">
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">1</span>
            <span className="text-gray-300">Open Telegram and search for <span className="font-mono bg-gray-700 px-1.5 py-0.5 rounded text-white">@BotFather</span></span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">2</span>
            <span className="text-gray-300">Send <span className="font-mono bg-gray-700 px-1.5 py-0.5 rounded text-white">/newbot</span></span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">3</span>
            <span className="text-gray-300">Choose a name (e.g., "My Business Assistant")</span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">4</span>
            <span className="text-gray-300">Choose a username ending in <span className="font-mono bg-gray-700 px-1.5 py-0.5 rounded text-white">bot</span> (e.g., <span className="font-mono text-white">mybiz_assistant_bot</span>)</span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">5</span>
            <span className="text-gray-300">BotFather will give you a <span className="text-white font-medium">bot token</span> — copy it</span>
          </li>
        </ol>

        {/* Screenshot placeholder: BotFather conversation */}
        <div className="rounded-lg bg-gray-900 border border-gray-700 aspect-video flex items-center justify-center">
          <div className="text-center text-gray-500 text-sm">
            <div className="text-2xl mb-1">🤖</div>
            <div className="font-medium">BotFather Conversation</div>
            <div className="text-xs text-gray-600 mt-0.5">Screenshot placeholder</div>
          </div>
        </div>

        {/* Screenshot placeholder: Token response */}
        <div className="rounded-lg bg-gray-900 border border-gray-700 aspect-[16/7] flex items-center justify-center">
          <div className="text-center text-gray-500 text-sm">
            <div className="text-2xl mb-1">🔑</div>
            <div className="font-medium">Bot Token Response</div>
            <div className="text-xs text-gray-600 mt-0.5">Screenshot placeholder</div>
          </div>
        </div>
      </div>

      <button
        onClick={onNext}
        className="w-full py-3 rounded-xl font-semibold text-white transition hover:opacity-90"
        style={{ backgroundColor: TELEGRAM_BLUE }}
      >
        I have my bot token — Next
      </button>
    </div>
  );
}


// ── Step 2: Paste Your Bot Token ──────────────────────────────────────────────

function StepPasteToken({ tokenInput, setTokenInput, connecting, error, onConnect, onBack }: {
  tokenInput: string;
  setTokenInput: (v: string) => void;
  connecting: boolean;
  error: string;
  onConnect: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 space-y-4">
        <h3 className="text-white font-semibold text-base">Step 2: Paste Your Bot Token</h3>
        <p className="text-gray-400 text-sm">
          Paste the token that BotFather gave you. It looks like:
        </p>
        <div className="font-mono text-xs text-gray-500 bg-gray-900 rounded-lg px-3 py-2 border border-gray-700">
          123456789:ABCdefGHIjklMNOpqrsTUVwxyz
        </div>

        <input
          type="text"
          value={tokenInput}
          onChange={e => setTokenInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onConnect()}
          placeholder="Paste your bot token here"
          className="w-full bg-gray-900 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-[#0088cc] font-mono transition"
          autoFocus
        />

        {error && (
          <div className="bg-red-900/30 border border-red-800/50 rounded-lg px-3 py-2 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Screenshot placeholder: Where to find the token */}
        <div className="rounded-lg bg-gray-900 border border-gray-700 aspect-[16/7] flex items-center justify-center">
          <div className="text-center text-gray-500 text-sm">
            <div className="text-2xl mb-1">📋</div>
            <div className="font-medium">Where to Find the Token</div>
            <div className="text-xs text-gray-600 mt-0.5">Screenshot placeholder</div>
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex-1 py-3 rounded-xl font-semibold text-gray-400 border border-gray-700 hover:bg-gray-800 transition"
        >
          Back
        </button>
        <button
          onClick={onConnect}
          disabled={connecting || !tokenInput.trim()}
          className="flex-1 py-3 rounded-xl font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
          style={{ backgroundColor: TELEGRAM_BLUE }}
        >
          {connecting ? (
            <span className="flex items-center justify-center gap-2">
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Validating...
            </span>
          ) : 'Connect'}
        </button>
      </div>
    </div>
  );
}


// ── Step 3: Link Your Telegram Account ────────────────────────────────────────

function StepLinkAccount({ botUsername, expiresAt, agentId, agentName, onDone }: {
  botUsername: string;
  expiresAt: string;
  agentId: string;
  agentName: string;
  onDone: () => void;
}) {
  const [minutesLeft, setMinutesLeft] = useState(10);
  const [checking, setChecking] = useState(false);
  const [linked, setLinked] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Countdown timer
  useEffect(() => {
    if (!expiresAt) return;
    const update = () => {
      const diff = new Date(expiresAt).getTime() - Date.now();
      setMinutesLeft(Math.max(0, Math.ceil(diff / 60000)));
    };
    update();
    const interval = setInterval(update, 10000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  // Auto-poll registration status every 5 seconds
  useEffect(() => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await api<{ open: boolean; window: RegistrationWindow | null }>(`/api/telegram/registration-window/${agentId}`);
        if (res.window?.registered_user_id) {
          setLinked(true);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch { /* ignore */ }
    }, 5000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [agentId]);

  const handleCheck = useCallback(async () => {
    setChecking(true);
    try {
      const res = await api<{ open: boolean; window: RegistrationWindow | null }>(`/api/telegram/registration-window/${agentId}`);
      if (res.window?.registered_user_id) {
        setLinked(true);
      }
    } catch { /* ignore */ }
    finally { setChecking(false); }
  }, [agentId]);

  if (linked) {
    return (
      <div className="space-y-4">
        <div className="bg-green-900/20 border border-green-800/50 rounded-xl p-5 text-center space-y-3">
          <div className="text-4xl">🎉</div>
          <h3 className="text-white font-semibold text-lg">Account Linked!</h3>
          <p className="text-green-300 text-sm">
            Messages to <span className="font-mono font-bold">@{botUsername}</span> will be handled by <span className="font-bold">{agentName}</span>.
          </p>
        </div>
        <button
          onClick={onDone}
          className="w-full py-3 rounded-xl font-semibold text-white transition hover:opacity-90"
          style={{ backgroundColor: TELEGRAM_BLUE }}
        >
          Continue
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 space-y-4">
        <div className="flex items-center gap-2">
          <h3 className="text-white font-semibold text-base">Step 3: Link Your Telegram Account</h3>
          <span className="text-xs bg-green-900/40 text-green-400 border border-green-700/40 rounded-full px-2 py-0.5">
            Bot connected!
          </span>
        </div>

        <p className="text-gray-300 text-sm">
          Your bot <span className="font-mono font-bold text-white">@{botUsername}</span> is ready. Now link your Telegram account:
        </p>

        <ol className="space-y-3 text-sm">
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">1</span>
            <span className="text-gray-300">Open Telegram</span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">2</span>
            <span className="text-gray-300">Search for <span className="font-mono bg-gray-700 px-1.5 py-0.5 rounded text-white">@{botUsername}</span></span>
          </li>
          <li className="flex gap-3">
            <span className="flex-shrink-0 w-6 h-6 rounded-full bg-[#0088cc]/20 text-[#0088cc] flex items-center justify-center text-xs font-bold">3</span>
            <span className="text-gray-300">Send any message (e.g., "Hello!")</span>
          </li>
        </ol>

        {/* Timer */}
        <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2 border border-gray-700">
          <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
          <span className="text-yellow-300 text-sm">
            {minutesLeft > 0
              ? `Registration window open — ${minutesLeft} minute${minutesLeft !== 1 ? 's' : ''} remaining`
              : 'Registration window expired — reset below'}
          </span>
        </div>

        {/* Screenshot placeholders */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-gray-900 border border-gray-700 aspect-[4/3] flex items-center justify-center">
            <div className="text-center text-gray-500 text-xs">
              <div className="text-xl mb-1">🔍</div>
              <div>Search for bot</div>
              <div className="text-gray-600">Screenshot</div>
            </div>
          </div>
          <div className="rounded-lg bg-gray-900 border border-gray-700 aspect-[4/3] flex items-center justify-center">
            <div className="text-center text-gray-500 text-xs">
              <div className="text-xl mb-1">💬</div>
              <div>Send first message</div>
              <div className="text-gray-600">Screenshot</div>
            </div>
          </div>
        </div>
      </div>

      <button
        onClick={handleCheck}
        disabled={checking}
        className="w-full py-3 rounded-xl font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
        style={{ backgroundColor: TELEGRAM_BLUE }}
      >
        {checking ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Checking...
          </span>
        ) : "I've sent a message"}
      </button>
    </div>
  );
}


// ── Step 4: All Set ───────────────────────────────────────────────────────────

function StepAllSet({ agentName, botUsername }: {
  agentName: string;
  botUsername: string;
}) {
  return (
    <div className="space-y-4">
      <div className="bg-gradient-to-b from-[#0088cc]/10 to-transparent rounded-xl border border-[#0088cc]/30 p-6 text-center space-y-4">
        <div className="text-5xl">🚀</div>
        <h3 className="text-white font-bold text-xl">All Set!</h3>
        <p className="text-gray-300 text-sm">
          Your agent <span className="text-white font-bold">{agentName}</span> is now live on Telegram as{' '}
          <span className="font-mono font-bold text-[#0088cc]">@{botUsername}</span>
        </p>
        <p className="text-gray-400 text-xs">
          Messages sent to the bot will be answered by your agent with full access to tools and knowledge.
        </p>
      </div>

      <a
        href={`https://t.me/${botUsername}`}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full py-3 rounded-xl font-semibold text-white text-center transition hover:opacity-90"
        style={{ backgroundColor: TELEGRAM_BLUE }}
      >
        Open @{botUsername} in Telegram
      </a>
    </div>
  );
}


// ── Management View (already connected) ───────────────────────────────────────

function ManagementView({ agentId, agentName, botUsername, telegramEnabled, onUpdate }: {
  agentId: string;
  agentName: string;
  botUsername: string;
  telegramEnabled: boolean;
  onUpdate: () => void;
}) {
  const [toggling, setToggling] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showConfirmDisconnect, setShowConfirmDisconnect] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

  async function handleToggle() {
    setToggling(true);
    try {
      await api(`/api/agents/${agentId}`, {
        method: 'PUT',
        body: JSON.stringify({ telegram_enabled: !telegramEnabled }),
      });
      onUpdate();
    } finally { setToggling(false); }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    try {
      await api(`/api/telegram/bot-token/${agentId}`, { method: 'DELETE' });
      onUpdate();
    } finally {
      setDisconnecting(false);
      setShowConfirmDisconnect(false);
    }
  }

  async function handleResetRegistration() {
    setResetting(true);
    setResetSuccess(false);
    try {
      await api('/api/telegram/reset-registration', {
        method: 'POST',
        body: JSON.stringify({ agent_id: agentId }),
      });
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 5000);
    } finally { setResetting(false); }
  }

  return (
    <div className="max-w-lg mx-auto py-6 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: `${TELEGRAM_BLUE}20` }}>
          <TelegramIcon size={24} />
        </div>
        <div>
          <h2 className="text-white font-bold text-lg">Telegram</h2>
          <p className="text-gray-400 text-sm">{agentName}</p>
        </div>
      </div>

      {/* Status card */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-4 space-y-4">
        {/* Connected status */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${telegramEnabled ? 'bg-green-400' : 'bg-gray-500'}`} />
            <span className="text-white font-medium">@{botUsername}</span>
          </div>
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            telegramEnabled
              ? 'bg-green-900/40 text-green-400 border border-green-700/40'
              : 'bg-gray-700 text-gray-400 border border-gray-600'
          }`}>
            {telegramEnabled ? 'Active' : 'Disabled'}
          </span>
        </div>

        {/* Enable/disable toggle */}
        <div className="flex items-center justify-between py-2 border-t border-gray-700">
          <div>
            <p className="text-white text-sm font-medium">Telegram Messaging</p>
            <p className="text-gray-500 text-xs">Respond to messages on Telegram</p>
          </div>
          <button
            onClick={handleToggle}
            disabled={toggling}
            className={`relative w-11 h-6 rounded-full transition ${telegramEnabled ? 'bg-[#0088cc]' : 'bg-gray-600'} ${toggling ? 'opacity-50' : ''}`}
          >
            <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${telegramEnabled ? 'left-5' : 'left-0.5'}`} />
          </button>
        </div>

        {/* Open in Telegram */}
        <a
          href={`https://t.me/${botUsername}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-sm text-[#0088cc] hover:underline"
        >
          <span>Open in Telegram</span>
          <span className="text-xs">↗</span>
        </a>
      </div>

      {/* Registration management */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-4 space-y-3">
        <h3 className="text-white text-sm font-semibold">Account Linking</h3>
        <p className="text-gray-400 text-xs">
          Reset the registration window to link a different Telegram account to this agent.
        </p>
        <button
          onClick={handleResetRegistration}
          disabled={resetting}
          className="text-sm px-4 py-2 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50"
        >
          {resetting ? 'Resetting...' : 'Reset Registration Window'}
        </button>
        {resetSuccess && (
          <p className="text-green-400 text-xs">Registration window reopened for 10 minutes. Message the bot to link your account.</p>
        )}
      </div>

      {/* Disconnect */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-4 space-y-3">
        <h3 className="text-white text-sm font-semibold">Disconnect Bot</h3>
        <p className="text-gray-400 text-xs">
          Remove the Telegram bot connection. The bot will stop responding to messages.
        </p>
        {!showConfirmDisconnect ? (
          <button
            onClick={() => setShowConfirmDisconnect(true)}
            className="text-sm px-4 py-2 rounded-lg bg-red-900/30 text-red-400 border border-red-800/40 hover:bg-red-900/50 transition"
          >
            Disconnect
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={handleDisconnect}
              disabled={disconnecting}
              className="text-sm px-4 py-2 rounded-md border border-ch-coral/25 text-ch-coral bg-transparent hover:bg-ch-coral/10 transition disabled:opacity-50"
            >
              {disconnecting ? 'Disconnecting...' : 'Confirm Disconnect'}
            </button>
            <button
              onClick={() => setShowConfirmDisconnect(false)}
              className="text-sm px-4 py-2 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Telegram Icon ─────────────────────────────────────────────────────────────

function TelegramIcon({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"
        fill={TELEGRAM_BLUE}
      />
    </svg>
  );
}
