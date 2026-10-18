/**
 * Chatty — viewer session helpers. Pure node, no DOM.
 */

import { describe, it, expect } from 'vitest';
import { initialMode, parseStoredControl } from './session';

describe('initialMode', () => {
  it('a plain link watches', () => {
    expect(initialMode(null, null)).toBe('view');
  });

  it('?mode=control starts in control even with nothing stored', () => {
    expect(initialMode('control', null)).toBe('control');
  });

  it('a reload mid-control comes back in control, not watching', () => {
    expect(initialMode(null, 'cs-1')).toBe('control');
  });

  it('an unknown mode param is just a watch', () => {
    expect(initialMode('owner', null)).toBe('view');
  });
});

describe('parseStoredControl', () => {
  it('returns the id stored for this agent', () => {
    expect(parseStoredControl(JSON.stringify({ agent: 'tom', id: 'cs-1' }), 'tom')).toBe('cs-1');
  });

  it("ignores another agent's session", () => {
    expect(parseStoredControl(JSON.stringify({ agent: 'tom', id: 'cs-1' }), 'sam')).toBeNull();
  });

  it('survives garbage and empty values', () => {
    expect(parseStoredControl(null, 'tom')).toBeNull();
    expect(parseStoredControl('not json', 'tom')).toBeNull();
    expect(parseStoredControl(JSON.stringify({ agent: 'tom', id: '' }), 'tom')).toBeNull();
    expect(parseStoredControl(JSON.stringify({ agent: 'tom', id: 7 }), 'tom')).toBeNull();
  });
});
