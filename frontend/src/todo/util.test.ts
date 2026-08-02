/**
 * Chatty — todo date/tag helper tests. Pure node, no DOM. These helpers
 * drive user-visible behavior: Review-page staleness, "waiting Nd" ages,
 * and overdue highlighting.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { parseDbDate, daysSince, formatAge, parseTags, todayStr } from './util';

describe('parseDbDate', () => {
  it('treats SQLite "YYYY-MM-DD HH:MM:SS" timestamps as UTC', () => {
    const d = parseDbDate('2026-08-02 15:30:00');
    expect(d.toISOString()).toBe('2026-08-02T15:30:00.000Z');
  });

  it('passes ISO strings with T through unchanged', () => {
    const d = parseDbDate('2026-08-02T15:30:00.000Z');
    expect(d.toISOString()).toBe('2026-08-02T15:30:00.000Z');
  });
});

describe('daysSince / formatAge', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-15T12:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns 0 / "today" for a same-day timestamp', () => {
    expect(daysSince('2026-08-15 08:00:00')).toBe(0);
    expect(formatAge('2026-08-15 08:00:00')).toBe('today');
  });

  it('floors partial days (23h ago is still day 0)', () => {
    expect(daysSince('2026-08-14 13:00:00')).toBe(0);
  });

  it('returns "1d" at exactly one day and "Nd" beyond', () => {
    expect(formatAge('2026-08-14 12:00:00')).toBe('1d');
    expect(daysSince('2026-08-01 12:00:00')).toBe(14);
    expect(formatAge('2026-08-01 12:00:00')).toBe('14d');
  });

  it('todayStr returns the UTC date used for overdue comparisons', () => {
    expect(todayStr()).toBe('2026-08-15');
  });
});

describe('parseTags', () => {
  it('splits on commas, trims, and drops empties', () => {
    expect(parseTags(' home ,  energy:low ,, ')).toEqual(['home', 'energy:low']);
    expect(parseTags('')).toEqual([]);
    expect(parseTags('solo')).toEqual(['solo']);
  });
});
