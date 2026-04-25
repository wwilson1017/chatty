import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import { useOAuthFlow } from '../core/hooks/useOAuthFlow';
import { AppCredentialsForm } from './AppCredentialsForm';
import type {
  Integration,
  GmailScopeLevel,
  CalendarScopeLevel,
  DriveScopeLevel,
} from '../core/types';

interface Props {
  integration: Integration;
  onChanged: () => void;  // parent re-fetches integrations list
}

const GMAIL_OPTIONS: { value: GmailScopeLevel; label: string; hint: string }[] = [
  { value: 'none', label: 'Off',   hint: 'Don\'t request Gmail access' },
  { value: 'read', label: 'Read only', hint: 'Search, read messages, read threads' },
  { value: 'send', label: 'Read + send + draft', hint: 'Everything above plus compose, reply, save drafts' },
];

const CALENDAR_OPTIONS: { value: CalendarScopeLevel; label: string; hint: string }[] = [
  { value: 'none', label: 'Off', hint: 'Don\'t request Calendar access' },
  { value: 'read', label: 'Read only', hint: 'List and search events, check free/busy' },
  { value: 'full', label: 'Full access', hint: 'Everything above plus create, update, and delete events' },
];

const DRIVE_OPTIONS: { value: DriveScopeLevel; label: string; hint: string }[] = [
  { value: 'none',      label: 'Off', hint: 'Don\'t request Drive access' },
  { value: 'file',      label: 'App files only', hint: 'Chatty can read & upload files it creates. Minimal scope, no Google verification.' },
  { value: 'readonly',  label: 'Read only (all files)', hint: 'Search and read any Drive file. Requires Google OAuth verification.' },
  { value: 'full',      label: 'Full access', hint: 'Read, write, and delete any Drive file. Most powerful; requires verification.' },
];

export function GoogleIntegrationCard({ integration, onChanged }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [gmail, setGmail]       = useState<GmailScopeLevel>(integration.scope_grants?.gmail ?? 'none');
  const [calendar, setCalendar] = useState<CalendarScopeLevel>(integration.scope_grants?.calendar ?? 'none');
  const [drive, setDrive]       = useState<DriveScopeLevel>(integration.scope_grants?.drive ?? 'none');
  const [disconnecting, setDisconnecting] = useState(false);
  const [localError, setLocalError] = useState<string>('');
  const [showCredForm, setShowCredForm] = useState(false);
  const [existingCreds, setExistingCreds] = useState<{ client_id?: string; redirect_uri?: string; source?: 'stored' | 'env' }>({});
  const hasAppCreds = integration.has_app_credentials !== false;

  async function openCredForm() {
    setLocalError('');
    try {
      const existing = await api<{ configured: boolean; client_id?: string; redirect_uri?: string; source?: 'stored' | 'env' }>('/api/integrations/google/app-credentials');
      setExistingCreds(existing.configured
        ? { client_id: existing.client_id, redirect_uri: existing.redirect_uri, source: existing.source }
        : { redirect_uri: existing.redirect_uri });
    } catch { setExistingCreds({}); }
    setShowCredForm(true);
  }

  useEffect(() => {
    setGmail(integration.scope_grants?.gmail ?? 'none');
    setCalendar(integration.scope_grants?.calendar ?? 'none');
    setDrive(integration.scope_grants?.drive ?? 'none');
  }, [integration.scope_grants?.gmail, integration.scope_grants?.calendar, integration.scope_grants?.drive]);

  const oauth = useOAuthFlow();

  useEffect(() => {
    if (oauth.state.status === 'success') {
      setPickerOpen(false);
      onChanged();
      oauth.reset();
    }
  }, [oauth.state.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  const anyGranted = gmail !== 'none' || calendar !== 'none' || drive !== 'none';

  async function connect() {
    setLocalError('');
    if (!anyGranted) {
      setLocalError('Enable at least one of Gmail, Calendar, or Drive.');
      return;
    }
    await oauth.start({
      setupUrl: '/api/integrations/google/setup',
      setupBody: { gmail_level: gmail, calendar_level: calendar, drive_level: drive },
      completeUrl: '/api/integrations/google/setup/complete',
    });
  }

  async function disconnect() {
    setDisconnecting(true); setLocalError('');
    try {
      await api('/api/integrations/google/disconnect', { method: 'POST' });
      onChanged();
    } catch (err: unknown) {
      setLocalError(err instanceof Error ? err.message : 'Disconnect failed');
    } finally {
      setDisconnecting(false);
    }
  }

  const isRunning = oauth.state.status === 'starting' ||
                    oauth.state.status === 'awaiting_user' ||
                    oauth.state.status === 'completing';

  const isBroken = integration.configured && integration.connection_status === 'broken';
  const isConnected = integration.configured && !isBroken;

  // Grants label summary
  const grants = integration.scope_grants;
  const grantsSummary = grants ? [
    grants.gmail !== 'none' && `Gmail: ${grants.gmail === 'send' ? 'read+send' : grants.gmail}`,
    grants.calendar !== 'none' && `Calendar: ${grants.calendar}`,
    grants.drive !== 'none' && `Drive: ${grants.drive}`,
  ].filter(Boolean).join(' · ') : '';

  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{integration.icon}</span>
          <div>
            <p className="text-white font-medium">{integration.name}</p>
            <p className="text-gray-400 text-xs mt-0.5">{integration.description}</p>
            {isConnected && integration.email && (
              <p className="text-gray-300 text-xs mt-1">
                Connected as <span className="text-indigo-300">{integration.email}</span>
                {grantsSummary && <span className="text-gray-500 ml-2">· {grantsSummary}</span>}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isBroken && (
            <>
              <span className="text-xs text-red-400 bg-red-900/20 px-2 py-1 rounded">Connection lost</span>
              <button
                onClick={() => hasAppCreds ? setPickerOpen(true) : openCredForm()}
                disabled={isRunning}
                className="text-xs px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-500 transition disabled:opacity-50"
              >
                {hasAppCreds ? 'Reconnect' : 'Setup credentials'}
              </button>
            </>
          )}

          {!integration.configured && (
            <button
              onClick={() => {
                setLocalError('');
                if (hasAppCreds) setPickerOpen(true);
                else openCredForm();
              }}
              disabled={isRunning}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50"
            >
              {isRunning ? 'Connecting...' : hasAppCreds ? 'Connect' : 'Setup'}
            </button>
          )}

          {isConnected && (
            <>
              <button
                onClick={() => setPickerOpen(true)}
                disabled={isRunning || disconnecting}
                className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50"
              >
                Change scopes
              </button>
              <button
                onClick={openCredForm}
                className="text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-700 transition"
              >
                Edit credentials
              </button>
              <button
                onClick={disconnect}
                disabled={disconnecting || isRunning}
                className="text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-gray-700 transition disabled:opacity-50"
              >
                {disconnecting ? 'Disconnecting...' : 'Disconnect'}
              </button>
            </>
          )}
        </div>
      </div>

      {localError && <p className="mt-2 text-red-400 text-xs">{localError}</p>}
      {oauth.state.status === 'error' && oauth.state.error && (
        <p className="mt-2 text-red-400 text-xs">{oauth.state.error}</p>
      )}
      {isRunning && (
        <p className="mt-2 text-indigo-300 text-xs flex items-center gap-2">
          <span className="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin inline-block" />
          {oauth.state.status === 'starting' && 'Preparing authorization...'}
          {oauth.state.status === 'awaiting_user' && 'Complete authorization in the popup...'}
          {oauth.state.status === 'completing' && 'Finalizing connection...'}
        </p>
      )}

      {showCredForm && (
        <AppCredentialsForm
          integration="google"
          currentClientId={existingCreds.client_id}
          redirectUri={existingCreds.redirect_uri}
          source={existingCreds.source}
          onSaved={() => { setShowCredForm(false); onChanged(); }}
          onCancel={() => setShowCredForm(false)}
        />
      )}

      {pickerOpen && (
        <div className="mt-4 pt-4 border-t border-gray-700 space-y-4">
          <p className="text-gray-400 text-xs">
            Pick the access levels you want to grant Chatty. You can change these later by reconnecting.
            Chatty only requests the scopes you select on Google's consent screen.
          </p>

          <ScopeGroup
            title="Gmail"
            options={GMAIL_OPTIONS}
            value={gmail}
            onChange={(v) => setGmail(v as GmailScopeLevel)}
          />
          <ScopeGroup
            title="Google Calendar"
            options={CALENDAR_OPTIONS}
            value={calendar}
            onChange={(v) => setCalendar(v as CalendarScopeLevel)}
          />
          <ScopeGroup
            title="Google Drive"
            options={DRIVE_OPTIONS}
            value={drive}
            onChange={(v) => setDrive(v as DriveScopeLevel)}
          />

          <div className="flex gap-2 pt-2">
            <button
              onClick={() => setPickerOpen(false)}
              disabled={isRunning}
              className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={connect}
              disabled={isRunning || !anyGranted}
              className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50"
            >
              {isRunning ? 'Connecting...' : (isConnected ? 'Reconnect with these scopes' : 'Connect Google')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


interface ScopeGroupProps {
  title: string;
  options: { value: string; label: string; hint: string }[];
  value: string;
  onChange: (v: string) => void;
}

function ScopeGroup({ title, options, value, onChange }: ScopeGroupProps) {
  return (
    <div>
      <p className="text-white text-sm font-medium mb-2">{title}</p>
      <div className="space-y-1.5">
        {options.map(opt => (
          <label
            key={opt.value}
            className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer transition ${
              value === opt.value ? 'bg-indigo-900/30 border border-indigo-700' : 'bg-gray-900/50 border border-transparent hover:bg-gray-900'
            }`}
          >
            <input
              type="radio"
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="mt-0.5 accent-indigo-500"
            />
            <div>
              <p className="text-white text-xs font-medium">{opt.label}</p>
              <p className="text-gray-400 text-[11px] leading-snug">{opt.hint}</p>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}
