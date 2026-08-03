import { api } from '../core/api/client';
import { toast } from '../shared/toast';
import type { TodoProjectStatus } from '../core/types';

/** PUT a project status change; toasts on failure. Returns success. */
export async function updateProjectStatus(projectId: number, status: TodoProjectStatus): Promise<boolean> {
  try {
    await api(`/api/todo/projects/${projectId}`, { method: 'PUT', body: JSON.stringify({ status }) });
    return true;
  } catch {
    toast.error('Failed to update project.');
    return false;
  }
}
