/**
 * Chatty — toast store tests. Pure node, no DOM: only the module-level
 * singleton store is exercised, not ToastViewport.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { toast, getToasts, dismissToast, subscribeToasts, _resetForTesting } from './toast';

beforeEach(() => {
  _resetForTesting();
});

describe('toast store', () => {
  it('caps the stack at 5 and drops the oldest toast', () => {
    for (let i = 1; i <= 6; i++) toast.info(`message ${i}`);
    const items = getToasts();
    expect(items).toHaveLength(5);
    expect(items.some(t => t.message === 'message 1')).toBe(false);
    expect(items[items.length - 1].message).toBe('message 6');
  });

  it('dismissToast removes the right item and notifies subscribers', () => {
    toast.info('first');
    toast.info('second');
    const [first, second] = getToasts();
    const listener = vi.fn();
    subscribeToasts(listener);

    dismissToast(first.id);

    const items = getToasts();
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe(second.id);
    expect(items[0].message).toBe('second');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('dismissToast with an unknown id does not notify subscribers', () => {
    toast.info('only');
    const listener = vi.fn();
    subscribeToasts(listener);

    dismissToast(99999);

    expect(getToasts()).toHaveLength(1);
    expect(listener).not.toHaveBeenCalled();
  });

  it('an unsubscribed listener is no longer called', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToasts(listener);

    toast.info('a');
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    toast.info('b');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('maps severity to duration: error 7000, success/info 4000', () => {
    toast.error('e');
    toast.success('s');
    toast.info('i');
    const [e, s, i] = getToasts();
    expect(e.severity).toBe('error');
    expect(e.duration).toBe(7000);
    expect(s.severity).toBe('success');
    expect(s.duration).toBe(4000);
    expect(i.severity).toBe('info');
    expect(i.duration).toBe(4000);
  });
});
