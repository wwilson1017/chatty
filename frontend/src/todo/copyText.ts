// Todo GTD — plain-text renderings of a todo, for the edit sheet's two Copy
// buttons.
//
// Mirrored byte-for-byte in CAKE OS (`frontend/src/apps/todo-gtd/copyText.ts`)
// so a todo copied out of either app pastes identically. Keep the two in sync;
// the shape is pinned by copyText.test.ts on both sides.
//
// Pure on purpose: the sheet renders from live FORM state, not from the saved
// row, so what you copy is what is on screen — including edits you have not
// saved yet.

import { STATUS_META } from './constants';
import type { TodoStatus } from '../core/types';

export interface TodoCopyFields {
  title: string;
  notes: string;
  status: TodoStatus;
  /** Resolved project NAME, not its id — "" / null when unfiled. */
  projectName: string | null;
  context: string;
  tags: string[];
  dueDate: string | null;
  /** Repeat rule as stored: '' | daily | weekly | … | every:N */
  repeat: string;
  star: boolean;
}

/**
 * Just the next action — the single line you paste into a message, a calendar
 * entry, or another list. No label, no decoration: pasting should give you the
 * action and nothing to delete afterwards.
 */
export function nextActionCopyText(title: string): string {
  return title.trim();
}

/**
 * The whole todo as plain text: the action on line one, then only the fields
 * that are actually set, then the notes. Absent fields are omitted rather than
 * printed empty — a pasted todo should read like a note, not like a form dump.
 */
export function todoCopyText(f: TodoCopyFields): string {
  const blocks: string[] = [f.title.trim()];

  const meta: string[] = [`Status: ${STATUS_META[f.status].label}`];
  if (f.projectName) meta.push(`Project: ${f.projectName}`);
  if (f.context.trim()) meta.push(`Context: ${f.context.trim()}`);
  if (f.dueDate) meta.push(`Due: ${f.dueDate}`);
  if (f.repeat) meta.push(`Repeat: ${f.repeat}`);
  if (f.tags.length) meta.push(`Tags: ${f.tags.join(', ')}`);
  if (f.star) meta.push('Starred: yes');
  blocks.push(meta.join('\n'));

  const notes = f.notes.trim();
  if (notes) blocks.push(`Notes:\n${notes}`);

  return blocks.join('\n\n');
}
