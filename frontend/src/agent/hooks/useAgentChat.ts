/**
 * Chatty — useAgentChat hook.
 *
 * Streams chat responses via SSE. Handles text, tool_start, tool_args,
 * tool_end, confirm, plan_ready, usage, report, title_update, done, error events.
 *
 * Supports 3-tier tool mode (read-only / normal / power) with confirmation flow,
 * plan mode, training/improve modes, and context usage tracking.
 *
 * Performance: rAF-batched text deltas, tail-update pattern for message state,
 * messagesRef for stable closures.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { getToken } from '../../core/auth/tokenUtils';

function uuid(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export type ToolMode = 'read-only' | 'normal' | 'power';
export type TrainingType = 'topic' | 'improve' | null;

export interface ToolCallInfo {
  tool: string;
  toolUseId: string;
  status: 'running' | 'done' | 'error';
  args?: Record<string, unknown>;
  description?: string;
  result?: unknown;
  elapsedMs?: number;
  durationMs?: number;
  startedAt: number;
}

export interface PendingConfirmation {
  tool: string;
  args: Record<string, unknown>;
  toolUseId: string;
  status: 'pending' | 'approved' | 'denied';
  description?: string;
}

export interface PendingPlan {
  plan: string;
  status: 'pending' | 'approved' | 'iterating';
}

export interface InlineReport {
  id: string;
  title: string;
  subtitle?: string;
  sections: unknown[];
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
  isStreaming?: boolean;
  attachments?: { name: string; size: number }[];
  hidden?: boolean;
  pendingConfirm?: PendingConfirmation;
  pendingPlan?: PendingPlan;
  reports?: InlineReport[];
}

export interface ContextUsage {
  inputTokens: number;
  contextWindow: number;
}

interface Options {
  onTitleUpdate?: (convId: string, title: string) => void;
  onImportComplete?: (newConversationId: string) => void;
}

export function useAgentChat(apiPrefix: string, options?: Options) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [trainingMode, setTrainingModeState] = useState(false);
  const [trainingType, setTrainingType] = useState<TrainingType>('topic');
  const [planMode, setPlanModeState] = useState(false);
  const [toolMode, setToolMode] = useState<ToolMode>('normal');
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [greetingPending, setGreetingPending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const streamInIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => {
    if (streamInIntervalRef.current) clearInterval(streamInIntervalRef.current);
  }, []);
  const savedToolModeRef = useRef<ToolMode>('normal');
  const savedToolModeForPlanRef = useRef<ToolMode>('normal');
  const trainingKickoffRef = useRef(false);
  const trainingKickoffMessageRef = useRef('Hey there!');

  // Stable ref for messages — avoids stale closures in sendMessage
  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  // ── rAF text batching ─────────────────────────────────────────────
  const pendingTextRef = useRef('');
  const rafIdRef = useRef<number | null>(null);

  const flushPendingText = useCallback(() => {
    rafIdRef.current = null;
    const chunk = pendingTextRef.current;
    if (!chunk) return;
    pendingTextRef.current = '';
    setMessages(prev => {
      if (!prev.length) return prev;
      const last = prev[prev.length - 1];
      if (last.role !== 'assistant') return prev;
      return [...prev.slice(0, -1), { ...last, content: last.content + chunk }];
    });
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafIdRef.current !== null) return;
    rafIdRef.current = requestAnimationFrame(flushPendingText);
  }, [flushPendingText]);

  // ── Tail-update helper ────────────────────────────────────────────
  const updateLastAssistant = useCallback(
    (updater: (msg: ChatMessage) => ChatMessage) => {
      setMessages(prev => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (last.role !== 'assistant') return prev;
        return [...prev.slice(0, -1), updater(last)];
      });
    },
    []
  );

  const sendMessage = useCallback(async (text: string, files?: File[], approvedTool?: {
    tool: string;
    args: Record<string, unknown>;
    toolUseId: string;
    result: unknown;
  }, overrides?: { tool_mode?: string; plan_mode?: boolean; hidden?: boolean }) => {
    const userMsg: ChatMessage = {
      id: uuid(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
      attachments: files?.map(f => ({ name: f.name, size: f.size })),
      hidden: overrides?.hidden,
    };
    const assistantMsg: ChatMessage = {
      id: uuid(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      toolCalls: [],
      isStreaming: true,
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    // Use messagesRef for fresh snapshot (avoids stale closure)
    const history = [...messagesRef.current, userMsg].map(m => ({ role: m.role, content: m.content }));

    // Effective tool mode: training forces power
    const effectiveMode = overrides?.tool_mode ?? (trainingMode ? 'power' : toolMode);

    abortRef.current = new AbortController();

    try {
      const token = getToken();
      const hasFiles = files && files.length > 0;

      const payload: Record<string, unknown> = {
        messages: history,
        training_mode: trainingMode,
        training_type: trainingType,
        conversation_id: conversationId,
        tool_mode: effectiveMode,
        plan_mode: overrides?.plan_mode ?? planMode,
      };
      if (approvedTool) payload.approved_tool = approvedTool;

      let res: Response;
      if (hasFiles) {
        const formData = new FormData();
        formData.append('payload', JSON.stringify(payload));
        for (const f of files) {
          formData.append('files', f);
        }
        res = await fetch(`${apiPrefix}/chat/upload`, {
          method: 'POST',
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: formData,
          signal: abortRef.current.signal,
        });
      } else {
        res = await fetch(`${apiPrefix}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
          signal: abortRef.current.signal,
        });
      }

      if (res.status === 401) {
        sessionStorage.removeItem('chatty_token');
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
              // rAF batching — accumulate text, flush once per frame
              pendingTextRef.current += event.text;
              scheduleFlush();
            } else if (event.type === 'tool_start') {
              // Flush pending text before tool events
              flushPendingText();
              updateLastAssistant(last => ({
                ...last,
                toolCalls: [
                  ...(last.toolCalls || []),
                  { tool: event.tool, toolUseId: event.tool_use_id || uuid(), status: 'running', startedAt: Date.now() },
                ],
              }));
            } else if (event.type === 'tool_args' && event.tool_use_id) {
              updateLastAssistant(last => ({
                ...last,
                toolCalls: (last.toolCalls || []).map(tc =>
                  tc.toolUseId === event.tool_use_id
                    ? { ...tc, args: event.args, description: event.description }
                    : tc
                ),
              }));
            } else if (event.type === 'tool_end') {
              updateLastAssistant(last => ({
                ...last,
                toolCalls: (last.toolCalls || []).map(tc => {
                  const match = event.tool_use_id
                    ? tc.toolUseId === event.tool_use_id
                    : tc.tool === event.tool && tc.status === 'running';
                  return match
                    ? { ...tc, status: 'done' as const, result: event.result, elapsedMs: event.elapsed_ms, durationMs: event.duration_ms }
                    : tc;
                }),
              }));
              if (event.tool === 'finalize_import' && event.result) {
                try {
                  const result = typeof event.result === 'string' ? JSON.parse(event.result) : event.result;
                  if (result.new_conversation_id && options?.onImportComplete) {
                    setTimeout(() => options.onImportComplete!(result.new_conversation_id), 2000);
                  }
                } catch { /* ignore parse errors */ }
              }
            } else if (event.type === 'confirm' && event.tool) {
              flushPendingText();
              updateLastAssistant(last => ({
                ...last,
                pendingConfirm: {
                  tool: event.tool,
                  args: event.args || {},
                  toolUseId: event.tool_use_id || '',
                  status: 'pending',
                  description: event.description,
                },
              }));
            } else if (event.type === 'plan_ready' && (event.plan_text || event.plan)) {
              flushPendingText();
              updateLastAssistant(last => ({
                ...last,
                pendingPlan: {
                  plan: event.plan_text || event.plan,
                  status: 'pending',
                },
              }));
            } else if (event.type === 'usage' && event.input_tokens != null && event.context_window != null) {
              setContextUsage({
                inputTokens: event.input_tokens,
                contextWindow: event.context_window,
              });
            } else if (event.type === 'report' && event.report) {
              updateLastAssistant(last => ({
                ...last,
                reports: [...(last.reports || []), event.report],
              }));
            } else if (event.type === 'conversation_id' && event.id) {
              setConversationId(event.id);
            } else if (event.type === 'title_update' && event.title && event.conversation_id) {
              options?.onTitleUpdate?.(event.conversation_id, event.title);
            } else if (event.type === 'error') {
              flushPendingText();
              updateLastAssistant(last => ({
                ...last,
                content: last.content + `\n\n**Error:** ${event.error}`,
              }));
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      updateLastAssistant(last => ({
        ...last,
        content: last.content || 'Failed to get a response. Please try again.',
      }));
    } finally {
      // Flush any remaining text
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      const remaining = pendingTextRef.current;
      if (remaining) {
        pendingTextRef.current = '';
        setMessages(prev => {
          if (!prev.length) return prev;
          const last = prev[prev.length - 1];
          if (last.role !== 'assistant') return prev;
          return [...prev.slice(0, -1), { ...last, content: last.content + remaining }];
        });
      }

      setIsStreaming(false);
      setMessages(prev => prev.map(m => m.isStreaming ? { ...m, isStreaming: false } : m));
      abortRef.current = null;
    }
  }, [trainingMode, trainingType, toolMode, planMode, conversationId, apiPrefix, options, scheduleFlush, flushPendingText, updateLastAssistant]);

  // ── Approve a pending confirmation ──
  const approveAction = useCallback(async (msgId: string) => {
    const msg = messagesRef.current.find(m => m.id === msgId);
    if (!msg?.pendingConfirm || msg.pendingConfirm.status !== 'pending') return;

    const { tool, args, toolUseId } = msg.pendingConfirm;

    setMessages(prev => prev.map(m =>
      m.id === msgId && m.pendingConfirm
        ? { ...m, pendingConfirm: { ...m.pendingConfirm, status: 'approved' as const } }
        : m
    ));

    try {
      const token = getToken();
      const res = await fetch(`${apiPrefix}/tool/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tool, args }),
      });

      if (!res.ok) throw new Error(`Execute failed: ${res.status}`);
      const result = await res.json();

      sendMessage(`[Approved] ${tool}`, undefined, { tool, args, toolUseId, result });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : 'Unknown error';
      sendMessage(`[Action failed] ${tool}: ${errMsg}`, undefined, {
        tool, args, toolUseId, result: { error: errMsg },
      });
    }
  }, [apiPrefix, sendMessage]);

  // ── Deny a pending confirmation ──
  const denyAction = useCallback((msgId: string) => {
    setMessages(prev => prev.map(m =>
      m.id === msgId && m.pendingConfirm
        ? { ...m, pendingConfirm: { ...m.pendingConfirm, status: 'denied' as const } }
        : m
    ));
  }, []);

  // ── Training mode ──
  const setTrainingMode = useCallback((on: boolean, type?: TrainingType, kickoff?: string) => {
    if (on) {
      savedToolModeRef.current = toolMode;
      setMessages([]);
      setConversationId(null);
      setTrainingType(type || 'topic');
      trainingKickoffMessageRef.current = kickoff || 'Hey there!';
      trainingKickoffRef.current = true;
      setGreetingPending(true);
      setTrainingModeState(true);
    } else {
      setToolMode(savedToolModeRef.current);
      setMessages([]);
      setConversationId(null);
      setTrainingType('topic');
      setGreetingPending(false);
      setTrainingModeState(false);
    }
  }, [toolMode]);

  useEffect(() => {
    if (!trainingMode || !trainingKickoffRef.current || isStreaming) return;
    const msg = trainingKickoffMessageRef.current;
    trainingKickoffRef.current = false;
    const timer = setTimeout(() => {
      setGreetingPending(false);
      sendMessage(msg, undefined, undefined, { hidden: true });
    }, 50);
    return () => clearTimeout(timer);
  }, [trainingMode, isStreaming, sendMessage]);

  // ── Plan mode ──
  const setPlanMode = useCallback((on: boolean) => {
    if (on) {
      savedToolModeForPlanRef.current = toolMode;
      setMessages([]);
      setConversationId(null);
      setPlanModeState(true);
    } else {
      setToolMode(savedToolModeForPlanRef.current);
      setPlanModeState(false);
    }
  }, [toolMode]);

  const approvePlan = useCallback((messageId: string) => {
    const msg = messagesRef.current.find(m => m.id === messageId);
    if (!msg?.pendingPlan || msg.pendingPlan.status !== 'pending') return;

    setMessages(prev =>
      prev.map(m =>
        m.id === messageId
          ? { ...m, pendingPlan: { ...m.pendingPlan!, status: 'approved' as const } }
          : m
      )
    );

    // Exit plan mode and execute with power mode override
    setPlanModeState(false);
    sendMessage('[Plan approved] Execute the plan now.', undefined, undefined, {
      tool_mode: 'power',
      plan_mode: false,
    });
  }, [sendMessage]);

  const iteratePlan = useCallback((messageId: string) => {
    setMessages(prev =>
      prev.map(m =>
        m.id === messageId
          ? { ...m, pendingPlan: { ...m.pendingPlan!, status: 'iterating' as const } }
          : m
      )
    );
    // Plan mode stays active -- user types feedback
  }, []);

  const stop = useCallback(() => { abortRef.current?.abort(); }, []);

  const clear = useCallback(() => {
    setMessages([]);
    setConversationId(null);
    setContextUsage(null);
  }, []);

  const loadMessages = useCallback((msgs: ChatMessage[], id: string, streamIn?: boolean) => {
    if (streamInIntervalRef.current) {
      clearInterval(streamInIntervalRef.current);
      streamInIntervalRef.current = null;
    }

    if (!streamIn || !msgs.length || msgs[msgs.length - 1].role !== 'assistant') {
      setMessages(msgs);
      setConversationId(id);
      return;
    }

    const lastMsg = msgs[msgs.length - 1];
    const fullText = lastMsg.content;
    const preceding = msgs.slice(0, -1);

    setConversationId(id);
    setIsStreaming(true);
    setMessages([...preceding, { ...lastMsg, content: '', isStreaming: true }]);

    let i = 0;
    streamInIntervalRef.current = setInterval(() => {
      const chunkEnd = Math.min(i + 3, fullText.length);
      const soFar = fullText.slice(0, chunkEnd);
      i = chunkEnd;
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last?.role !== 'assistant') return prev;
        return [...prev.slice(0, -1), { ...last, content: soFar }];
      });
      if (i >= fullText.length) {
        if (streamInIntervalRef.current) clearInterval(streamInIntervalRef.current);
        streamInIntervalRef.current = null;
        setIsStreaming(false);
        setMessages(prev => prev.map(m => m.isStreaming ? { ...m, isStreaming: false } : m));
      }
    }, 12);
  }, []);

  return {
    messages,
    isStreaming,
    conversationId,
    contextUsage,
    trainingMode,
    trainingType,
    toolMode,
    setToolMode,
    setTrainingMode,
    greetingPending,
    setGreetingPending,
    planMode,
    setPlanMode,
    approvePlan,
    iteratePlan,
    sendMessage,
    approveAction,
    denyAction,
    stop,
    clear,
    loadMessages,
  };
}
