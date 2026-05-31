const CT = 'America/Chicago';

export function parseServerTimestamp(value: string | number | null | undefined): Date | null {
  if (value == null || value === '') return null;
  if (typeof value === 'number') {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  // SQLite datetime('now') returns UTC without a timezone marker (e.g. "2026-05-30 14:23:11")
  const sqliteNaive =
    /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(value) &&
    !value.includes('Z') &&
    !/[+-]\d\d:?\d\d$/.test(value);
  const d = sqliteNaive ? new Date(value.replace(' ', 'T') + 'Z') : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function ctDayKey(d: Date): string {
  return d.toLocaleDateString('en-CA', { timeZone: CT });
}

export function ctDateKey(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  return d ? ctDayKey(d) : '';
}

function ctDaysAgo(then: Date, now: Date): number {
  const a = new Date(ctDayKey(then) + 'T00:00:00Z').getTime();
  const b = new Date(ctDayKey(now) + 'T00:00:00Z').getTime();
  return Math.round((b - a) / 86_400_000);
}

function ctTime(d: Date): string {
  return d.toLocaleTimeString('en-US', { timeZone: CT, hour: 'numeric', minute: '2-digit' });
}

export function formatSidebarTime(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  const days = ctDaysAgo(d, new Date());
  if (days <= 0) return ctTime(d);
  if (days === 1) return 'Yesterday';
  if (days < 7) return d.toLocaleDateString('en-US', { timeZone: CT, weekday: 'short' });
  return d.toLocaleDateString('en-US', {
    timeZone: CT, month: 'numeric', day: 'numeric', year: '2-digit',
  });
}

export function formatBubbleTime(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  return ctTime(d);
}

export function formatDateDivider(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  const now = new Date();
  const days = ctDaysAgo(d, now);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days <= 6) return d.toLocaleDateString('en-US', { timeZone: CT, weekday: 'long' });
  const sameYear =
    d.toLocaleDateString('en-US', { timeZone: CT, year: 'numeric' }) ===
    now.toLocaleDateString('en-US', { timeZone: CT, year: 'numeric' });
  return d.toLocaleDateString('en-US', {
    timeZone: CT, month: 'short', day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}
