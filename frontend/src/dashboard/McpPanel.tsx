/**
 * Chatty — MCP servers card body: add/remove remote servers, test and refresh their tool
 * lists, and set each tool's enabled / read-only / allow-in-background policy.
 * Rendered inside the mcp integration card in IntegrationsTab.
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import { confirmDialog } from '../shared/confirm';
import { INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, BG_RAISED, CORAL, SAGE, GOLD, FONT_MONO, mono, inputStyle } from '../shared/styles';

interface Tool {
  name: string;
  description: string;
  read_only_hint: boolean | null;
  enabled: boolean;
  writes: boolean;
}

interface Server {
  id: string;
  name: string;
  url: string;
  header: string;
  has_key: boolean;
  enabled: boolean;
  allow_in_background: boolean;
  tools_refreshed_at: number | null;
  last_error: string | null;
  tools: Tool[];
}

interface Status {
  enabled: boolean;
  servers: Server[];
}

const EMPTY_FORM = { name: '', url: '', header: 'Authorization', api_key: '' };

const smallBtn: React.CSSProperties = {
  fontSize: 11, padding: '4px 10px', borderRadius: 4,
  background: 'transparent', color: INK_MUTE, border: `1px solid ${LINE_STRONG}`, cursor: 'pointer',
};
const field: React.CSSProperties = { ...inputStyle, fontSize: 12, padding: '5px 8px' };

function fmtTime(t: number | null): string {
  return t ? new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'never';
}

export function McpPanel({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api<Status>('/api/integrations/mcp/status').then(setStatus).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  // Every mcp route answers with the full status, so one handler refreshes the card.
  async function run(fn: () => Promise<Status>) {
    setError(''); setBusy(true);
    try { setStatus(await fn()); onChanged(); }
    catch (err: unknown) { setError(err instanceof Error ? err.message : 'Request failed'); }
    finally { setBusy(false); }
  }

  const add = () => run(async () => {
    const s = await api<Status>('/api/integrations/mcp/servers', { method: 'POST', body: JSON.stringify(form) });
    setForm(EMPTY_FORM); setAdding(false);
    return s;
  });
  const patchServer = (id: string, body: Partial<Pick<Server, 'enabled' | 'allow_in_background'>>) =>
    run(() => api<Status>(`/api/integrations/mcp/servers/${id}`, { method: 'PUT', body: JSON.stringify(body) }));
  const refresh = (id: string) => run(() => api<Status>(`/api/integrations/mcp/servers/${id}/refresh`, { method: 'POST' }));
  const patchTool = (id: string, tool: string, body: { enabled?: boolean; read_only?: boolean }) =>
    run(() => api<Status>(`/api/integrations/mcp/servers/${id}/tools/${encodeURIComponent(tool)}`, { method: 'PUT', body: JSON.stringify(body) }));
  const remove = async (s: Server) => {
    if (!await confirmDialog({
      title: `Remove ${s.name}`,
      message: 'Agents lose its tools at their next turn. The key is deleted.',
      confirmLabel: 'Remove', danger: true,
    })) return;
    await run(() => api<Status>(`/api/integrations/mcp/servers/${s.id}`, { method: 'DELETE' }));
  };

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${LINE}`, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 12, color: INK_MUTE }}>
      {error && <p role="alert" style={{ color: CORAL, margin: 0 }}>{error}</p>}

      {status?.servers.map(s => (
        <details key={s.id} style={{ border: `1px solid ${LINE}`, borderRadius: 4, padding: '6px 8px' }}>
          <summary style={{ cursor: 'pointer', display: 'flex', flexWrap: 'wrap', gap: '2px 10px', alignItems: 'center' }}>
            <span aria-hidden style={{ width: 6, height: 6, borderRadius: '50%', background: s.last_error ? CORAL : s.enabled ? SAGE : INK_DIM }} />
            <span style={{ color: INK }}>{s.name}</span>
            <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: INK_DIM, fontFamily: FONT_MONO }}>{s.url}</span>
            <span>{s.tools.length} tools</span>
          </summary>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '8px 0 2px' }}>
            {s.last_error && <p style={{ margin: 0, color: CORAL }}>Last refresh failed: {s.last_error}</p>}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="checkbox" checked={s.enabled} disabled={busy} onChange={e => patchServer(s.id, { enabled: e.target.checked })} />
                Enabled
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }} title="Lets scheduled actions, heartbeats and reminders use this server's write tools without asking">
                <input type="checkbox" checked={s.allow_in_background} disabled={busy} onChange={e => patchServer(s.id, { allow_in_background: e.target.checked })} />
                Allow writes in background turns
              </label>
              <span style={{ color: INK_DIM }}>{s.header}: {s.has_key ? '••••••' : 'no key'} · tools refreshed {fmtTime(s.tools_refreshed_at)}</span>
              <button onClick={() => refresh(s.id)} disabled={busy} style={{ ...smallBtn, marginLeft: 'auto' }}>Test &amp; refresh tools</button>
              <button onClick={() => remove(s)} disabled={busy} style={{ ...smallBtn, color: CORAL, borderColor: 'transparent' }}>Remove</button>
            </div>

            {s.tools.length > 0 && (
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ ...mono(9), textAlign: 'left' }}>
                    <th style={{ padding: '2px 6px 4px 0', fontWeight: 400 }}>Tool</th>
                    <th style={{ padding: '2px 6px 4px', fontWeight: 400 }}>On</th>
                    <th style={{ padding: '2px 6px 4px', fontWeight: 400 }} title="Only you can mark a tool read-only; the server's own hint is shown as a suggestion">Read-only</th>
                  </tr>
                </thead>
                <tbody>
                  {s.tools.map(t => (
                    <tr key={t.name} style={{ borderTop: `1px solid ${LINE}`, opacity: t.enabled ? 1 : 0.5 }}>
                      <td style={{ padding: '4px 6px 4px 0' }}>
                        <span style={{ color: INK, fontFamily: FONT_MONO }}>{t.name}</span>
                        {t.read_only_hint && <span style={{ ...mono(8, GOLD), marginLeft: 8 }}>server says read-only</span>}
                        {t.description && <div style={{ color: INK_DIM, fontSize: 11 }}>{t.description}</div>}
                      </td>
                      <td style={{ padding: '4px 6px', verticalAlign: 'top' }}>
                        <input type="checkbox" checked={t.enabled} disabled={busy} aria-label={`Enable ${t.name}`}
                          onChange={e => patchTool(s.id, t.name, { enabled: e.target.checked })} />
                      </td>
                      <td style={{ padding: '4px 6px', verticalAlign: 'top' }}>
                        <input type="checkbox" checked={!t.writes} disabled={busy} aria-label={`Mark ${t.name} read-only`}
                          onChange={e => patchTool(s.id, t.name, { read_only: e.target.checked })} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </details>
      ))}

      {adding ? (
        <form onSubmit={e => { e.preventDefault(); add(); }} style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8, borderRadius: 4, background: BG_RAISED }}>
          <input required placeholder="Name (e.g. GitHub)" value={form.name} maxLength={60} style={field}
            onChange={e => setForm({ ...form, name: e.target.value })} />
          <input required placeholder="https://… (the server's MCP endpoint)" value={form.url} style={field}
            onChange={e => setForm({ ...form, url: e.target.value })} />
          <div style={{ display: 'flex', gap: 6 }}>
            <input required placeholder="Header" value={form.header} pattern="[A-Za-z0-9-]+" title="Header name, e.g. Authorization or X-API-Key" style={{ ...field, width: 150 }}
              onChange={e => setForm({ ...form, header: e.target.value })} />
            <input type="password" autoComplete="off" placeholder="API key (optional; Authorization gets 'Bearer ' added)" value={form.api_key} style={{ ...field, flex: 1 }}
              onChange={e => setForm({ ...form, api_key: e.target.value })} />
          </div>
          <p style={{ margin: 0, color: INK_DIM }}>
            Must be https on a public host. Every tool counts as a write (asks before running in chat, refused in background turns) until you mark it read-only here.
          </p>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="submit" disabled={busy} style={{ ...smallBtn, color: INK }}>{busy ? 'Connecting…' : 'Connect'}</button>
            <button type="button" onClick={() => { setAdding(false); setForm(EMPTY_FORM); }} style={smallBtn}>Cancel</button>
          </div>
        </form>
      ) : (
        <div><button onClick={() => setAdding(true)} style={smallBtn}>Add server</button></div>
      )}
    </div>
  );
}
