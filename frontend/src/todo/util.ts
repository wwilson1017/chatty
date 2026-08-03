// SQLite timestamps are UTC "YYYY-MM-DD HH:MM:SS" — normalize before parsing.
export function parseDbDate(s: string): Date {
  return new Date(s.includes('T') ? s : s.replace(' ', 'T') + 'Z');
}

export function daysSince(s: string): number {
  return Math.floor((Date.now() - parseDbDate(s).getTime()) / 86_400_000);
}

export function formatAge(s: string): string {
  const days = daysSince(s);
  if (days <= 0) return 'today';
  if (days === 1) return '1d';
  return `${days}d`;
}

export function todayStr(): string {
  // Local date parts, NOT toISOString(): due dates carry the user's local
  // intent, and the UTC date would flip items to "overdue" mid-evening.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function parseTags(input: string): string[] {
  return input.split(',').map(t => t.trim()).filter(Boolean);
}

// Client-side filter behind the per-tab search boxes. Context is an exact
// (case-insensitive) match; search is a substring match across title, notes,
// context, project name, and tags.
export function matchesFilter(
  todo: {
    title: string; notes: string; context: string;
    project_name: string | null; tags: string[];
  },
  search: string,
  context = '',
): boolean {
  if (context && todo.context.toLowerCase() !== context.toLowerCase()) return false;
  const q = search.trim().toLowerCase();
  if (!q) return true;
  return [todo.title, todo.notes, todo.context, todo.project_name || '', ...todo.tags]
    .some(field => field.toLowerCase().includes(q));
}
