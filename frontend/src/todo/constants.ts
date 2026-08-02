import type { TodoProjectStatus, TodoSource, TodoStatus } from '../core/types';

export const TODO_STATUS_ORDER: TodoStatus[] = [
  'inbox', 'next_action', 'waiting_for', 'delegated', 'someday_maybe', 'done', 'dropped',
];

export const STATUS_META: Record<TodoStatus, { label: string; color: string; bg: string }> = {
  inbox: { label: 'Inbox', color: '#7B9EC4', bg: 'rgba(123,158,196,0.10)' },
  next_action: { label: 'Next Action', color: '#8EA589', bg: 'rgba(142,165,137,0.10)' },
  waiting_for: { label: 'Waiting For', color: '#D4A85A', bg: 'rgba(212,168,90,0.10)' },
  delegated: { label: 'Delegated', color: '#D4855A', bg: 'rgba(212,133,90,0.10)' },
  someday_maybe: { label: 'Someday / Maybe', color: '#C8D1D9', bg: 'rgba(200,209,217,0.10)' },
  done: { label: 'Done', color: '#7E8B99', bg: 'rgba(126,139,153,0.10)' },
  dropped: { label: 'Dropped', color: '#D97757', bg: 'rgba(217,119,87,0.10)' },
};

export const PROJECT_STATUS_ORDER: TodoProjectStatus[] = [
  'active', 'someday', 'completed', 'dropped',
];

export const PROJECT_STATUS_META: Record<TodoProjectStatus, { label: string; color: string; bg: string }> = {
  active: { label: 'Active', color: '#8EA589', bg: 'rgba(142,165,137,0.10)' },
  someday: { label: 'Someday', color: '#C8D1D9', bg: 'rgba(200,209,217,0.10)' },
  completed: { label: 'Completed', color: '#7E8B99', bg: 'rgba(126,139,153,0.10)' },
  dropped: { label: 'Dropped', color: '#D97757', bg: 'rgba(217,119,87,0.10)' },
};

export const SOURCE_LABELS: Record<TodoSource, string> = {
  capture_web: 'Capture',
  telegram: 'Telegram',
  agent: 'Agent',
  ui: 'Manual',
};

// Items in next_action / waiting_for / delegated untouched this long are
// flagged as stale on the Review page.
export const STALE_DAYS = 14;
