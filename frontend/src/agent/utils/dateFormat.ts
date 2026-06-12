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

// 'en-CA' formats as YYYY-MM-DD — used as a day key in the browser's local timezone
function localDayKey(d: Date): string {
  return d.toLocaleDateString('en-CA');
}

export function localDateKey(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  return d ? localDayKey(d) : '';
}

function localDaysAgo(then: Date, now: Date): number {
  const a = new Date(localDayKey(then) + 'T00:00:00Z').getTime();
  const b = new Date(localDayKey(now) + 'T00:00:00Z').getTime();
  return Math.round((b - a) / 86_400_000);
}

function localTime(d: Date): string {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export function formatSidebarTime(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  const days = localDaysAgo(d, new Date());
  if (days <= 0) return localTime(d);
  if (days === 1) return 'Yesterday';
  if (days < 7) return d.toLocaleDateString('en-US', { weekday: 'short' });
  return d.toLocaleDateString('en-US', {
    month: 'numeric', day: 'numeric', year: '2-digit',
  });
}

export function formatBubbleTime(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  return localTime(d);
}

export function timeAgo(value: string | number | null | undefined): string {
  const d = parseServerTimestamp(value);
  if (!d) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return 'Just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

export function formatDateDivider(value: string | number | null | undefined): string {
  if (value === 0) return '';
  const d = parseServerTimestamp(value);
  if (!d) return '';
  const now = new Date();
  const days = localDaysAgo(d, now);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days <= 6) return d.toLocaleDateString('en-US', { weekday: 'long' });
  const sameYear = d.getFullYear() === now.getFullYear();
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}
