/**
 * Chatty — confirm store tests. Pure node, no DOM: only the module-level
 * singleton queue is exercised, not ConfirmHost.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { confirmDialog, settleConfirm, getCurrentConfirm, _resetForTesting } from './confirm';

beforeEach(() => {
  _resetForTesting();
});

describe('confirm store', () => {
  it('dedupes an identical call against the visible head only', async () => {
    const first = confirmDialog({ title: 'Delete file', message: 'Sure?' });
    const second = confirmDialog({ title: 'Delete file', message: 'Sure?' });

    // The duplicate resolves false immediately without enqueueing.
    await expect(second).resolves.toBe(false);
    expect(getCurrentConfirm()?.options.title).toBe('Delete file');

    // Settling the head empties the queue — proves the dupe never joined it.
    settleConfirm(true);
    await expect(first).resolves.toBe(true);
    expect(getCurrentConfirm()).toBeNull();
  });

  it('does not dedupe an identical call after the first has settled', async () => {
    const first = confirmDialog({ title: 'Delete file', message: 'Sure?' });
    settleConfirm(false);
    await expect(first).resolves.toBe(false);

    const again = confirmDialog({ title: 'Delete file', message: 'Sure?' });
    expect(getCurrentConfirm()?.options.title).toBe('Delete file');
    settleConfirm(true);
    await expect(again).resolves.toBe(true);
  });

  it('queues a distinct dialog behind the head (FIFO)', async () => {
    const first = confirmDialog({ title: 'Dialog A', message: 'same message' });
    const second = confirmDialog({ title: 'Dialog B', message: 'same message' });

    expect(getCurrentConfirm()?.options.title).toBe('Dialog A');

    settleConfirm(true);
    await expect(first).resolves.toBe(true);

    // The second dialog becomes the head after the first settles.
    expect(getCurrentConfirm()?.options.title).toBe('Dialog B');
    settleConfirm(false);
    await expect(second).resolves.toBe(false);
    expect(getCurrentConfirm()).toBeNull();
  });

  it('settleConfirm on an empty queue is a no-op', () => {
    expect(() => settleConfirm(false)).not.toThrow();
    expect(getCurrentConfirm()).toBeNull();
  });

  it('settle resolves the head promise with the given boolean', async () => {
    const accepted = confirmDialog({ title: 'Accept', message: 'ok?' });
    settleConfirm(true);
    await expect(accepted).resolves.toBe(true);

    const rejected = confirmDialog({ title: 'Reject', message: 'ok?' });
    settleConfirm(false);
    await expect(rejected).resolves.toBe(false);
  });
});
