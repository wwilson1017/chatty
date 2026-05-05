import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import { useOAuthFlow } from '../core/hooks/useOAuthFlow';
import { AppCredentialsForm } from './AppCredentialsForm';
import type {
  Integration,
  Agent,
  GoogleAccount,
  GmailScopeLevel,
  CalendarScopeLevel,
  DriveScopeLevel,
} from '../core/types';

interface Props {
  integration: Integration;
  onChanged: () => void;
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

function scopeSummary(grants: GoogleAccount['scope_grants']) {
  return [
    grants.gmail !== 'none' && `Gmail: ${grants.gmail === 'send' ? 'read+send' : grants.gmail}`,
    grants.calendar !== 'none' && `Calendar: ${grants.calendar}`,
    grants.drive !== 'none' && `Drive: ${grants.drive}`,
  ].filter(Boolean).join(' \u00b7 ');
}

export function GoogleIntegrationCard({ integration, onChanged }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [editingAccountId, setEditingAccountId] = useState('');
  const [gmail, setGmail]       = useState<GmailScopeLevel>('none');
  const [calendar, setCalendar] = useState<CalendarScopeLevel>('none');
  const [drive, setDrive]       = useState<DriveScopeLevel>('none');
  const [disconnecting, setDisconnecting] = useState('');
  const [localError, setLocalError] = useState('');
  const [showCredForm, setShowCredForm] = useState(false);
  const [existingCreds, setExistingCreds] = useState<{ client_id?: string; redirect_uri?: string; source?: 'stored' | 'env' }>({});
  const [assignmentsOpen, setAssignmentsOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [savingAgent, setSavingAgent] = useState('');
  const hasAppCreds = integration.has_app_credentials !== false;
  const accounts = integration.google_accounts || [];

  const oauth = useOAuthFlow();

  useEffect(() => {
    if (oauth.state.status === 'success') {
      setPickerOpen(false);
      setEditingAccountId('');
      onChanged();
      oauth.reset();
    }
  }, [oauth.state.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (assignmentsOpen && agents.length === 0) {
      api<{ agents: Agent[] }>('/api/agents').then(data => setAgents(data.agents)).catch(() => {});
    }
  }, [assignmentsOpen]); // eslint-disable-line react-hooks/exhaustive-deps

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

  function openScopePicker(accountId: string = '', acct?: GoogleAccount) {
    setEditingAccountId(accountId);
    setGmail(acct?.scope_grants?.gmail ?? 'none');
    setCalendar(acct?.scope_grants?.calendar ?? 'none');
    setDrive(acct?.scope_grants?.drive ?? 'none');
    setPickerOpen(true);
    setLocalError('');
  }

  const anyGranted = gmail !== 'none' || calendar !== 'none' || drive !== 'none';

  async function connect() {
    setLocalError('');
    if (!anyGranted) {
      setLocalError('Enable at least one of Gmail, Calendar, or Drive.');
      return;
    }
    const base = editingAccountId
      ? `/api/integrations/google/${editingAccountId}/setup`
      : '/api/integrations/google/setup';
    const complete = editingAccountId
      ? `/api/integrations/google/${editingAccountId}/setup/complete`
      : '/api/integrations/google/setup/complete';
    await oauth.start({
      setupUrl: base,
      setupBody: { gmail_level: gmail, calendar_level: calendar, drive_level: drive },
      completeUrl: complete,
    });
  }

  async function disconnectAccount(accountId: string) {
    setDisconnecting(accountId); setLocalError('');
    try {
      await api(`/api/integrations/google/${accountId}/disconnect`, { method: 'POST' });
      onChanged();
      setAgents([]);
    } catch (err: unknown) {
      setLocalError(err instanceof Error ? err.message : 'Disconnect failed');
    } finally {
      setDisconnecting('');
    }
  }

  async function updateAgentAccount(agentId: string, service: 'gmail' | 'calendar' | 'drive', accountId: string) {
    setSavingAgent(agentId);
    const agent = agents.find(a => a.id === agentId);
    const current = agent?.google_accounts || {};
    const updated = { ...current, [service]: accountId };
    try {
      await api(`/api/agents/${agentId}`, {
        method: 'PUT',
        body: JSON.stringify({ google_accounts: updated }),
      });
      const data = await api<{ agents: Agent[] }>('/api/agents');
      setAgents(data.agents);
    } catch (err: unknown) {
      setLocalError(err instanceof Error ? err.message : 'Failed to update agent');
    } finally {
      setSavingAgent('');
    }
  }

  function accountsForService(service: 'gmail' | 'calendar' | 'drive') {
    return accounts.filter(a => {
      const g = a.scope_grants;
      if (service === 'gmail') return g.gmail !== 'none';
      if (service === 'calendar') return g.calendar !== 'none';
      return g.drive !== 'none';
    });
  }

  const isRunning = oauth.state.status === 'starting' ||
                    oauth.state.status === 'awaiting_user' ||
                    oauth.state.status === 'completing';

  return (
    <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{integration.icon}</span>
          <div>
            <p className="text-white font-medium">{integration.name}</p>
            <p className="text-gray-400 text-xs mt-0.5">
              {accounts.length === 0
                ? integration.description
                : `${accounts.length} account${accounts.length > 1 ? 's' : ''} connected`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {accounts.length === 0 && !hasAppCreds && (
            <button onClick={openCredForm} disabled={isRunning}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50">
              Setup
            </button>
          )}
          {accounts.length === 0 && hasAppCreds && (
            <button onClick={() => openScopePicker()} disabled={isRunning}
              className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition disabled:opacity-50">
              {isRunning ? 'Connecting...' : 'Connect'}
            </button>
          )}
          {accounts.length > 0 && (
            <>
              <button onClick={() => openScopePicker()} disabled={isRunning}
                className="text-xs px-3 py-1.5 rounded-lg bg-brand text-white hover:opacity-90 transition disabled:opacity-50">
                + Add Account
              </button>
              <button onClick={openCredForm}
                className="text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-700 transition">
                Edit credentials
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error / OAuth status */}
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

      {/* App credentials form */}
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

      {/* Connected accounts list */}
      {accounts.length > 0 && (
        <div className="mt-3 space-y-2">
          {accounts.map(acct => (
            <div key={acct.id} className="flex items-center justify-between bg-gray-900/50 rounded-lg px-3 py-2">
              <div>
                <p className="text-white text-xs font-medium">
                  {acct.email}
                  {acct.connection_status === 'broken' && (
                    <span className="ml-2 text-red-400 text-[10px] bg-red-900/20 px-1.5 py-0.5 rounded">Connection lost</span>
                  )}
                </p>
                <p className="text-gray-500 text-[11px] mt-0.5">{scopeSummary(acct.scope_grants)}</p>
              </div>
              <div className="flex items-center gap-1.5">
                <button onClick={() => openScopePicker(acct.id, acct)} disabled={isRunning}
                  className="text-[11px] px-2 py-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition disabled:opacity-50">
                  {acct.connection_status === 'broken' ? 'Reconnect' : 'Change scopes'}
                </button>
                <button onClick={() => disconnectAccount(acct.id)} disabled={disconnecting === acct.id || isRunning}
                  className="text-[11px] px-2 py-1 rounded text-gray-500 hover:text-red-400 hover:bg-gray-700 transition disabled:opacity-50">
                  {disconnecting === acct.id ? '...' : 'Disconnect'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Agent Assignments */}
      {accounts.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setAssignmentsOpen(!assignmentsOpen)}
            className="text-xs text-gray-400 hover:text-gray-200 transition flex items-center gap-1">
            <span className={`transition-transform ${assignmentsOpen ? 'rotate-90' : ''}`}>&#9654;</span>
            Agent Assignments
          </button>
          {assignmentsOpen && (
            <div className="mt-2 space-y-2">
              {agents.length === 0 && <p className="text-gray-500 text-xs">No agents created yet.</p>}
              {agents.map(agent => {
                const ga = agent.google_accounts || {};
                return (
                  <div key={agent.id} className="bg-gray-900/30 rounded-lg px-3 py-2">
                    <p className="text-white text-xs font-medium mb-1.5">{agent.agent_name}</p>
                    <div className="grid grid-cols-3 gap-2">
                      {(['gmail', 'calendar', 'drive'] as const).map(svc => {
                        const available = accountsForService(svc);
                        return (
                          <div key={svc}>
                            <label className="text-gray-500 text-[10px] uppercase tracking-wide block mb-0.5">
                              {svc === 'gmail' ? 'Gmail' : svc === 'calendar' ? 'Calendar' : 'Drive'}
                            </label>
                            <select
                              value={ga[svc] || ''}
                              onChange={e => updateAgentAccount(agent.id, svc, e.target.value)}
                              disabled={savingAgent === agent.id}
                              className="w-full bg-gray-800 text-gray-300 text-[11px] rounded px-1.5 py-1 border border-gray-700 focus:border-indigo-500 outline-none disabled:opacity-50"
                            >
                              <option value="">None</option>
                              {available.map(a => (
                                <option key={a.id} value={a.id}>{a.email}</option>
                              ))}
                            </select>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Scope picker panel */}
      {pickerOpen && (
        <div className="mt-4 pt-4 border-t border-gray-700 space-y-4">
          <p className="text-gray-400 text-xs">
            {editingAccountId
              ? 'Update the access levels for this account. You\'ll re-authorize on Google\'s consent screen.'
              : 'Pick the access levels for the new Google account.'}
          </p>
          <ScopeGroup title="Gmail" options={GMAIL_OPTIONS} value={gmail}
            onChange={(v) => setGmail(v as GmailScopeLevel)} />
          <ScopeGroup title="Google Calendar" options={CALENDAR_OPTIONS} value={calendar}
            onChange={(v) => setCalendar(v as CalendarScopeLevel)} />
          <ScopeGroup title="Google Drive" options={DRIVE_OPTIONS} value={drive}
            onChange={(v) => setDrive(v as DriveScopeLevel)} />

          <div className="flex gap-2 pt-2">
            <button onClick={() => { setPickerOpen(false); setEditingAccountId(''); }} disabled={isRunning}
              className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition disabled:opacity-50">
              Cancel
            </button>
            <button onClick={connect} disabled={isRunning || !anyGranted}
              className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50">
              {isRunning ? 'Connecting...' : editingAccountId ? 'Reconnect' : 'Connect Google Account'}
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
