/**
 * Chatty — todo-only public mode.
 *
 * The backend serves the SPA at /todo (or /todo/{token}) with the router
 * basename injected as window.__CHATTY_TODO_BASE__ (see backend
 * core/todo/web.py). In that mode there is no login, no AppShell and no
 * dashboard — just the todo app, talking to /api/todo-web instead of
 * /api/todo.
 */

/** Segments after /todo that can never be a secret token
 *  (admin_settings.RESERVED_TODO_WEB_SLUGS rejects them all), which is what
 *  makes the dev-server fallback below unambiguous. All are client-side page
 *  routes except 'todos', reserved server-side because it would shadow the
 *  /api/todo-web/{token} API mount. */
const PAGE_SLUGS = ['next', 'projects', 'waiting', 'someday', 'done', 'review', 'search', 'todos'];

function detectBase(): string | null {
  const injected = (window as { __CHATTY_TODO_BASE__?: string }).__CHATTY_TODO_BASE__;
  if (typeof injected === 'string' && injected) return injected;

  // Vite dev server serves index.html for any path without asking the
  // backend, so nothing is injected there. Recover the basename from the URL:
  // the segment after /todo is the token unless it is a page slug.
  const parts = window.location.pathname.split('/').filter(Boolean);
  if (parts[0] !== 'todo') return null;
  const second = parts[1];
  return second && !PAGE_SLUGS.includes(second) ? `/todo/${second}` : '/todo';
}

/** Router basename when serving the no-login todo app, else null. */
export const TODO_PUBLIC_BASE = detectBase();

export const isTodoPublicMode = TODO_PUBLIC_BASE !== null;

/** API prefix standing in for /api/todo — carries the token in public mode. */
export const TODO_API_BASE = TODO_PUBLIC_BASE
  ? `/api/todo-web${TODO_PUBLIC_BASE.slice('/todo'.length)}`
  : '/api/todo';

/**
 * Route path for a todo page. Inside the dashboard these live under /todos;
 * in public mode the router basename already points at the todo root, so
 * they hang off '/'.
 */
export function todoPath(sub = ''): string {
  return (isTodoPublicMode ? sub : `/todos${sub}`) || '/';
}
