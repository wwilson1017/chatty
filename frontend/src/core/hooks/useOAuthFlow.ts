/**
 * Chatty — shared OAuth flow hook.
 *
 * Drives the two-step OAuth pattern:
 *   1. POST {setupUrl} → { flow_id, auth_url }
 *   2. Open auth_url in a popup
 *   3. Poll /api/oauth/flows/{flow_id}/status every ~1.5s
 *   4. When status === 'ok', POST {completeUrl} with { flow_id, ...completeBody }
 *
 * Works on Railway deploys because the popup redirects back to
 * `{backend_url}/api/oauth/callback`, not localhost.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

export type OAuthFlowStatus =
  | 'idle'
  | 'starting'          // hitting /setup to get auth_url
  | 'awaiting_user'     // popup open, polling for completion
  | 'completing'        // status:ok received, calling /setup/complete
  | 'success'
  | 'error';

export interface OAuthFlowState {
  status: OAuthFlowStatus;
  error?: string;
  result?: unknown;     // whatever /setup/complete returned
}

interface StartOpts {
  /** Endpoint that returns { flow_id, auth_url }. */
  setupUrl: string;
  /** Optional body sent to setupUrl (e.g. scope selection). */
  setupBody?: unknown;
  /** Endpoint called with { flow_id, ...completeBody } once the popup finishes. */
  completeUrl: string;
  /** Extra fields merged into the completion POST body. */
  completeBody?: Record<string, unknown>;
  /** How often to poll for status (ms). Default 1500. */
  pollIntervalMs?: number;
  /** Total timeout for the OAuth flow (ms). Default 5 minutes. */
  timeoutMs?: number;
  /** Popup window dimensions. */
  popupWidth?: number;
  popupHeight?: number;
}

interface SetupResponse {
  flow_id: string;
  auth_url: string;
}

interface FlowStatusResponse {
  status: 'pending' | 'ok' | 'error';
  error?: string | null;
}

export function useOAuthFlow() {
  const [state, setState] = useState<OAuthFlowState>({ status: 'idle' });
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const popupRef = useRef<Window | null>(null);
  const timeoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    if (timeoutTimer.current) {
      clearTimeout(timeoutTimer.current);
      timeoutTimer.current = null;
    }
  }, []);

  const tryClosePopup = useCallback(() => {
    try {
      popupRef.current?.close();
    } catch {
      /* cross-origin close can throw; ignore */
    }
    popupRef.current = null;
  }, []);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      cleanup();
      tryClosePopup();
    };
  }, [cleanup, tryClosePopup]);

  const reset = useCallback(() => {
    cleanup();
    tryClosePopup();
    setState({ status: 'idle' });
  }, [cleanup, tryClosePopup]);

  const start = useCallback(
    async (opts: StartOpts) => {
      const pollInterval = opts.pollIntervalMs ?? 1500;
      const timeoutMs = opts.timeoutMs ?? 5 * 60 * 1000;
      const popupW = opts.popupWidth ?? 520;
      const popupH = opts.popupHeight ?? 720;

      cleanup();
      tryClosePopup();
      setState({ status: 'starting' });

      // 1. Hit /setup to get {flow_id, auth_url}
      let setupResp: SetupResponse;
      try {
        setupResp = await api<SetupResponse>(opts.setupUrl, {
          method: 'POST',
          body: opts.setupBody ? JSON.stringify(opts.setupBody) : undefined,
        });
      } catch (err: unknown) {
        setState({ status: 'error', error: err instanceof Error ? err.message : 'Setup failed' });
        return;
      }

      const { flow_id, auth_url } = setupResp;

      // 2. Open popup
      const left = window.screenX + (window.outerWidth - popupW) / 2;
      const top = window.screenY + (window.outerHeight - popupH) / 2;
      popupRef.current = window.open(
        auth_url,
        'chatty_oauth',
        `width=${popupW},height=${popupH},left=${left},top=${top}`,
      );
      if (!popupRef.current) {
        setState({
          status: 'error',
          error: 'Popup blocked. Please allow popups for this site and try again.',
        });
        return;
      }
      setState({ status: 'awaiting_user' });

      // 3. Start polling + overall timeout
      timeoutTimer.current = setTimeout(() => {
        cleanup();
        tryClosePopup();
        setState({ status: 'error', error: 'OAuth flow timed out. Please try again.' });
      }, timeoutMs);

      let popupClosedAt: number | null = null;

      pollTimer.current = setInterval(async () => {
        // Track when popup closes so we can fail fast if we never got a callback
        if (!popupClosedAt && popupRef.current?.closed) {
          popupClosedAt = Date.now();
        }

        let status: FlowStatusResponse;
        try {
          status = await api<FlowStatusResponse>(`/api/oauth/flows/${flow_id}/status`);
        } catch (err: unknown) {
          // 404 means the flow expired or was cleaned up
          cleanup();
          tryClosePopup();
          setState({
            status: 'error',
            error: err instanceof Error ? err.message : 'Flow status lookup failed',
          });
          return;
        }

        if (status.status === 'ok') {
          cleanup();
          setState({ status: 'completing' });
          try {
            const result = await api(opts.completeUrl, {
              method: 'POST',
              body: JSON.stringify({ flow_id, ...(opts.completeBody ?? {}) }),
            });
            tryClosePopup();
            setState({ status: 'success', result });
          } catch (err: unknown) {
            tryClosePopup();
            setState({
              status: 'error',
              error: err instanceof Error ? err.message : 'Finalization failed',
            });
          }
          return;
        }

        if (status.status === 'error') {
          cleanup();
          tryClosePopup();
          setState({
            status: 'error',
            error: status.error || 'OAuth flow failed',
          });
          return;
        }

        // status === 'pending': if the popup was closed more than 3s ago and
        // we still haven't seen tokens, the user likely dismissed the dialog.
        if (popupClosedAt && Date.now() - popupClosedAt > 3000) {
          cleanup();
          setState({
            status: 'error',
            error: 'Authorization window was closed before completing.',
          });
        }
      }, pollInterval);
    },
    [cleanup, tryClosePopup],
  );

  return { state, start, reset };
}
