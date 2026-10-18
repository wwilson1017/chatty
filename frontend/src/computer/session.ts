/**
 * Chatty — the viewer's control-session bookkeeping, kept pure so it is testable
 * without a DOM. ComputerPage owns sessionStorage; this decides what the stored
 * value means.
 */

export type Mode = 'view' | 'control';

export const SESSION_KEY = 'chatty_control_session'; // JSON {agent, id}

/** The control session id this tab kept for `agent`, or null (other agent, nothing stored, garbage). */
export function parseStoredControl(raw: string | null, agent: string): string | null {
  try {
    const v = JSON.parse(raw || 'null') as { agent?: unknown; id?: unknown } | null;
    return v && v.agent === agent && typeof v.id === 'string' && v.id ? v.id : null;
  } catch {
    return null;
  }
}

/**
 * Which mode the page opens in. A reload mid-control must come back in control:
 * the computer keeps the session until its grace ends, and a page that merely
 * watches would leave the helper paused and the user unable to type.
 */
export function initialMode(modeParam: string | null, storedId: string | null): Mode {
  return modeParam === 'control' || storedId ? 'control' : 'view';
}
