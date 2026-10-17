/**
 * Chatty — the computer's live screen (/computer?agent=<slug>&task=<id>&mode=view|control).
 *
 * Full-screen, outside AppShell, JWT-protected by ProtectedRoute. Watching is
 * view-only; "Take control" opens a control session on the computer (the helper
 * pauses, the control VNC port comes up) and "I'm done" ends it. The browser
 * never holds the computer's secret: it asks Chatty for a single-use ticket and
 * Chatty relays the VNC bytes. The control session id lives in sessionStorage
 * so a phone that drops off can reattach within the computer's grace period.
 */

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type RFB from '@novnc/novnc';
import { api } from '../core/api/client';
import { INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, BG_ELEV, BG_RAISED, CORAL, SAGE, GOLD, FONT_MONO, mono } from '../shared/styles';
import { useIsMobile } from '../shared/useIsMobile';

type Mode = 'view' | 'control';
type Conn = 'connecting' | 'connected' | 'disconnected';

const SESSION_KEY = 'chatty_control_session'; // {agent, id}
const KEYS: Record<string, number> = { Enter: 0xff0d, Backspace: 0xff08, Tab: 0xff09, Escape: 0xff1b };

// X11 keysyms: Latin-1 maps 1:1, anything else is the Unicode keysym range.
function keysym(ch: string): number {
  const cp = ch.codePointAt(0)!;
  return cp === 10 ? KEYS.Enter : cp < 0x100 ? cp : 0x01000000 | cp;
}

function storedControl(agent: string): string | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null') as { agent: string; id: string } | null;
    return v && v.agent === agent ? v.id : null;
  } catch { return null; }
}

const btn: React.CSSProperties = {
  fontSize: 12, padding: '6px 12px', borderRadius: 4, cursor: 'pointer',
  background: 'transparent', color: INK, border: `1px solid ${LINE_STRONG}`,
};

export function ComputerPage() {
  const [params] = useSearchParams();
  const agent = params.get('agent') || '';
  const taskId = params.get('task') || undefined;
  const [mode, setMode] = useState<Mode>(params.get('mode') === 'control' ? 'control' : 'view');
  const [conn, setConn] = useState<Conn>('connecting');
  const [error, setError] = useState('');
  const [controlId, setControlId] = useState<string | null>(() => storedControl(agent));
  const [text, setText] = useState('');
  const [attempt, setAttempt] = useState(0); // bump to reconnect
  const screenRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const isMobile = useIsMobile();

  useEffect(() => { document.title = `${agent || 'Computer'} · screen`; }, [agent]);

  useEffect(() => {
    if (!agent) return;
    let cancelled = false;
    let rfb: RFB | null = null;
    let connected = false;
    let closeReason = '';
    setConn('connecting');
    setError('');
    (async () => {
      try {
        const reattach = mode === 'control' ? storedControl(agent) : undefined;
        const [{ default: Rfb }, { ticket }] = await Promise.all([
          import('@novnc/novnc'),
          api<{ ticket: string }>('/api/computer/viewer-ticket', {
            method: 'POST', body: JSON.stringify({ mode, agent, task_id: taskId, reattach }),
          }),
        ]);
        if (cancelled || !screenRef.current) return;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        // Our own socket so the server's close reason (busy, turned off…) is readable; noVNC hides it.
        const sock = new WebSocket(`${proto}://${location.host}/api/computer/vnc?ticket=${encodeURIComponent(ticket)}`);
        sock.addEventListener('close', ev => { closeReason = ev.reason; });
        rfb = new Rfb(screenRef.current, sock);
        rfb.background = '#0A0C0F';
        rfb.scaleViewport = true;
        rfb.resizeSession = false;
        rfb.viewOnly = mode === 'view';
        rfbRef.current = rfb;
        rfb.addEventListener('connect', async () => {
          connected = true;
          setConn('connected');
          if (mode === 'control') {
            // The relay opened the control session when the socket connected; fetch its id for "I'm done" and reattach.
            const { control } = await api<{ control: { control_session_id: string } | null }>('/api/computer/control/status');
            if (control && !cancelled) {
              setControlId(control.control_session_id);
              sessionStorage.setItem(SESSION_KEY, JSON.stringify({ agent, id: control.control_session_id }));
            }
          }
        });
        rfb.addEventListener('disconnect', e => {
          if (cancelled) return;
          const { clean } = (e as CustomEvent<{ clean: boolean }>).detail;
          setConn('disconnected');
          setError(closeReason || (clean ? '' : 'Connection lost.'));
          // A control session we never reached is gone (expired or refused): don't keep reattaching to it.
          if (mode === 'control' && !connected) { sessionStorage.removeItem(SESSION_KEY); setControlId(null); }
        });
      } catch (err: unknown) {
        if (!cancelled) { setConn('disconnected'); setError(err instanceof Error ? err.message : 'Could not connect'); }
      }
    })();
    return () => { cancelled = true; rfbRef.current = null; rfb?.disconnect(); };
  }, [agent, taskId, mode, attempt]);

  const reconnect = () => setAttempt(a => a + 1);

  const done = async () => {
    const id = controlId;
    sessionStorage.removeItem(SESSION_KEY);
    setControlId(null);
    if (id) {
      try { await api('/api/computer/control/end', { method: 'POST', body: JSON.stringify({ control_session_id: id }) }); }
      catch (err: unknown) { setError(err instanceof Error ? err.message : 'Could not end control'); }
    }
    setMode('view');
    setAttempt(a => a + 1);
  };

  const sendKey = (ks: number) => rfbRef.current?.sendKey(ks, null);
  const sendText = () => {
    for (const ch of text) sendKey(keysym(ch));
    setText('');
  };

  if (!agent) {
    return (
      <div style={{ minHeight: '100vh', background: BG_ELEV, color: INK_MUTE, display: 'grid', placeItems: 'center', fontSize: 13 }}>
        <p>No agent given. Open the screen from the Computer card in Settings → Integrations.</p>
      </div>
    );
  }

  const inControl = mode === 'control';
  const statusText = conn === 'connecting' ? 'Connecting…'
    : conn === 'disconnected' ? 'Disconnected'
    : inControl ? 'You have control — the helper is paused until you press I’m done'
    : 'Watching — view only';

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column', background: BG_ELEV, color: INK_MUTE, fontSize: 12 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderBottom: `1px solid ${LINE}`, flexWrap: 'wrap' }}>
        <Link to="/" style={{ ...mono(9, INK_DIM), textDecoration: 'none' }}>← Chatty</Link>
        <span style={{ color: INK }}>{agent}</span>
        {taskId && <span style={{ fontFamily: FONT_MONO, color: INK_DIM }}>task {taskId}</span>}
        <span aria-hidden style={{ width: 6, height: 6, borderRadius: '50%', background: conn === 'connected' ? (inControl ? GOLD : SAGE) : INK_DIM }} />
        <span aria-live="polite">{statusText}</span>
        <span style={{ flex: 1 }} />
        {conn === 'disconnected' && <button onClick={reconnect} style={btn}>{inControl && controlId ? 'Reconnect (keep control)' : 'Reconnect'}</button>}
        {!inControl && <button onClick={() => setMode('control')} style={{ ...btn, borderColor: GOLD, color: GOLD }}>Take control</button>}
        {inControl && <button onClick={done} style={{ ...btn, borderColor: SAGE, color: SAGE }}>I’m done</button>}
      </header>
      {error && <p role="alert" style={{ margin: 0, padding: '6px 12px', color: CORAL, borderBottom: `1px solid ${LINE}` }}>{error}</p>}

      {/* noVNC draws its canvas into this box and scales the 1280×800 desktop to fit. */}
      <div ref={screenRef} style={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }} />

      {inControl && (isMobile || conn === 'connected') && (
        <form onSubmit={e => { e.preventDefault(); sendText(); }}
          style={{ display: 'flex', gap: 6, padding: 8, borderTop: `1px solid ${LINE}`, flexWrap: 'wrap', alignItems: 'center' }}>
          <input value={text} onChange={e => setText(e.target.value)} placeholder="Type here, then Send (phones: the screen can’t take a keyboard directly)"
            autoCapitalize="off" autoCorrect="off" spellCheck={false}
            style={{ flex: 1, minWidth: 160, fontSize: 14, padding: '8px 10px', borderRadius: 4, background: BG_RAISED, color: INK, border: `1px solid ${LINE_STRONG}` }} />
          <button type="submit" style={btn} disabled={!text}>Send</button>
          {Object.entries(KEYS).map(([name, ks]) => (
            <button key={name} type="button" onClick={() => sendKey(ks)} style={btn}>{name === 'Escape' ? 'Esc' : name}</button>
          ))}
        </form>
      )}
    </div>
  );
}
