/**
 * Chatty — styled confirm store, a drop-in replacement for native confirm():
 *
 *   if (!await confirmDialog({ title: 'Delete report', message: '...', danger: true })) return;
 *
 * Module-level singleton (same mechanism as toast.ts) so it works inside
 * plain async handlers and hooks without threading React context.
 * ConfirmHost (mounted once in App.tsx) renders the head of the FIFO queue.
 */

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

export interface PendingConfirm {
  id: number;
  options: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

let queue: PendingConfirm[] = [];
let listeners: Array<() => void> = [];
let nextId = 1;

function emit() {
  for (const listener of listeners) listener();
}

export function subscribeConfirms(onChange: () => void): () => void {
  listeners.push(onChange);
  return () => {
    listeners = listeners.filter(l => l !== onChange);
  };
}

export function getCurrentConfirm(): PendingConfirm | null {
  return queue[0] ?? null;
}

export function settleConfirm(ok: boolean) {
  const head = queue[0];
  if (!head) return;
  queue = queue.slice(1);
  emit();
  head.resolve(ok);
}

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  // A duplicate trigger (double-click before the overlay paints) is a no-op:
  // resolving false for the duplicate preserves native confirm()'s
  // one-dialog-one-action semantics. Sharing the pending promise instead
  // would run the action twice on confirm. Only the queue head (the visible
  // dialog) is compared — a distinct queued action that happens to share the
  // same copy must still be asked, not silently dropped.
  const head = queue[0];
  if (head && head.options.title === options.title && head.options.message === options.message) {
    return Promise.resolve(false);
  }
  return new Promise<boolean>(resolve => {
    queue = [...queue, { id: nextId++, options, resolve }];
    emit();
  });
}

// test-only: singletons persist across module imports
export function _resetForTesting() {
  queue = [];
  listeners = [];
  nextId = 1;
}
