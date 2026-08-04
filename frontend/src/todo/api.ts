/**
 * Chatty — todo API client.
 *
 * Identical to the shared client except that it retargets /api/todo at the
 * no-login /api/todo-web mount when the app is running in todo-only public
 * mode. Every todo page calls this instead of api() so neither mode needs
 * its own copy of the pages.
 */

import { api } from '../core/api/client';
import { TODO_API_BASE } from './publicMode';

const DASHBOARD_PREFIX = '/api/todo/';

export function todoApi<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const target = path.startsWith(DASHBOARD_PREFIX)
    ? `${TODO_API_BASE}/${path.slice(DASHBOARD_PREFIX.length)}`
    : path;
  return api<T>(target, options);
}
