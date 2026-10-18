/**
 * Chatty — Computer card body: online status, keep-running setting, which
 * agents may use it, each agent's signed-in sites, and links to the live screen.
 * Rendered inside the computer integration card in IntegrationsTab.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../core/api/client';
import { confirmDialog } from '../shared/confirm';
import { INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, BG_RAISED, CORAL, SAGE, GOLD, FONT_MONO, mono } from '../shared/styles';
import type { Agent } from '../core/types';

interface Status {
  configured: boolean;
  enabled: boolean;
  url: string;
  idle_minutes: number;
  disabled_agents: string[];
  online: boolean;
  health: Record<string, unknown> | null;
  error: string | null;
  viewers: number;
  control: { control_session_id: string; agent: string; task_id: string | null } | null;
}

interface Site { domain: string; [k: string]: unknown }

const smallBtn: React.CSSProperties = {
  fontSize: 11, padding: '4px 10px', borderRadius: 4,
  background: 'transparent', color: INK_MUTE, border: `1px solid ${LINE_STRONG}`, cursor: 'pointer',
};
const selectStyle: React.CSSProperties = {
  alignSelf: 'flex-start', fontSize: 12, padding: '4px 6px', borderRadius: 4,
  background: BG_RAISED, color: INK, border: `1px solid ${LINE_STRONG}`,
};

const str = (v: unknown) => (v == null || v === '' ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));
// /health reports disk as {total, used, free} in bytes.
function fmtDisk(d: unknown): string {
  const o = d as { used?: number; total?: number } | null;
  if (!o || typeof o.used !== 'number' || typeof o.total !== 'number') return str(d);
  const gb = (n: number) => (n / 1e9).toFixed(1);
  return `${gb(o.used)} / ${gb(o.total)} GB`;
}

export function ComputerPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState('');
  const [sitesFor, setSitesFor] = useState<string | null>(null);
  const sitesForRef = useRef<string | null>(null); // same value, readable after an await
  const [sites, setSites] = useState<Site[] | null>(null);
  // Exclude-list writes run one at a time, each from the list the previous write returned, so two
  // quick checkbox changes can't both derive from the same stale status and silently drop one.
  const disabledRef = useRef<string[]>([]);
  const agentWrites = useRef(0);
  const agentChain = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => { if (status && agentWrites.current === 0) disabledRef.current = status.disabled_agents; }, [status]);

  const load = useCallback(() => {
    // best-effort polling: a missed tick just shows the previous state
    api<Status>('/api/integrations/computer/status').then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    api<{ agents: Agent[] }>('/api/agents').then(d => setAgents(d.agents)).catch(() => {});
  }, []);

  async function run(fn: () => Promise<unknown>) {
    setError('');
    try { await fn(); } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Request failed'); }
    load();
  }

  const setKeepRunning = (always_on: boolean) => run(() =>
    api('/api/integrations/computer/settings', { method: 'PUT', body: JSON.stringify({ always_on }) }));

  const toggleAgent = (slug: string, allowed: boolean) => {
    agentWrites.current += 1;
    agentChain.current = agentChain.current.then(() => run(async () => {
      const current = disabledRef.current;
      const next = allowed ? current.filter(s => s !== slug) : [...current, slug];
      const res = await api<{ disabled_agents: string[] }>('/api/integrations/computer/agents', {
        method: 'PUT', body: JSON.stringify({ disabled_agents: next }),
      });
      disabledRef.current = res.disabled_agents;
      setStatus(s => s && { ...s, disabled_agents: res.disabled_agents });
    })).finally(() => { agentWrites.current -= 1; });
  };

  const showSites = (slug: string) => run(async () => {
    if (sitesForRef.current === slug) { sitesForRef.current = null; setSitesFor(null); setSites(null); return; }
    sitesForRef.current = slug; setSitesFor(slug); setSites(null);
    const { sites } = await api<{ sites: Site[] }>(`/api/integrations/computer/profiles/${slug}/sites`);
    if (sitesForRef.current === slug) setSites(sites); // a slow reply for an agent no longer open is dropped
  });

  const signOut = (slug: string, domain: string) => run(async () => {
    await api(`/api/integrations/computer/profiles/${slug}/sites/${encodeURIComponent(domain)}`, { method: 'DELETE' });
    setSites(s => s && s.filter(x => x.domain !== domain));
  });

  const resetBrowser = async (slug: string) => {
    if (!await confirmDialog({
      title: 'Reset this agent’s browser',
      message: 'Clears every site’s cookies and stored data in this agent’s Chrome profile on the computer. Sites themselves are not told; sessions there may stay valid until they expire.',
      confirmLabel: 'Reset', danger: true,
    })) return;
    await run(async () => {
      await api(`/api/integrations/computer/profiles/${slug}`, { method: 'DELETE' });
      setSites([]);
    });
  };

  const agentName = (slug: string) => agents.find(a => a.slug === slug)?.agent_name ?? slug;
  const h = status?.health ?? {};

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${LINE}`, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12, color: INK_MUTE }}>
      {error && <p role="alert" style={{ color: CORAL, margin: 0 }}>{error}</p>}

      {status && !status.configured && (
        <p style={{ margin: 0, lineHeight: 1.5 }}>
          No computer yet. Run the <code style={{ fontFamily: FONT_MONO }}>chatty-computer</code> container (a second Railway service, or Docker locally)
          and give Chatty its address as <code style={{ fontFamily: FONT_MONO }}>COMPUTER_URL</code> and its secret as <code style={{ fontFamily: FONT_MONO }}>COMPUTER_SECRET</code>, then reload.
        </p>
      )}

      {status?.configured && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span aria-hidden style={{ width: 6, height: 6, borderRadius: '50%', background: status.online ? SAGE : INK_DIM }} />
            <span style={{ color: INK }}>{status.online ? 'Online' : 'Offline'}</span>
            <span style={{ fontFamily: FONT_MONO }}>{status.url}</span>
            {str(h.chromium_version) && <span>· Chromium {str(h.chromium_version)}</span>}
            {str(h.disk) && <span>· disk {fmtDisk(h.disk)}</span>}
            {h.desktop_running === false && <span>· asleep (wakes for the next task or viewer)</span>}
            {str(h.active_agent) && <span>· screen: {agentName(str(h.active_agent))}</span>}
            {h.human_in_control === true && <span style={{ color: GOLD }}>· someone has control</span>}
            {status.viewers > 0 && <span>· {status.viewers} watching</span>}
          </div>
          {status.error && <p role="alert" style={{ color: CORAL, margin: 0 }}>{status.error}</p>}

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={mono(9)}>Keep the computer running</span>
            <select value={status.idle_minutes === 0 ? 'on' : 'idle'} onChange={e => setKeepRunning(e.target.value === 'on')} style={selectStyle}>
              <option value="idle">Close when idle (after 30 min)</option>
              <option value="on">Always on</option>
            </select>
          </label>

          {agents.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={mono(9)}>Agents that can use it</span>
              {agents.map(a => {
                const allowed = !status.disabled_agents.includes(a.slug);
                return (
                  <div key={a.slug} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', color: INK }}>
                        <input type="checkbox" checked={allowed} onChange={e => toggleAgent(a.slug, e.target.checked)} />
                        {a.agent_name}
                      </label>
                      {/* Same tab on purpose: the JWT lives in sessionStorage, so a new tab would land on /login. */}
                      {allowed && status.enabled && (
                        <Link to={`/computer?agent=${a.slug}`} style={{ ...smallBtn, textDecoration: 'none' }}>Open the screen</Link>
                      )}
                      <button onClick={() => showSites(a.slug)} style={smallBtn}>{sitesFor === a.slug ? 'Hide sites' : 'Signed-in sites'}</button>
                    </div>
                    {sitesFor === a.slug && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingLeft: 22 }}>
                        {sites === null ? <span style={{ color: INK_DIM }}>Loading…</span>
                          : sites.length === 0 ? <span style={{ color: INK_DIM }}>No sites with stored data.</span>
                          : sites.map(s => (
                            <div key={s.domain} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontFamily: FONT_MONO, color: INK }}>{s.domain}</span>
                              <button onClick={() => signOut(a.slug, s.domain)} aria-label={`Sign out of ${s.domain}`} style={smallBtn}>Sign out</button>
                            </div>
                          ))}
                        <div>
                          <button onClick={() => resetBrowser(a.slug)} style={{ ...smallBtn, color: CORAL }}>Reset browser</button>
                        </div>
                        <p style={{ margin: 0, color: INK_DIM }}>
                          Signing out clears what the computer stored for that site. The site’s own servers aren’t told, so a session may stay valid there until it expires.
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <p style={{ margin: 0, color: INK_DIM, lineHeight: 1.5 }}>
            All agents share one Linux user (with sudo) on the computer. Each has its own Chrome profile so they don’t sign each other out,
            but a program one agent runs could read another agent’s files or logins. Sign in to sites yourself by taking over the screen;
            the helper never sees what you type.
          </p>
        </>
      )}
    </div>
  );
}
