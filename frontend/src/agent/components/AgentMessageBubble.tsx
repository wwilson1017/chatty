/**
 * Chatty — AgentMessageBubble.
 * Expandable tool pills with elapsed timer. No voice, no confirm flow.
 */

import { useState, useEffect } from 'react';
import type { ChatMessage, ToolCallInfo } from '../hooks/useAgentChat';

interface Props {
  message: ChatMessage;
}

const HUNG_THRESHOLD_SEC = 30;

function ToolPill({ tc }: { tc: ToolCallInfo }) {
  const [expanded, setExpanded] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (tc.status !== 'running') return;
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, [tc.status]);

  const elapsedRaw = tc.status === 'running'
    ? (Date.now() - tc.startedAt) / 1000
    : tc.elapsedMs ? tc.elapsedMs / 1000 : null;
  const elapsedSec = elapsedRaw !== null ? elapsedRaw.toFixed(1) : null;
  const isHung = tc.status === 'running' && elapsedRaw !== null && elapsedRaw >= HUNG_THRESHOLD_SEC;

  const icon = tc.status === 'running' ? '⏳' : tc.status === 'done' ? '✓' : '✗';
  const bg = tc.status === 'running'
    ? isHung
      ? 'bg-red-900/30 border-red-700/40'
      : 'bg-yellow-900/30 border-yellow-700/40'
    : tc.status === 'done'
    ? 'bg-green-900/20 border-green-700/30'
    : 'bg-red-900/20 border-red-700/30';

  const textColor = tc.status === 'running'
    ? isHung ? 'text-red-300' : 'text-yellow-300'
    : tc.status === 'done'
    ? 'text-green-300'
    : 'text-red-300';

  return (
    <div className={`rounded-lg border ${bg} text-xs mb-1`}>
      <button
        onClick={() => setExpanded(e => !e)}
        className={`flex items-center gap-2 px-3 py-1.5 w-full text-left ${textColor}`}
      >
        <span className={tc.status === 'running' ? 'animate-pulse' : ''}>{icon}</span>
        <span className="font-mono font-medium">{tc.tool}</span>
        {elapsedSec && (
          <span className={`ml-auto ${isHung ? 'text-red-400' : 'text-gray-500'}`}>{elapsedSec}s</span>
        )}
        <span className={`text-gray-500 transition ${expanded ? 'rotate-180' : ''}`}>▾</span>
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-1 border-t border-gray-700/50">
          {tc.args && Object.keys(tc.args).length > 0 && (
            <div>
              <p className="text-gray-500 uppercase text-[10px] tracking-wide mt-2 mb-1">Args</p>
              <pre className="text-gray-300 text-[11px] overflow-auto max-h-32 whitespace-pre-wrap">
                {JSON.stringify(tc.args, null, 2)}
              </pre>
            </div>
          )}
          {tc.status === 'running' && (
            <p className={`mt-2 text-[11px] ${isHung ? 'text-red-400' : 'text-gray-500'}`}>
              {isHung ? 'Tool may be stuck...' : 'Waiting for result...'}
            </p>
          )}
          {tc.result !== undefined && tc.status === 'done' && (
            <div>
              <p className="text-gray-500 uppercase text-[10px] tracking-wide mt-2 mb-1">Result</p>
              <pre className="text-gray-300 text-[11px] overflow-auto max-h-32 whitespace-pre-wrap">
                {typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AgentMessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[85%] ${isUser ? 'max-w-[70%]' : ''}`}>
        {/* Tool pills (assistant only) */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2">
            {message.toolCalls.map(tc => (
              <ToolPill key={tc.toolUseId} tc={tc} />
            ))}
          </div>
        )}

        {/* File attachments (user messages) */}
        {isUser && message.attachments && message.attachments.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {message.attachments.map((att, i) => (
              <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-500/30 border border-indigo-500/40 rounded text-xs text-indigo-200">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                {att.name}
              </span>
            ))}
          </div>
        )}

        {/* Message bubble */}
        {(message.content || (isUser)) && (
          <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-indigo-600 text-white rounded-br-sm'
              : 'bg-gray-800 text-gray-100 rounded-bl-sm'
          }`}>
            {message.content}
            {message.isStreaming && !message.content && (
              <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse rounded-sm" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
