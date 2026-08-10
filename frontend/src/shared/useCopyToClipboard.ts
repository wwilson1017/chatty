/**
 * Copy text to the clipboard with a transient "copied" flag.
 *
 * Lived under `agent/hooks/` until the todo edit sheet needed it for its two
 * Copy buttons — the dashboard was already reaching across into the agent
 * feature's private hook, which is the layering smell, so it moved here beside
 * `useIsMobile` and `toast` rather than being copied a third time.
 *
 * The failure path is deliberately quiet. `navigator.clipboard` rejects in a
 * non-secure context — a dev server or a Railway instance reached over plain
 * http on a LAN — and every surface using this is a convenience affordance, not
 * a path where losing the copy loses work.
 */
import { useState, useCallback, useRef, useEffect } from 'react';

export function useCopyToClipboard(resetMs = 1500) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), resetMs);
    } catch (err) {
      // No UI on failure — see the note above. Logged rather than swallowed
      // outright so it is at least diagnosable when it does happen.
      console.warn('Copy to clipboard failed', err);
    }
  }, [resetMs]);

  // The reset timer outlives the component otherwise: copy, then close the edit
  // sheet inside `resetMs` and the timeout fires against an unmounted one.
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  return { copied, copy };
}
