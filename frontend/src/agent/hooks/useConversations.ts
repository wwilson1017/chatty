/**
 * Chatty — useConversations hook.
 * Adapted from CAKE OS — sender_email/sender_name removed (single-user).
 */

import { useState, useCallback, useRef, useEffect, type SetStateAction } from 'react';
import { api } from '../../core/api/client';
import { toast } from '../../shared/toast';
import type { ChatMessage } from './useAgentChat';
import { parseServerTimestamp } from '../utils/dateFormat';

export interface Conversation {
  id: string;
  title: string;
  title_edited_by_user: boolean;
  source?: string | null;
  pinned?: number;
  mode?: 'normal' | 'import';
  created_at: string;
  updated_at: string;
  message_count?: number;
  preview?: string;
}

export function useConversations(apiPrefix: string) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  // Mirrors activeId so async callbacks (e.g. deleteConversation) can read the
  // current value instead of a stale render closure. Written through
  // synchronously by setActiveId below — an effect-based sync would lag a
  // render, letting a DELETE that resolves between a newer select's commit and
  // the effect run compute wasActive from the stale id.
  const activeIdRef = useRef<string | null>(null);
  const setActiveId = useCallback((value: SetStateAction<string | null>) => {
    activeIdRef.current = typeof value === 'function' ? (value as (p: string | null) => string | null)(activeIdRef.current) : value;
    setActiveIdState(value);
  }, []);
  // Guards against out-of-order selectConversation responses: only the most
  // recent call may commit state or surface errors. Also bumped by New Chat
  // and agent switches, so a slow in-flight select can't land afterwards and
  // resurrect the old messages/activeId.
  const selectSeqRef = useRef(0);
  // Same pattern for loadConversations: a stale failure must not set
  // loadError over a newer success, nor a stale success overwrite a newer list.
  const loadSeqRef = useRef(0);
  useEffect(() => {
    selectSeqRef.current++;
    loadSeqRef.current++;
    setLoaded(false); setConversations([]); setActiveId(null); setLoadError(false);
  }, [apiPrefix, setActiveId]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<{ id: string; title: string; snippet: string; updated_at?: string }[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadConversations = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setLoadError(false);
    try {
      const data = await api<{ conversations: Conversation[] }>(`${apiPrefix}/conversations`);
      if (seq === loadSeqRef.current) setConversations(data.conversations);
    } catch { if (seq === loadSeqRef.current) setLoadError(true); }
    finally { if (seq === loadSeqRef.current) setLoaded(true); }
  }, [apiPrefix]);

  const selectConversation = useCallback(async (id: string): Promise<ChatMessage[] | null> => {
    const seq = ++selectSeqRef.current;
    setLoading(true);
    try {
      const data = await api<{
        id: string; title: string;
        messages: { id: string; role: string; content: string; seq: number; tool_calls?: string; model?: string; created_at?: string }[];
      }>(`${apiPrefix}/conversations/${id}`);
      // A newer selection started while this one was in flight — discard it
      // (null is the callers' existing do-nothing path).
      if (seq !== selectSeqRef.current) return null;
      setActiveId(id);
      return data.messages.map(m => {
        const parsedTimestamp = parseServerTimestamp(m.created_at);
        const msg: ChatMessage = {
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: parsedTimestamp ? parsedTimestamp.getTime() : 0,
          model: m.model,
        };
        if (m.tool_calls) {
          try {
            const parsed = JSON.parse(m.tool_calls);
            if (Array.isArray(parsed) && parsed.length > 0) {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              msg.toolCalls = parsed.map((tc: any) => ({
                tool: tc.tool || '',
                toolUseId: tc.toolUseId || tc.tool_use_id || '',
                args: tc.args,
                result: tc.result,
                status: 'done' as const,
                startedAt: 0,
                elapsedMs: tc.elapsedMs ?? tc.elapsed_ms,
                durationMs: tc.elapsedMs ?? tc.elapsed_ms ?? tc.durationMs,
              }));
            }
          } catch { /* ignore corrupted tool_calls */ }
        }
        return msg;
      });
    } catch {
      // null (not []) so callers can distinguish failure from an empty
      // conversation and skip switching the chat view. A stale failure stays
      // silent — it shouldn't toast over a newer selection.
      if (seq === selectSeqRef.current) toast.error('Failed to load conversation.');
      return null;
    } finally {
      if (seq === selectSeqRef.current) setLoading(false);
    }
  }, [apiPrefix, setActiveId]);

  const startNewChat = useCallback(() => {
    // Invalidate any in-flight select so a slow response can't land after
    // New Chat and resurrect the conversation the user just left.
    selectSeqRef.current++;
    setActiveId(null);
    setSearchQuery('');
    setSearchResults([]);
  }, [setActiveId]);

  const deleteConversation = useCallback(async (id: string): Promise<{ ok: boolean; wasActive: boolean }> => {
    try {
      await api(`${apiPrefix}/conversations/${id}`, { method: 'DELETE' });
      // Read the ref, not the closure: the user may have switched conversations
      // while the DELETE was in flight, and callers must not clear that view.
      const wasActive = activeIdRef.current === id;
      setConversations(prev => prev.filter(c => c.id !== id));
      setActiveId(prev => (prev === id ? null : prev));
      return { ok: true, wasActive };
    } catch { return { ok: false, wasActive: false }; }
  }, [apiPrefix, setActiveId]);

  const renameConversation = useCallback(async (id: string, title: string): Promise<boolean> => {
    try {
      const data = await api<{ title: string }>(`${apiPrefix}/conversations/${id}/title`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      setConversations(prev => prev.map(c =>
        c.id === id ? { ...c, title: data.title, title_edited_by_user: true } : c
      ));
      return true;
    } catch { return false; }
  }, [apiPrefix]);

  const updateConversationTitle = useCallback((id: string, title: string) => {
    setConversations(prev => prev.map(c => c.id === id ? { ...c, title } : c));
  }, []);

  const searchConversations = useCallback((query: string) => {
    setSearchQuery(query);
    if (searchTimer.current !== null) clearTimeout(searchTimer.current);
    if (!query.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const data = await api<{ results: { id: string; title: string; snippet: string; updated_at?: string }[] }>(
          `${apiPrefix}/conversations/search?q=${encodeURIComponent(query)}`
        );
        setSearchResults(data.results);
      } catch { setSearchResults([]); }
      finally { setIsSearching(false); }
    }, 300);
  }, [apiPrefix]);

  return {
    conversations,
    activeId,
    setActiveId,
    loading,
    loaded,
    loadError,
    searchQuery,
    searchResults,
    isSearching,
    loadConversations,
    selectConversation,
    startNewChat,
    deleteConversation,
    renameConversation,
    updateConversationTitle,
    searchConversations,
  };
}
