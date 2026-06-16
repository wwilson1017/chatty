/**
 * Chatty — live build-progress stream for Printing Press installs.
 *
 * The backend builds a CLI on a background threadpool and exposes progress as an
 * SSE stream. We consume it with `fetch` + a reader (not `EventSource`, which
 * can't send the JWT `Authorization` header).
 */

import { useCallback, useRef, useState } from 'react';
import { getToken } from '../auth/tokenUtils';

export interface BuildLine {
  phase: string;
  msg: string;
}

export type BuildStatus = 'idle' | 'streaming' | 'success' | 'error';

export function useBuildStream() {
  const [logs, setLogs] = useState<BuildLine[]>([]);
  const [status, setStatus] = useState<BuildStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef(false);

  const reset = useCallback(() => {
    setLogs([]);
    setStatus('idle');
    setError(null);
  }, []);

  const start = useCallback(async (buildId: string): Promise<BuildStatus> => {
    if (activeRef.current) return status;
    activeRef.current = true;
    setLogs([]);
    setStatus('streaming');
    setError(null);

    let final: BuildStatus = 'error';
    try {
      const token = getToken();
      const res = await fetch(`/api/printing-press/install/${buildId}/stream`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok || !res.body) {
        setStatus('error');
        setError(`Build stream failed (${res.status})`);
        return 'error';
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() ?? '';
        for (const part of parts) {
          const line = part.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'progress') {
              setLogs((prev) => [...prev, { phase: event.phase, msg: event.msg }]);
            } else if (event.type === 'done') {
              final = event.status === 'success' ? 'success' : 'error';
              setStatus(final);
              if (event.error) setError(event.error);
            }
          } catch {
            /* ignore malformed line */
          }
        }
      }
    } catch (e) {
      setStatus('error');
      setError(e instanceof Error ? e.message : 'Build stream error');
      final = 'error';
    } finally {
      activeRef.current = false;
    }
    return final;
  }, [status]);

  return { logs, status, error, start, reset };
}
