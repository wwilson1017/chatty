/**
 * Chatty — AgentMessageBubble.
 * Expandable tool pills with elapsed timer. No voice, no confirm flow.
 */

import { useState, useEffect } from 'react';
import type { ChatMessage, ToolCallInfo } from '../hooks/useAgentChat';

interface Props {
  message: ChatMessage;
}

function ToolPill({ tc }: { tc: ToolCallInfo }) {
  const [expanded, setExpanded] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (tc.status !== 'running') return;
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, [tc.status]);

  const elapsedSec = tc.status === 'running'
    ? ((Date.now() - tc.startedAt) / 1000).toFixed(1)
    : tc.elapsedMs ? (tc.elapsedMs / 1000).toFixed(1) : null;

  const icon = tc.status === 'running' ? '⏳' : tc.status === 'done' ? '✓' : '✗';
  const bg = tc.status === 'running'
    ? 'bg-yellow-900/30 border-yellow-700/40'
    : tc.status === 'done'
    ? 'bg-green-900/20 border-green-700/30'
    : 'bg-red-900/20 border-red-700/30';

  const textColor = tc.status === 'running'
    ? 'text-yellow-300'
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
        {elapsedSec && <span className="text-gray-500 ml-auto">{elapsedSec}s</span>}
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
