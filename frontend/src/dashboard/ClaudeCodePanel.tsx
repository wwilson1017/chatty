/**
 * Chatty — Claude Code connector card body: pairing, status, agent access, recent jobs.
 * Rendered inside the claude_code integration card in IntegrationsTab.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../core/api/client';
import { confirmDialog } from '../shared/confirm';
import { useCopyToClipboard } from '../shared/useCopyToClipboard';
import { INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, BG_RAISED, CORAL, SAGE, GOLD, FONT_MONO, mono } from '../shared/styles';
import type { Agent } from '../core/types';

interface Status {
  paired: boolean;
  online: boolean;
  host: string;
  last_seen: number | null;
  version: string | null;
  runners: Record<string, unknown>;
  capabilities: string | null;
  disabled_agents: string[];
}

interface Job {
  id: string;
  agent_slug: string;
  origin: string;
  runner: string;
  mode: string;
  status: string;
  task: string;
  finish_reason: string | null;
  error: string | null;
  session_id: string | null;
  created_at: string;
  claimed_at: string | null;
  finished_at: string | null;
  result_text: string;
  result_truncated: boolean;
}

// Job timestamps are SQLite datetime('now') — UTC without a zone marker; last_seen is epoch seconds.
function toMs(t: string | number | null): number | null {
  if (t == null || t === '') return null;
  if (typeof t === 'number') return t * 1000;
  return Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(t) ? t : t.replace(' ', 'T') + 'Z');
}

function fmtTime(t: string | number | null): string {
  const ms = toMs(t);
  return ms == null ? '—' : new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function fmtDuration(job: Job): string {
  const start = toMs(job.claimed_at);
  if (start == null) return '—';
  const s = Math.max(0, Math.round(((toMs(job.finished_at) ?? Date.now()) - start) / 1000));
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const smallBtn: React.CSSProperties = {
  fontSize: 11, padding: '4px 10px', borderRadius: 4,
  background: 'transparent', color: INK_MUTE, border: `1px solid ${LINE_STRONG}`, cursor: 'pointer',
};
const pre: React.CSSProperties = {
  margin: 0, padding: 8, borderRadius: 4, background: BG_RAISED, color: INK,
  fontFamily: FONT_MONO, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
};

function CopyLine({ text }: { text: string }) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
      <code style={{ ...pre, flex: 1 }}>{text}</code>
      <button onClick={() => copy(text)} aria-label={`Copy: ${text}`} style={smallBtn}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  );
}

export function ClaudeCodePanel({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const pairedRef = useRef<boolean | null>(null);

  const load = useCallback(() => {
    // best-effort polling: a missed tick just shows the previous state
    api<Status>('/api/integrations/claude_code/status').then(s => {
      setStatus(s);
      // pairing/unpairing changes the card's configured/enabled flags
      if (pairedRef.current !== null && pairedRef.current !== s.paired) onChanged();
      pairedRef.current = s.paired;
    }).catch(() => {});
    api<{ jobs: Job[] }>('/api/integrations/claude_code/jobs?limit=20').then(d => setJobs(d.jobs)).catch(() => {});
  }, [onChanged]);

  // Poll fast while a pair code is showing so the card flips to paired on its own.
  const waiting = !!code && !status?.paired;
  useEffect(() => {
    load();
    const t = setInterval(load, waiting ? 3000 : 10000);
    return () => clearInterval(t);
  }, [load, waiting]);

  useEffect(() => {
    api<{ agents: Agent[] }>('/api/agents').then(d => setAgents(d.agents)).catch(() => {});
  }, []);

  async function run(fn: () => Promise<unknown>) {
    setError('');
    try { await fn(); } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Request failed'); }
    load();
  }

  const connect = () => run(async () => {
    setCode(await api('/api/integrations/claude_code/pair-code', { method: 'POST' }));
    onChanged();
  });

  const disconnect = async () => {
    if (!await confirmDialog({
      title: 'Disconnect Claude Code',
      message: 'Revokes the connector and stops its jobs when the connector next checks in.',
      confirmLabel: 'Disconnect', danger: true,
    })) return;
    setCode(null);
    await run(() => api('/api/integrations/claude_code/disconnect', { method: 'POST' }));
  };

  const toggleAgent = (slug: string, allowed: boolean) => run(async () => {
    const current = status?.disabled_agents ?? [];
    const next = allowed ? current.filter(s => s !== slug) : [...current, slug];
    const res = await api<{ disabled_agents: string[] }>('/api/integrations/claude_code/agents', {
      method: 'PUT', body: JSON.stringify({ disabled_agents: next }),
    });
    setStatus(s => s && { ...s, disabled_agents: res.disabled_agents });
  });

  const origin = window.location.origin;
  const agentName = (slug: string) => slug ? (agents.find(a => a.slug === slug)?.agent_name ?? slug) : 'system';

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${LINE}`, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12, color: INK_MUTE }}>
      {error && <p role="alert" style={{ color: CORAL, margin: 0 }}>{error}</p>}

      {status && !status.paired && (code ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <p style={{ margin: 0 }}>
            Pair code <strong style={{ color: INK, fontFamily: FONT_MONO }}>{code.code}</strong> — expires {fmtTime(code.expires_at)}.
            Run these on the computer with Claude Code:
          </p>
          <CopyLine text={'uv tool install "git+https://github.com/WWilson1017/chatty#subdirectory=connector"'} />
          <CopyLine text={`chatty-connector pair ${origin} ${code.code}`} />
          <CopyLine text="chatty-connector doctor" />
          <CopyLine text="chatty-connector install-service" />
          <p style={{ margin: 0, color: INK_DIM }}>Waiting for the connector to pair…</p>
        </div>
      ) : (
        <div><button onClick={connect} style={smallBtn}>Connect</button></div>
      ))}

      {status?.paired && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span aria-hidden style={{ width: 6, height: 6, borderRadius: '50%', background: status.online ? SAGE : INK_DIM }} />
            <span style={{ color: INK }}>{status.online ? 'Online' : 'Offline'}</span>
            <span>{status.host || 'unknown host'}</span>
            <span>· {Object.keys(status.runners).join(', ') || 'no runners'}</span>
            {status.version && <span>· v{status.version}</span>}
            <span>· last seen {fmtTime(status.last_seen)}</span>
            <button onClick={disconnect} style={{ ...smallBtn, marginLeft: 'auto', color: CORAL, borderColor: 'transparent' }}>Disconnect</button>
          </div>

          <details>
            <summary style={{ ...mono(9, INK_MUTE), cursor: 'pointer' }}>Capabilities</summary>
            <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <pre style={pre}>{status.capabilities || 'Not reported yet.'}</pre>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={() => run(async () => {
                  await api('/api/integrations/claude_code/capabilities/refresh', { method: 'POST' });
                  setNote('Refresh queued — updates when the connector runs it.');
                })} style={smallBtn}>Refresh</button>
                {note && <span style={{ color: INK_DIM }}>{note}</span>}
              </div>
            </div>
          </details>

          {agents.length > 0 && <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
            <legend style={{ ...mono(9), marginBottom: 4 }}>Agents that can delegate</legend>
            {agents.map(a => (
              <label key={a.slug} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="checkbox" checked={!status.disabled_agents.includes(a.slug)}
                  onChange={e => toggleAgent(a.slug, e.target.checked)} />
                {a.agent_name}
              </label>
            ))}
          </fieldset>}
        </>
      )}

      {jobs.length > 0 && (
        <div>
          <p style={{ ...mono(9), margin: '0 0 4px' }}>Recent jobs</p>
          {jobs.map(j => (
            <details key={j.id} style={{ borderTop: `1px solid ${LINE}`, padding: '4px 0' }}>
              <summary style={{ cursor: 'pointer', display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'center' }}>
                <span>{fmtTime(j.created_at)}</span>
                <span style={{ color: INK }}>{agentName(j.agent_slug)}</span>
                <span>{j.origin}</span>
                <span>{j.runner}/{j.mode}</span>
                <span style={{ color: j.status === 'done' ? SAGE : j.status === 'running' || j.status === 'queued' ? GOLD : j.status === 'failed' ? CORAL : INK_DIM }}>{j.status}</span>
                <span>{fmtDuration(j)}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: INK_DIM }}>{j.task}</span>
              </summary>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 0 4px' }}>
                <pre style={pre}>{j.task}</pre>
                {(j.finish_reason || j.error) && (
                  <p style={{ margin: 0, color: j.error ? CORAL : INK_MUTE }}>{[j.finish_reason, j.error].filter(Boolean).join(' — ')}</p>
                )}
                {j.result_text && <pre style={pre}>{j.result_text}{j.result_truncated ? '\n…' : ''}</pre>}
                {j.session_id && <CopyLine text={`claude --resume ${j.session_id}`} />}
                {(j.status === 'queued' || j.status === 'running') && (
                  <div>
                    <button onClick={() => run(() => api(`/api/integrations/claude_code/jobs/${j.id}/cancel`, { method: 'POST' }))}
                      aria-label={`Cancel job ${j.id}`} style={{ ...smallBtn, color: CORAL }}>Cancel</button>
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
