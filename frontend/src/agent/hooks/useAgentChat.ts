/**
 * Chatty — useAgentChat hook.
 *
 * Streams chat responses via SSE. Handles text, tool_start, tool_args,
 * tool_end, confirm, plan_ready, usage, report, title_update, done, error events.
 *
 * Supports 3-tier tool mode (read-only / normal / power) with confirmation flow,
 * plan mode, training/improve modes, and context usage tracking.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { getToken } from '../../core/auth/AuthContext';

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
  const abortRef = useRef<AbortController | null>(null);
  const savedToolModeRef = useRef<ToolMode>('normal');
  const savedToolModeForPlanRef = useRef<ToolMode>('normal');
  const trainingKickoffRef = useRef(false);
  const trainingKickoffMessageRef = useRef('Hey there!');

  const sendMessage = useCallback(async (text: string, files?: File[], approvedTool?: {
    tool: string;
    args: Record<string, unknown>;
    toolUseId: string;
    result: unknown;
  }, overrides?: { tool_mode?: string; plan_mode?: boolean; hidden?: boolean }) => {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
      attachments: files?.map(f => ({ name: f.name, size: f.size })),
      hidden: overrides?.hidden,
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
                      { tool: event.tool, toolUseId: event.tool_use_id || crypto.randomUUID(), status: 'running', startedAt: Date.now() },
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
                      tc.toolUseId === event.tool_use_id
                        ? { ...tc, args: event.args, description: event.description }
                        : tc
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
                        ? { ...tc, status: 'done' as const, result: event.result, elapsedMs: event.elapsed_ms, durationMs: event.duration_ms }
                        : tc;
                    }),
                  };
                }
                return updated;
              });
            } else if (event.type === 'confirm' && event.tool) {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    pendingConfirm: {
                      tool: event.tool,
                      args: event.args || {},
                      toolUseId: event.tool_use_id || '',
                      status: 'pending',
                      description: event.description,
                    },
                  };
                }
                return updated;
              });
            } else if (event.type === 'plan_ready' && event.plan) {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    pendingPlan: {
                      plan: event.plan,
                      status: 'pending',
                    },
                  };
                }
                return updated;
              });
            } else if (event.type === 'usage' && event.input_tokens != null && event.context_window != null) {
              setContextUsage({
                inputTokens: event.input_tokens,
                contextWindow: event.context_window,
              });
            } else if (event.type === 'report' && event.report) {
              setMessages(prev => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    reports: [...(last.reports || []), event.report],
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
                    content: last.content + `\n\n**Error:** ${event.error}`,
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
  }, [messages, trainingMode, trainingType, toolMode, planMode, conversationId, apiPrefix, options]);

  // ── Approve a pending confirmation ──
  const approveAction = useCallback(async (msgId: string) => {
    const msg = messages.find(m => m.id === msgId);
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
  }, [messages, apiPrefix, sendMessage]);

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
      setTrainingModeState(true);
    } else {
      setToolMode(savedToolModeRef.current);
      setMessages([]);
      setConversationId(null);
      setTrainingType('topic');
      setTrainingModeState(false);
    }
  }, [toolMode]);

  useEffect(() => {
    if (trainingMode && trainingKickoffRef.current && !isStreaming) {
      trainingKickoffRef.current = false;
      sendMessage(trainingKickoffMessageRef.current, undefined, undefined, { hidden: true });
    }
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
    const msg = messages.find(m => m.id === messageId);
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
  }, [messages, sendMessage]);

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

  const loadMessages = useCallback((msgs: ChatMessage[], id: string) => {
    setMessages(msgs);
    setConversationId(id);
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
