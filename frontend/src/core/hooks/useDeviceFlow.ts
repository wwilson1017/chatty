/**
 * Chatty — device-code login poller for Printing Press CLIs that support it.
 *
 * Starts the CLI's own device flow (the CLI owns the token), shows the user a
 * code + verification URL, and polls until the CLI reports authorized. Modeled
 * on useOAuthFlow but with a code panel instead of a popup.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

interface Flow {
  flow_id: string;
  user_code: string;
  verification_uri: string;
}

export type DeviceStatus = 'idle' | 'pending' | 'authorized' | 'error';

export function useDeviceFlow(slug: string) {
  const [flow, setFlow] = useState<Flow | null>(null);
  const [status, setStatus] = useState<DeviceStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) { clearInterval(timer.current); timer.current = null; }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    try {
      const f = await api<Flow>(`/api/printing-press/${slug}/auth/device`, { method: 'POST' });
      setFlow(f);
      setStatus('pending');
    } catch (e) {
      setStatus('error');
      setError(e instanceof Error ? e.message : 'Could not start device login');
    }
  }, [slug]);

  useEffect(() => {
    if (status !== 'pending' || !flow) return;
    timer.current = setInterval(async () => {
      try {
        const s = await api<{ status: string; error: string | null }>(
          `/api/printing-press/${slug}/auth/device/${flow.flow_id}`,
        );
        if (s.status === 'authorized') { setStatus('authorized'); stop(); }
        else if (s.status === 'error' || s.status === 'expired') {
          setStatus('error'); setError(s.error || s.status); stop();
        }
      } catch {
        /* transient; keep polling */
      }
    }, 2500);
    return stop;
  }, [status, flow, slug, stop]);

  useEffect(() => stop, [stop]);

  return { flow, status, error, start };
}
