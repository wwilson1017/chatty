/**
 * Chatty — usePlaybooks hook: single source of truth for an agent's playbooks.
 *
 * Instantiated once in AgentPage and shared by the chat surface (chips + slash
 * menu) and the Playbooks tab (CRUD), so chips refresh after any panel edit.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../../core/api/client';
import type { PlaybookSummary, PlaybookDetail, PlaybookWrite } from './types';

export function usePlaybooks(apiPrefix: string) {
  const [playbooks, setPlaybooks] = useState<PlaybookSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const seqRef = useRef(0);

  const reload = useCallback(async () => {
    const seq = ++seqRef.current;
    setLoadFailed(false);
    try {
      const data = await api<{ playbooks: PlaybookSummary[] }>(`${apiPrefix}/playbooks`);
      if (seq === seqRef.current) setPlaybooks(data.playbooks);
    } catch {
      if (seq === seqRef.current) setLoadFailed(true);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [apiPrefix]);

  useEffect(() => {
    seqRef.current++;
    setPlaybooks([]);
    setLoading(true);
    reload();
  }, [apiPrefix, reload]);

  const getDetail = useCallback(
    (slug: string) => api<PlaybookDetail>(`${apiPrefix}/playbooks/${slug}`),
    [apiPrefix],
  );

  const save = useCallback(async (slug: string, data: Partial<PlaybookWrite>) => {
    await api(`${apiPrefix}/playbooks/${slug}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
    await reload();
  }, [apiPrefix, reload]);

  const remove = useCallback(async (slug: string) => {
    const prev = playbooks;
    setPlaybooks(p => p.filter(pb => pb.slug !== slug));
    try {
      await api(`${apiPrefix}/playbooks/${slug}`, { method: 'DELETE' });
    } catch (err) {
      setPlaybooks(prev);
      throw err;
    }
  }, [apiPrefix, playbooks]);

  const toggleChip = useCallback(async (slug: string, chip: boolean) => {
    const prev = playbooks;
    setPlaybooks(p => p.map(pb => (pb.slug === slug ? { ...pb, chip } : pb)));
    try {
      await api(`${apiPrefix}/playbooks/${slug}`, {
        method: 'PUT',
        body: JSON.stringify({ chip }),
      });
    } catch (err) {
      setPlaybooks(prev);
      throw err;
    }
  }, [apiPrefix, playbooks]);

  const restore = useCallback(async (slug: string) => {
    await api(`${apiPrefix}/playbooks/${slug}/restore`, { method: 'POST' });
    await reload();
  }, [apiPrefix, reload]);

  return { playbooks, loading, loadFailed, reload, getDetail, save, remove, toggleChip, restore };
}
