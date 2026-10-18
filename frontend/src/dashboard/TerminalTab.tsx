/**
 * Chatty — Settings → Terminal: install the `chatty` CLI, approve a terminal
 * that is pairing (`chatty login` shows a code and a QR for /?pair=<code>),
 * and revoke paired terminals. Pending pairings are never listed — anyone can
 * start one — so a pairing is only shown when its code is entered or scanned.
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '../core/api/client';
import { confirmDialog } from '../shared/confirm';
import { INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, CORAL, SAGE, FONT_MONO, mono, inputStyle } from '../shared/styles';
import { CopyLine } from './ClaudeCodePanel';

interface Pairing {
  user_code: string;
  host: string;
  platform: string;
  ip: string;
  created_at: string;
  expires_at: string;
}

interface Device {
  id: number;
  label: string;
  host: string;
  platform: string;
  created_at: string;
  last_seen_at: string | null;
}

const smallBtn: React.CSSProperties = {
  fontSize: 11, padding: '4px 10px', borderRadius: 4,
  background: 'transparent', color: INK_MUTE, border: `1px solid ${LINE_STRONG}`, cursor: 'pointer',
};

const INSTALL = 'uv tool install "git+https://github.com/WWilson1017/chatty#subdirectory=cli"';

function fmtTime(t: string | null): string {
  return t ? new Date(t).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'never';
}

export function TerminalTab({ pairCode }: { pairCode?: string }) {
  const [code, setCode] = useState(pairCode ?? '');
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [label, setLabel] = useState('');
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  const loadDevices = useCallback(() => {
    // best-effort: the list just stays as it was on failure
    api<{ devices: Device[] }>('/api/terminal/devices').then(d => setDevices(d.devices)).catch(() => {});
  }, []);

  // Polls so an approved terminal shows up once it claims its token, and last-used stays fresh.
  useEffect(() => {
    loadDevices();
    const t = setInterval(loadDevices, 5000);
    return () => clearInterval(t);
  }, [loadDevices]);

  async function run(fn: () => Promise<unknown>) {
    setError('');
    setNote('');
    try { await fn(); } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Request failed'); }
  }

  const fetchPairing = (c: string) =>
    api<Pairing>(`/api/terminal/pair/${encodeURIComponent(c.trim())}`).then(p => { setPairing(p); setLabel(p.host); });

  const lookUp = (c: string) => run(async () => {
    setPairing(null);
    await fetchPairing(c);
  });

  // Arrived from the QR: look the code up straight away.
  useEffect(() => {
    if (pairCode) fetchPairing(pairCode).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Request failed'));
  }, [pairCode]);

  const decide = (approve: boolean) => run(async () => {
    const p = pairing!;
    await api(`/api/terminal/pair/${encodeURIComponent(p.user_code)}/decide`, {
      method: 'POST', body: JSON.stringify({ approve, label }),
    });
    setPairing(null);
    setCode('');
    setNote(approve ? `Approved — ${label || p.host} finishes logging in by itself.` : 'Denied.');
  });

  const revoke = async (d: Device) => {
    if (!await confirmDialog({
      title: `Revoke ${d.label || d.host}`,
      message: 'That terminal stops working within 15 minutes and needs `chatty login` again.',
      confirmLabel: 'Revoke', danger: true,
    })) return;
    await run(() => api(`/api/terminal/devices/${d.id}`, { method: 'DELETE' }));
    loadDevices();
  };

  const section: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 8 };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, fontSize: 12, color: INK_MUTE }}>
      <div style={section}>
        <span style={mono(9)}>Chat from a terminal</span>
        <p style={{ margin: 0 }}>
          Install the <code>chatty</code> command on a Mac or Linux computer and log in. It shows a code and a QR — scan the QR with your phone, or type the code below.
        </p>
        <CopyLine text={`${INSTALL} && chatty login ${window.location.origin}`} />
        <p style={{ margin: 0, color: INK_DIM }}>
          Needs <a href="https://docs.astral.sh/uv/getting-started/installation/" target="_blank" rel="noreferrer">uv</a>.
          No phone handy? <code>chatty login --password</code> logs in with your password instead.
        </p>
      </div>

      <div style={section}>
        <span style={mono(9)}>Approve a terminal</span>
        <form onSubmit={e => { e.preventDefault(); if (code.trim()) lookUp(code); }} style={{ display: 'flex', gap: 6 }}>
          <input value={code} onChange={e => setCode(e.target.value)} placeholder="XXXX-XXXX" aria-label="Code from your terminal"
            style={{ ...inputStyle, flex: 1, fontFamily: FONT_MONO, textTransform: 'uppercase' }} />
          <button type="submit" disabled={!code.trim()} style={smallBtn}>Look up</button>
        </form>
        {pairing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, borderRadius: 6, border: `1px solid ${LINE}` }}>
            <p style={{ margin: 0, color: INK }}>
              Approve only if your terminal shows <strong style={{ fontFamily: FONT_MONO }}>{pairing.user_code}</strong>.
            </p>
            <p style={{ margin: 0, color: INK_DIM }}>
              {pairing.host || 'unknown host'} · {pairing.platform || 'unknown OS'} · {pairing.ip} · started {fmtTime(pairing.created_at)}
            </p>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={mono(9)}>Name</span>
              <input value={label} onChange={e => setLabel(e.target.value)} maxLength={100} style={inputStyle} />
            </label>
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => decide(true)} style={{ ...smallBtn, color: SAGE }}>Approve</button>
              <button onClick={() => decide(false)} style={{ ...smallBtn, color: CORAL }}>Deny</button>
            </div>
          </div>
        )}
        {error && <p role="alert" style={{ color: CORAL, margin: 0 }}>{error}</p>}
        {note && <p style={{ color: SAGE, margin: 0 }}>{note}</p>}
      </div>

      <div style={section}>
        <span style={mono(9)}>Paired terminals</span>
        {devices.length === 0 && <p style={{ margin: 0, color: INK_DIM }}>None yet.</p>}
        {devices.map(d => (
          <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8, paddingBottom: 8, borderBottom: `1px solid ${LINE}` }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: INK }}>{d.label || d.host}</div>
              <div style={{ color: INK_DIM }}>{d.host} · {d.platform} · last used {fmtTime(d.last_seen_at)}</div>
            </div>
            <button onClick={() => revoke(d)} style={{ ...smallBtn, color: CORAL }}>Revoke</button>
          </div>
        ))}
      </div>
    </div>
  );
}
