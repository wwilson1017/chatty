// Live meeting recorder engine: MediaRecorder restarted per ~20s chunk (each
// chunk is a standalone file), sequential upload queue with backoff retry,
// screen Wake Lock, iOS suspend/resume handling, and the session SSE stream
// that delivers coach messages into the open chat.
//
// Sessions live server-side: unmount/navigation is a *suspend*, never a stop;
// GET /api/live/active reattaches after reload. Recording only ever stops via
// the Stop button or the server's idle finalize.

import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken } from '../../core/auth/tokenUtils';
import { api } from '../../core/api/client';
import { parseServerTimestamp } from '../utils/dateFormat';
import type { ChatMessage } from './useAgentChat';

export type LiveStatus =
  | 'idle' | 'starting' | 'recording' | 'suspended' | 'tap_to_resume'
  | 'stopping' | 'finalizing' | 'done' | 'error';

export interface LiveSessionInfo {
  session_id: string;
  agent_id: string;
  agent_name: string;
  conversation_id: string;
  state: string;
  started_at: string;
  last_chunk_index: number | null;
  chunk_seconds: number;
}

export interface LiveDoneInfo {
  meeting_filename: string | null;
  audio_url: string | null;
  duration_seconds: number;
  title: string;
  error: string | null;
}

// ── Pure helpers (exported for tests) ───────────────────────────────────────

export function pickAudioMime(isSupported: (t: string) => boolean): string | undefined {
  for (const t of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']) {
    if (isSupported(t)) return t;
  }
  return undefined; // let the browser pick; read recorder.mimeType afterwards
}

export function extForMime(type: string): string {
  const t = (type || '').toLowerCase();
  if (t.includes('mp4')) return 'mp4';
  if (t.includes('ogg')) return 'ogg';
  if (t.includes('wav')) return 'wav';
  return 'webm';
}

export function backoffDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 15000);
}

export function formatElapsed(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = `${h ? String(m).padStart(2, '0') : m}:${String(s % 60).padStart(2, '0')}`;
  return h ? `${h}:${rest}` : rest;
}

// ── Hook ────────────────────────────────────────────────────────────────────

interface LiveMeetingOptions {
  conversationId: string | null;
  onCoachMessage: (msg: ChatMessage, sessionConvId: string) => void;
  onSessionConversation: (convId: string) => void;
  onSessionEnded?: (sessionConvId: string) => void;
}

interface QueuedChunk { index: number; blob: Blob }

function authOnly(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function toLoginOn401() {
  sessionStorage.removeItem('chatty_token');
  window.location.href = '/login';
}

export function useLiveMeeting(apiPrefix: string, opts: LiveMeetingOptions) {
  const [status, setStatus] = useState<LiveStatus>('idle');
  const [elapsedSec, setElapsedSec] = useState(0);
  const [pendingUploads, setPendingUploads] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [foreignSession, setForeignSession] = useState<LiveSessionInfo | null>(null);
  const [doneInfo, setDoneInfo] = useState<LiveDoneInfo | null>(null);

  const statusRef = useRef<LiveStatus>('idle');
  const setStatusBoth = useCallback((s: LiveStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const optsRef = useRef(opts);
  useEffect(() => { optsRef.current = opts; });

  const sessionRef = useRef<LiveSessionInfo | null>(null);
  const startedAtMsRef = useRef(0);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const partsRef = useRef<Blob[]>([]);
  const stopReasonRef = useRef<'restart' | 'final' | 'suspend'>('restart');
  const chunkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nextIndexRef = useRef(0);
  const queueRef = useRef<QueuedChunk[]>([]);
  const uploaderActiveRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const sseAbortRef = useRef<AbortController | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);

  const agentId = apiPrefix.split('/').pop() || '';

  // ── Wake Lock ─────────────────────────────────────────────────────────
  const acquireWakeLock = useCallback(async () => {
    try {
      wakeLockRef.current = (await navigator.wakeLock?.request('screen')) ?? null;
    } catch { /* unsupported or denied — recording works regardless */ }
  }, []);

  const releaseWakeLock = useCallback(() => {
    try { wakeLockRef.current?.release(); } catch { /* already released */ }
    wakeLockRef.current = null;
  }, []);

  // ── Upload queue (sequential, unbounded retry on transient errors) ──────
  const pumpQueue = useCallback(async () => {
    if (uploaderActiveRef.current) return;
    uploaderActiveRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const session = sessionRef.current;
        if (!session) break;
        const chunk = queueRef.current[0];
        let attempt = 0;
        let dispatched = false;
        while (!dispatched) {
          try {
            const formData = new FormData();
            formData.append('index', String(chunk.index));
            const ext = extForMime(chunk.blob.type);
            formData.append('file', new File([chunk.blob], `chunk-${chunk.index}.${ext}`, { type: chunk.blob.type }));
            const res = await fetch(`${apiPrefix}/live/${session.session_id}/chunk`, {
              method: 'POST',
              headers: authOnly(),
              body: formData,
            });
            if (res.ok) { dispatched = true; break; }
            if (res.status === 401) { toLoginOn401(); return; }
            if (res.status === 404 || res.status === 410 || res.status === 409) {
              // Session finalized under us — the SSE stream drives state.
              queueRef.current = [];
              setPendingUploads(0);
              return;
            }
            if (res.status === 413 || res.status === 422) {
              console.warn(`Dropping chunk ${chunk.index}: HTTP ${res.status}`);
              dispatched = true; // drop, keep the meeting going
              break;
            }
            throw new Error(`HTTP ${res.status}`);
          } catch {
            await new Promise(r => setTimeout(r, backoffDelay(attempt++)));
          }
        }
        queueRef.current.shift();
        setPendingUploads(queueRef.current.length);
      }
      // Stop was requested and every chunk is safely uploaded → tell the server.
      if (stopRequestedRef.current && sessionRef.current
          && recorderRef.current === null && queueRef.current.length === 0) {
        stopRequestedRef.current = false;
        const session = sessionRef.current;
        for (let attempt = 0; attempt < 5; attempt++) {
          try {
            const res = await fetch(`${apiPrefix}/live/${session.session_id}/stop`, {
              method: 'POST', headers: authOnly(),
            });
            if (res.status === 401) { toLoginOn401(); return; }
            if (res.ok || res.status === 404) break;
          } catch { /* retry */ }
          await new Promise(r => setTimeout(r, backoffDelay(attempt)));
        }
        setStatusBoth('finalizing'); // server idle-finalize is the net if POSTs failed
      }
    } finally {
      uploaderActiveRef.current = false;
    }
  }, [apiPrefix, setStatusBoth]);

  const enqueueChunk = useCallback((blob: Blob) => {
    if (blob.size === 0) return;
    queueRef.current.push({ index: nextIndexRef.current++, blob });
    setPendingUploads(queueRef.current.length);
    void pumpQueue();
  }, [pumpQueue]);

  // ── Recorder loop (restart per chunk) ───────────────────────────────────
  const startRecorderLoop = useCallback((stream: MediaStream) => {
    const session = sessionRef.current;
    if (!session) return;
    const mime = pickAudioMime(t => MediaRecorder.isTypeSupported(t));
    const startOne = () => {
      if (statusRef.current !== 'recording') return;
      const rec = new MediaRecorder(stream, {
        ...(mime ? { mimeType: mime } : {}),
        audioBitsPerSecond: 48000,
      });
      recorderRef.current = rec;
      stopReasonRef.current = 'restart';
      partsRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) partsRef.current.push(e.data); };
      rec.onstop = () => {
        const blob = new Blob(partsRef.current, { type: rec.mimeType || mime || 'audio/webm' });
        partsRef.current = [];
        enqueueChunk(blob);
        const reason = stopReasonRef.current;
        if (reason === 'restart' && statusRef.current === 'recording') {
          startOne();
        } else if (reason === 'final') {
          recorderRef.current = null;
          void pumpQueue(); // may already be draining; ensures the stop POST fires
        } else {
          recorderRef.current = null;
        }
      };
      rec.onerror = () => { salvageAndSuspend(); };
      rec.start(); // no timeslice — each recorder yields ONE standalone file
      chunkTimerRef.current = setTimeout(() => {
        if (rec.state === 'recording') {
          stopReasonRef.current = 'restart';
          rec.stop();
        }
      }, (session.chunk_seconds || 20) * 1000);
    };

    // A dying track (screen lock, phone call, Siri) is the real suspend
    // signal on iOS — visibilitychange alone misses in-app interruptions.
    stream.getAudioTracks().forEach(track => {
      track.onended = () => salvageAndSuspend();
    });

    startOne();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enqueueChunk, pumpQueue]);

  const stopRecorderInstance = useCallback((reason: 'final' | 'suspend') => {
    if (chunkTimerRef.current) { clearTimeout(chunkTimerRef.current); chunkTimerRef.current = null; }
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') {
      stopReasonRef.current = reason;
      try { rec.stop(); } catch { recorderRef.current = null; }
    } else {
      recorderRef.current = null;
    }
    streamRef.current?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    streamRef.current = null;
  }, []);

  const attemptResume = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setStatusBoth('recording');
      void acquireWakeLock();
      startRecorderLoop(stream);
    } catch {
      setStatusBoth('tap_to_resume');
    }
  }, [acquireWakeLock, setStatusBoth, startRecorderLoop]);

  const salvageAndSuspend = useCallback(() => {
    if (statusRef.current !== 'recording') return;
    stopRecorderInstance('suspend');
    if (document.visibilityState === 'visible') {
      // In-app interruption (call/Siri): one immediate resume attempt.
      setStatusBoth('suspended');
      void attemptResume();
    } else {
      setStatusBoth('suspended');
    }
  }, [attemptResume, setStatusBoth, stopRecorderInstance]);

  // ── Session SSE ─────────────────────────────────────────────────────────
  const connectSSE = useCallback((sessionId: string) => {
    sseAbortRef.current?.abort();
    const abort = new AbortController();
    sseAbortRef.current = abort;

    const run = async () => {
      let attempt = 0;
      while (!abort.signal.aborted) {
        try {
          const res = await fetch(`${apiPrefix}/live/${sessionId}/events`, {
            headers: authOnly(),
            signal: abort.signal,
          });
          if (res.status === 401) { toLoginOn401(); return; }
          if (res.status === 404 || res.status === 410) {
            const session = sessionRef.current;
            if (statusRef.current === 'finalizing' && session) {
              optsRef.current.onSessionEnded?.(session.conversation_id);
            }
            if (statusRef.current !== 'done') setStatusBoth('idle');
            sessionRef.current = null;
            return;
          }
          if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
          attempt = 0;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            for (const line of lines) {
              if (!line.startsWith('data: ')) continue;
              try {
                handleSSEEvent(JSON.parse(line.slice(6).trim()));
              } catch { /* skip malformed */ }
            }
          }
        } catch {
          if (abort.signal.aborted) return;
        }
        if (abort.signal.aborted) return;
        const s = statusRef.current;
        if (s === 'done' || s === 'idle' || s === 'error') return;
        await new Promise(r => setTimeout(r, backoffDelay(attempt++)));
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiPrefix]);

  const handleSSEEvent = useCallback((event: Record<string, unknown>) => {
    const type = event.type as string;
    const session = sessionRef.current;
    if (type === 'coach' && session) {
      const m = event.message as { id: string; role: string; content: string; model?: string; created_at?: string };
      const msg: ChatMessage = {
        id: m.id,
        role: 'assistant',
        content: m.content,
        timestamp: parseServerTimestamp(m.created_at)?.getTime() ?? Date.now(),
        model: m.model,
      };
      optsRef.current.onCoachMessage(msg, session.conversation_id);
    } else if (type === 'status') {
      const state = event.state as string;
      const local = statusRef.current;
      // Server truth wins when it is ahead of us (idle finalize).
      if (state === 'finalizing' && ['recording', 'suspended', 'tap_to_resume', 'starting', 'stopping'].includes(local)) {
        stopRecorderInstance('suspend');
        releaseWakeLock();
        setStatusBoth('finalizing');
      }
    } else if (type === 'done') {
      setDoneInfo({
        meeting_filename: (event.meeting_filename as string) ?? null,
        audio_url: (event.audio_url as string) ?? null,
        duration_seconds: (event.duration_seconds as number) ?? 0,
        title: (event.title as string) ?? 'Live meeting',
        error: (event.error as string) ?? null,
      });
      setStatusBoth('done');
      releaseWakeLock();
    }
    // 'chunk' / 'finalize' / 'ping' → no UI in the minimal design
  }, [releaseWakeLock, setStatusBoth, stopRecorderInstance]);

  // ── Public API ──────────────────────────────────────────────────────────
  const start = useCallback(async (prepNote?: string) => {
    if (statusRef.current !== 'idle' && statusRef.current !== 'error') return;
    setErrorMsg(null);
    setDoneInfo(null);
    setStatusBoth('starting');

    // Mic FIRST: a denied mic must never create a server session.
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      const name = (e as DOMException)?.name;
      // On insecure origins (plain-HTTP LAN) the mic API doesn't exist at all —
      // that's a protocol problem, not a permission one; say so.
      setErrorMsg(!window.isSecureContext || !navigator.mediaDevices
        ? 'Recording needs a secure connection (HTTPS) — this page was loaded over plain HTTP.'
        : name === 'NotFoundError'
          ? 'No microphone found on this device.'
          : 'Microphone access denied — enable it for this site in your browser settings.');
      setStatusBoth('idle');
      return;
    }

    let session: LiveSessionInfo;
    try {
      session = await api<LiveSessionInfo>(`${apiPrefix}/live/start`, {
        method: 'POST',
        body: JSON.stringify({
          prep_note: prepNote || '',
          conversation_id: optsRef.current.conversationId,
        }),
      });
    } catch (e) {
      stream.getTracks().forEach(t => t.stop());
      setErrorMsg(e instanceof Error ? e.message : 'Could not start the live session.');
      setStatusBoth('idle');
      return;
    }

    sessionRef.current = session;
    startedAtMsRef.current = parseServerTimestamp(session.started_at)?.getTime() ?? Date.now();
    nextIndexRef.current = (session.last_chunk_index ?? -1) + 1;
    stopRequestedRef.current = false;
    streamRef.current = stream;
    optsRef.current.onSessionConversation(session.conversation_id);
    setStatusBoth('recording');
    void acquireWakeLock();
    connectSSE(session.session_id);
    startRecorderLoop(stream);
  }, [acquireWakeLock, apiPrefix, connectSSE, setStatusBoth, startRecorderLoop]);

  const stop = useCallback(() => {
    const s = statusRef.current;
    if (!['recording', 'suspended', 'tap_to_resume'].includes(s)) return;
    setStatusBoth('stopping');
    stopRequestedRef.current = true;
    stopRecorderInstance('final'); // onstop enqueues the final blob → pumpQueue → POST stop
    releaseWakeLock();
    void pumpQueue(); // covers suspended/tap_to_resume (no active recorder)
  }, [pumpQueue, releaseWakeLock, setStatusBoth, stopRecorderInstance]);

  const resume = useCallback(() => {
    if (statusRef.current !== 'tap_to_resume' && statusRef.current !== 'suspended') return;
    void attemptResume();
  }, [attemptResume]);

  const dismissDone = useCallback(() => {
    setDoneInfo(null);
    sessionRef.current = null;
    setStatusBoth('idle');
  }, [setStatusBoth]);

  const downloadRecording = useCallback(async () => {
    const url = doneInfo?.audio_url;
    if (!url) return;
    try {
      const res = await fetch(url, { headers: authOnly() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${(doneInfo?.title || 'meeting').replace(/[^\w\- ]+/g, '')}.mp3`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      setErrorMsg('Recording download failed.');
    }
  }, [doneInfo]);

  // ── Elapsed ticker ──────────────────────────────────────────────────────
  useEffect(() => {
    const active = ['recording', 'suspended', 'tap_to_resume', 'stopping', 'finalizing'].includes(status);
    if (!active) return;
    const tick = () => setElapsedSec((Date.now() - startedAtMsRef.current) / 1000);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [status]);

  // ── Visibility: re-acquire wake lock, auto-resume after suspend ─────────
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return; // hidden: do nothing
      if (statusRef.current === 'recording') void acquireWakeLock();
      else if (statusRef.current === 'suspended') void attemptResume();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [acquireWakeLock, attemptResume]);

  // ── Reattach on mount / teardown on unmount (suspend, never stop) ───────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { active } = await api<{ active: LiveSessionInfo | null }>('/api/live/active');
        if (cancelled || !active) return;
        if (active.agent_id !== agentId) {
          setForeignSession(active);
          return;
        }
        sessionRef.current = active;
        startedAtMsRef.current = parseServerTimestamp(active.started_at)?.getTime() ?? Date.now();
        nextIndexRef.current = (active.last_chunk_index ?? -1) + 1;
        optsRef.current.onSessionConversation(active.conversation_id);
        // Never auto-grab the mic on page load — a reload is a fresh gesture
        // context and iOS requires the tap anyway.
        setStatusBoth(active.state === 'finalizing' ? 'finalizing' : 'tap_to_resume');
        connectSSE(active.session_id);
      } catch { /* no active session or auth handled elsewhere */ }
    })();

    return () => {
      cancelled = true;
      // Teardown = suspend: the server session survives; /live/active
      // re-adopts it. Un-uploaded queue contents are dropped (bounded loss).
      sseAbortRef.current?.abort();
      if (chunkTimerRef.current) clearTimeout(chunkTimerRef.current);
      const rec = recorderRef.current;
      if (rec && rec.state !== 'inactive') { stopReasonRef.current = 'suspend'; try { rec.stop(); } catch { /* gone */ } }
      recorderRef.current = null;
      streamRef.current?.getTracks().forEach(t => { t.onended = null; t.stop(); });
      streamRef.current = null;
      releaseWakeLock();
      queueRef.current = [];
      sessionRef.current = null;
      statusRef.current = 'idle';
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiPrefix]);

  return {
    status,
    elapsedSec,
    pendingUploads,
    errorMsg,
    foreignSession,
    doneInfo,
    sessionConversationId: sessionRef.current?.conversation_id ?? null,
    start,
    stop,
    resume,
    dismissDone,
    downloadRecording,
  };
}
