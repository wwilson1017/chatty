/**
 * Chatty — useAgentChat hook.
 *
 * Streams chat responses via SSE. Handles text, tool_start, tool_args,
 * tool_end, title_update, done, error events.
 *
 * Adapted from CAKE OS — voice tab, confirm flow, and DIMM/report events removed.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { getToken } from '../../core/auth/AuthContext';

export interface ToolCallInfo {
  tool: string;
  toolUseId: string;
  status: 'running' | 'done' | 'error';
  args?: Record<string, unknown>;
  result?: unknown;
  elapsedMs?: number;
  startedAt: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
  isStreaming?: boolean;
}

interface Options {
  onTitleUpdate?: (convId: string, title: string) => void;
}

export function useAgentChat(apiPrefix: string, options?: Options) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [trainingMode, setTrainingModeState] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const trainingKickoffRef = useRef(false);

  const sendMessage = useCallback(async (text: string) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      toolCalls: [],
      isStreaming: true,
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }));

    abortRef.current = new AbortController();

    try {
      const token = getToken();
      const res = await fetch(`${apiPrefix}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          messages: history,
          training_mode: trainingMode,
          conversation_id: conversationId,
        }),
        signal: abortRef.current.signal,
      });

      if (res.status === 401) {
        localStorage.removeItem('chatty_token');
        window.location.href = '/login';
        return;
      }
      if (!res.ok) throw new Error(`API error ${res.status}`);

      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);

            if (event.type === 'text' && event.text) {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: last.content + event.text };
                }
                return updated;
              });
            } else if (event.type === 'tool_start') {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    toolCalls: [
                      ...(last.toolCalls || []),
                      { tool: event.tool, toolUseId: event.tool_use_id, status: 'running', startedAt: Date.now() },
                    ],
                  };
                }
                return updated;
              });
            } else if (event.type === 'tool_args' && event.tool_use_id) {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    toolCalls: (last.toolCalls || []).map(tc =>
                      tc.toolUseId === event.tool_use_id ? { ...tc, args: event.args } : tc
                    ),
                  };
                }
                return updated;
              });
            } else if (event.type === 'tool_end') {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    toolCalls: (last.toolCalls || []).map(tc => {
                      const match = event.tool_use_id
                        ? tc.toolUseId === event.tool_use_id
                        : tc.tool === event.tool && tc.status === 'running';
                      return match
                        ? { ...tc, status: 'done' as const, result: event.result, elapsedMs: event.elapsed_ms }
                        : tc;
                    }),
                  };
                }
                return updated;
              });
            } else if (event.type === 'conversation_id' && event.id) {
              setConversationId(event.id);
            } else if (event.type === 'title_update' && event.title && event.conversation_id) {
              options?.onTitleUpdate?.(event.conversation_id, event.title);
            } else if (event.type === 'error') {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + `\n\n⚠️ ${event.error}`,
                  };
                }
                return updated;
              });
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant' && !last.content) {
          updated[updated.length - 1] = { ...last, content: 'Failed to get a response. Please try again.' };
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
      setMessages(prev => prev.map(m => m.isStreaming ? { ...m, isStreaming: false } : m));
      abortRef.current = null;
    }
  }, [messages, trainingMode, conversationId, apiPrefix, options]);

  const setTrainingMode = useCallback((on: boolean) => {
    if (on) {
      setMessages([]);
      setConversationId(null);
      trainingKickoffRef.current = true;
      setTrainingModeState(true);
    } else {
      setMessages([]);
      setConversationId(null);
      setTrainingModeState(false);
    }
  }, []);

  useEffect(() => {
    if (trainingMode && trainingKickoffRef.current && !isStreaming) {
      trainingKickoffRef.current = false;
      sendMessage('Start onboarding.');
    }
  }, [trainingMode, isStreaming, sendMessage]);

  const stop = useCallback(() => { abortRef.current?.abort(); }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setConversationId(null);
  }, []);

  const loadMessages = useCallback((msgs: ChatMessage[], id: string) => {
    setMessages(msgs);
    setConversationId(id);
  }, []);

  return {
    messages,
    isStreaming,
    conversationId,
    trainingMode,
    setTrainingMode,
    sendMessage,
    stop,
    clear,
    loadMessages,
  };
}
