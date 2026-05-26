import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../core/api/client';

// ── Types ────────────────────────────────────────────────────────────────────

export interface ScheduledAction {
  id: string;
  agent: string;
  action_type: string;
  schedule_type: string;
  name: string;
  description: string;
  interval_minutes: number | null;
  cron_expression: string | null;
  active_hours_start: string;
  active_hours_end: string;
  active_hours_tz: string;
  model_override: string | null;
  max_tool_iterations: number;
  triage_enabled: boolean;
  enabled: boolean;
  always_on: boolean;
  next_run: string | null;
  last_run: string | null;
  last_status: string | null;
  last_result: string | null;
  last_duration_ms: number | null;
  total_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  consecutive_errors: number;
}

export interface ActivityRecord {
  id: string;
  agent: string;
  action_type: string;
  started_at: string;
  status: string;
  result_summary: string | null;
  result_full: string | null;
  tool_calls: { tool: string; args: Record<string, unknown>; result: string; duration_ms: number }[] | null;
  model_used: string | null;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
}

export interface ParsedLine {
  type: 'heading' | 'blank' | 'passthrough' | 'list-item';
  raw: string;
  prefix?: string;
  text?: string;
  checked?: boolean;
  id?: string;
}

// ── Parsing ──────────────────────────────────────────────────────────────────

export function parseHeartbeat(markdown: string): { lines: ParsedLine[]; canEditCards: boolean } {
  if (!markdown.trim()) return { lines: [], canEditCards: true };

  const lines: ParsedLine[] = [];
  let hasIndented = false;

  for (const line of markdown.split('\n')) {
    const trimmed = line.trim();

    if (!trimmed) { lines.push({ type: 'blank', raw: line }); continue; }
    if (trimmed.startsWith('#')) { lines.push({ type: 'heading', raw: line }); continue; }

    const indent = line.length - line.trimStart().length;
    if (indent > 0 && /^[-*]/.test(trimmed)) {
      hasIndented = true;
      lines.push({ type: 'passthrough', raw: line });
      continue;
    }

    const checkboxMatch = trimmed.match(/^([-*]\s*\[[ xX]\]\s*)(.+)$/);
    if (checkboxMatch) {
      lines.push({
        type: 'list-item', raw: line,
        prefix: checkboxMatch[1],
        checked: /\[[xX]\]/.test(checkboxMatch[1]),
        text: checkboxMatch[2],
        id: crypto.randomUUID(),
      });
      continue;
    }

    const listMatch = trimmed.match(/^([-*]\s+)(.+)$/);
    if (listMatch) {
      lines.push({
        type: 'list-item', raw: line,
        prefix: listMatch[1],
        text: listMatch[2],
        id: crypto.randomUUID(),
      });
      continue;
    }

    lines.push({ type: 'passthrough', raw: line });
  }

  return { lines, canEditCards: !hasIndented };
}

export function serializeHeartbeat(lines: ParsedLine[]): string {
  return lines.map(line => {
    if (line.type === 'list-item') {
      const bullet = line.prefix?.startsWith('*') ? '*' : '-';
      if (line.checked !== undefined) {
        return `${bullet} ${line.checked ? '[x]' : '[ ]'} ${line.text}`;
      }
      return `${bullet} ${line.text}`;
    }
    return line.raw;
  }).join('\n');
}

// ── Boolean normalization (SQLite returns 0|1) ──────────────────────────────

function normalizeAction(raw: Record<string, unknown>): ScheduledAction {
  return {
    ...raw,
    enabled: Boolean(raw.enabled),
    always_on: Boolean(raw.always_on),
    triage_enabled: Boolean(raw.triage_enabled),
  } as ScheduledAction;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

interface UseHeartbeatResult {
  action: ScheduledAction | null;
  parsedLines: ParsedLine[];
  canEditCards: boolean;
  rawMarkdown: string;
  history: ActivityRecord[];
  loading: boolean;
  running: boolean;
  actionError: boolean;
  countdown: string;
  runNow: () => Promise<void>;
  toggleEnabled: () => Promise<void>;
  updateConfig: (fields: Record<string, unknown>) => Promise<void>;
  saveChecklist: (lines: ParsedLine[]) => Promise<void>;
  saveRawChecklist: (raw: string) => Promise<void>;
  refetchAll: () => Promise<void>;
}

export function useHeartbeat(agentSlug: string, apiPrefix: string): UseHeartbeatResult {
  const [action, setAction] = useState<ScheduledAction | null>(null);
  const [parsedLines, setParsedLines] = useState<ParsedLine[]>([]);
  const [canEditCards, setCanEditCards] = useState(true);
  const [rawMarkdown, setRawMarkdown] = useState('');
  const [history, setHistory] = useState<ActivityRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [countdown, setCountdown] = useState('');
  const [actionError, setActionError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const mountedRef = useRef(true);

  const fetchAction = useCallback(async () => {
    try {
      const data = await api<{ actions: Record<string, unknown>[] }>(`/api/scheduled-actions/${agentSlug}`);
      const hb = data.actions.find((a) => a.action_type === 'heartbeat');
      if (hb && mountedRef.current) {
        setAction(normalizeAction(hb));
        setActionError(false);
      }
    } catch {
      if (mountedRef.current) setActionError(true);
    }
  }, [agentSlug]);

  const fetchChecklist = useCallback(async () => {
    try {
      const data = await api<{ content: string }>(`${apiPrefix}/context/HEARTBEAT.md`);
      if (!mountedRef.current) return;
      setRawMarkdown(data.content);
      const parsed = parseHeartbeat(data.content);
      setParsedLines(parsed.lines);
      setCanEditCards(parsed.canEditCards);
    } catch (e) {
      if (mountedRef.current && e instanceof Error && e.message.includes('404')) {
        setRawMarkdown('');
        setParsedLines([]);
        setCanEditCards(true);
      }
    }
  }, [apiPrefix]);

  const fetchHistory = useCallback(async () => {
    try {
      const data = await api<{ activities: ActivityRecord[] }>(`${apiPrefix}/activity?limit=30`);
      if (!mountedRef.current) return;
      setHistory(data.activities.filter(r => r.action_type === 'heartbeat' || r.action_type === 'cron').slice(0, 10));
    } catch { /* supplementary */ }
  }, [apiPrefix]);

  const refetchAll = useCallback(async () => {
    await Promise.all([fetchAction(), fetchChecklist(), fetchHistory()]);
  }, [fetchAction, fetchChecklist, fetchHistory]);

  useEffect(() => {
    mountedRef.current = true;
    (async () => {
      await Promise.all([fetchAction(), fetchChecklist(), fetchHistory()]);
      if (mountedRef.current) setLoading(false);
    })();
    return () => { mountedRef.current = false; };
  }, [fetchAction, fetchChecklist, fetchHistory]);

  // Retry if no action found (sweeper may not have created it yet), max 3 retries
  useEffect(() => {
    if (loading || action || retryCount >= 3) {
      if (!loading && !action && retryCount >= 3 && !actionError) {
        setActionError(true);
      }
      return;
    }
    const timer = setTimeout(async () => {
      await fetchAction();
      if (mountedRef.current) setRetryCount(c => c + 1);
    }, 2000);
    return () => clearTimeout(timer);
  }, [loading, action, retryCount, actionError, fetchAction]);

  // Countdown timer
  useEffect(() => {
    if (!action?.next_run || !action.enabled || running) {
      setCountdown(running ? 'Running...' : action && !action.enabled ? 'Paused' : '--:--');
      return;
    }

    function tick() {
      const next = new Date(action!.next_run + 'Z').getTime();
      const diff = next - Date.now();
      if (diff <= 0) { setCountdown('Due now'); return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setCountdown(h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`);
    }

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [action?.next_run, action?.enabled, running]);

  const runNow = useCallback(async () => {
    if (!action) return;
    setRunning(true);
    try {
      await api(`/api/scheduled-actions/${action.id}/run-now`, { method: 'POST' });
    } catch (e) {
      if (e instanceof Error && e.message.includes('409')) {
        alert('Heartbeat is already running.');
      }
    } finally {
      setRunning(false);
      await Promise.all([fetchAction(), fetchHistory()]);
    }
  }, [action, fetchAction, fetchHistory]);

  const toggleEnabled = useCallback(async () => {
    if (!action) return;
    const next = !action.enabled;
    setAction(prev => prev ? { ...prev, enabled: next } : prev);
    try {
      await api(`/api/scheduled-actions/${action.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: next }),
      });
      await fetchAction();
    } catch {
      setAction(prev => prev ? { ...prev, enabled: !next } : prev);
    }
  }, [action, fetchAction]);

  const updateConfig = useCallback(async (fields: Record<string, unknown>) => {
    if (!action) return;
    await api(`/api/scheduled-actions/${action.id}`, {
      method: 'PATCH',
      body: JSON.stringify(fields),
    });
    await fetchAction();
  }, [action, fetchAction]);

  const saveChecklist = useCallback(async (lines: ParsedLine[]) => {
    const content = serializeHeartbeat(lines);
    await api(`${apiPrefix}/context/HEARTBEAT.md`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    });
    setRawMarkdown(content);
    setParsedLines(lines);
  }, [apiPrefix]);

  const saveRawChecklist = useCallback(async (raw: string) => {
    await api(`${apiPrefix}/context/HEARTBEAT.md`, {
      method: 'PUT',
      body: JSON.stringify({ content: raw }),
    });
    setRawMarkdown(raw);
    const parsed = parseHeartbeat(raw);
    setParsedLines(parsed.lines);
    setCanEditCards(parsed.canEditCards);
  }, [apiPrefix]);

  return {
    action, parsedLines, canEditCards, rawMarkdown, history,
    loading, running, actionError, countdown,
    runNow, toggleEnabled, updateConfig, saveChecklist, saveRawChecklist, refetchAll,
  };
}
