import { useCallback, useEffect, useState } from 'react';
import { api } from '../../core/api/client';

export interface RuntimeStatus {
  runtime: 'chatty' | 'hermes';
  dev_switch: boolean;
  hermes: {
    connected: boolean;
    healthy?: boolean;
    model?: string | null;
    approval_request_id?: boolean;
    error?: string | null;
  };
}

export function useRuntimeStatus(agentId: string | undefined) {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const refresh = useCallback(() => {
    if (!agentId) return;
    api<RuntimeStatus>(`/api/agents/${agentId}/runtime/status`).then(setStatus).catch(() => {});
  }, [agentId]);
  useEffect(() => { refresh(); }, [refresh]);
  return { status, refresh };
}

