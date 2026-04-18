/**
 * Chatty — useConversations hook.
 * Adapted from CAKE OS — sender_email/sender_name removed (single-user).
 */

import { useState, useCallback, useRef } from 'react';
import { api } from '../../core/api/client';
import type { ChatMessage, ToolCallInfo } from './useAgentChat';

export interface Conversation {
  id: string;
  title: string;
  title_edited_by_user: boolean;
  created_at: string;
  updated_at: string;
  message_count?: number;
  preview?: string;
}

export function useConversations(apiPrefix: string) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<{ id: string; title: string; snippet: string }[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      const data = await api<{ conversations: Conversation[] }>(`${apiPrefix}/conversations`);
      setConversations(data.conversations);
    } catch { /* silent */ }
  }, [apiPrefix]);

  const selectConversation = useCallback(async (id: string): Promise<ChatMessage[]> => {
    setLoading(true);
    try {
      const data = await api<{
        id: string; title: string;
        messages: { id: string; role: string; content: string; seq: number; tool_calls?: string }[];
      }>(`${apiPrefix}/conversations/${id}`);
      setActiveId(id);
      return data.messages.map(m => {
        const msg: ChatMessage = {
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: Date.now(),
        };
        if (m.tool_calls) {
          try {
            const parsed = JSON.parse(m.tool_calls) as ToolCallInfo[];
            if (Array.isArray(parsed) && parsed.length > 0) {
              msg.toolCalls = parsed.map(tc => ({
                ...tc,
                status: 'done' as const,
                startedAt: 0,
                durationMs: tc.elapsedMs ?? tc.durationMs,
              }));
            }
          } catch { /* ignore corrupted tool_calls */ }
        }
        return msg;
      });
    } catch {
      return [];
    } finally {
      setLoading(false);
    }
  }, [apiPrefix]);

  const startNewChat = useCallback(() => {
    setActiveId(null);
    setSearchQuery('');
    setSearchResults([]);
  }, []);

  const deleteConversation = useCallback(async (id: string) => {
    try {
      await api(`${apiPrefix}/conversations/${id}`, { method: 'DELETE' });
      setConversations(prev => prev.filter(c => c.id !== id));
      if (activeId === id) setActiveId(null);
      return true;
    } catch { return false; }
  }, [activeId, apiPrefix]);

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
        const data = await api<{ results: { id: string; title: string; snippet: string }[] }>(
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
