import { describe, it, expect } from 'vitest';
import { nextActionCopyText, todoCopyText, type TodoCopyFields } from './copyText';

const base: TodoCopyFields = {
  title: 'Call the plumber about the upstairs sink',
  notes: '',
  status: 'next_action',
  projectName: null,
  context: '',
  tags: [],
  dueDate: null,
  repeat: '',
  star: false,
};

describe('nextActionCopyText', () => {
  it('is the bare action, with no label to delete after pasting', () => {
    expect(nextActionCopyText('  Call the plumber  ')).toBe('Call the plumber');
  });
});

describe('todoCopyText', () => {
  it('omits every unset field rather than printing it empty', () => {
    expect(todoCopyText(base)).toBe(
      'Call the plumber about the upstairs sink\n\nStatus: Next Action',
    );
  });

  it('renders the set fields in a fixed order under the action', () => {
    expect(todoCopyText({
      ...base,
      notes: 'He quoted $200 last time.\nAsk about the warranty.',
      projectName: 'House repairs',
      context: '@calls',
      tags: ['home', 'urgent'],
      dueDate: '2026-08-15',
      repeat: 'weekly',
      star: true,
    })).toBe(
      'Call the plumber about the upstairs sink\n'
      + '\n'
      + 'Status: Next Action\n'
      + 'Project: House repairs\n'
      + 'Context: @calls\n'
      + 'Due: 2026-08-15\n'
      + 'Repeat: weekly\n'
      + 'Tags: home, urgent\n'
      + 'Starred: yes\n'
      + '\n'
      + 'Notes:\n'
      + 'He quoted $200 last time.\n'
      + 'Ask about the warranty.',
    );
  });

  it('drops notes that are only whitespace', () => {
    expect(todoCopyText({ ...base, notes: '   \n  ' })).toBe(todoCopyText(base));
  });
});
