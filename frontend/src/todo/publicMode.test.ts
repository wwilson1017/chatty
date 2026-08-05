/**
 * Chatty — todo public-mode base detection tests.
 *
 * publicMode.ts resolves the router basename once at module load, so each
 * case stubs `window` (the vitest environment is plain node) and re-imports
 * the module fresh.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';

async function load(win: Record<string, unknown>) {
  vi.resetModules();
  vi.stubGlobal('window', win);
  return await import('./publicMode');
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TODO_PUBLIC_BASE detection', () => {
  it('prefers the backend-injected base over the URL', async () => {
    const mod = await load({
      __CHATTY_TODO_BASE__: '/todo/tok',
      location: { pathname: '/todo/next' },
    });
    expect(mod.TODO_PUBLIC_BASE).toBe('/todo/tok');
    expect(mod.TODO_API_BASE).toBe('/api/todo-web/tok');
  });

  it('reads a page slug after /todo as a route, not a token', async () => {
    const mod = await load({ location: { pathname: '/todo/next' } });
    expect(mod.TODO_PUBLIC_BASE).toBe('/todo');
    expect(mod.TODO_API_BASE).toBe('/api/todo-web');
  });

  it("never reads the reserved 'todos' segment as a token", async () => {
    // The backend rejects 'todos' as a token (it would shadow the
    // /api/todo-web/{token} mount), so the dev fallback must agree.
    const mod = await load({ location: { pathname: '/todo/todos' } });
    expect(mod.TODO_PUBLIC_BASE).toBe('/todo');
    expect(mod.TODO_API_BASE).toBe('/api/todo-web');
  });

  it('reads a non-slug segment after /todo as the token', async () => {
    const mod = await load({ location: { pathname: '/todo/abc123' } });
    expect(mod.TODO_PUBLIC_BASE).toBe('/todo/abc123');
    expect(mod.TODO_API_BASE).toBe('/api/todo-web/abc123');
  });

  it('stays in dashboard mode on non-/todo paths', async () => {
    const mod = await load({ location: { pathname: '/agents/frank' } });
    expect(mod.TODO_PUBLIC_BASE).toBeNull();
    expect(mod.isTodoPublicMode).toBe(false);
    expect(mod.TODO_API_BASE).toBe('/api/todo');
    expect(mod.todoPath('/x')).toBe('/todos/x');
  });
});
