/**
 * Chatty — AgentMessageBubble.
 * Claude-style: flat assistant messages with markdown, branded user bubbles.
 * Expandable tool pills with elapsed timer. Confirmation cards for write ops.
 */

import { useState, useEffect } from 'react';
import type { ChatMessage, ToolCallInfo, PendingConfirmation } from '../hooks/useAgentChat';
import MarkdownContent from './MarkdownContent';

interface Props {
  message: ChatMessage;
  onApprove?: (msgId: string) => void;
  onDeny?: (msgId: string) => void;
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

function ConfirmationCard({ confirm, onApprove, onDeny }: {
  confirm: PendingConfirmation;
  onApprove?: () => void;
  onDeny?: () => void;
}) {
  const borderColor = confirm.status === 'approved'
    ? 'border-green-700/40 bg-green-900/20'
    : confirm.status === 'denied'
    ? 'border-red-700/40 bg-red-900/20'
    : 'border-amber-700/40 bg-amber-900/20';

  const dotColor = confirm.status === 'approved'
    ? 'bg-green-500'
    : confirm.status === 'denied'
    ? 'bg-red-500'
    : 'bg-amber-400 animate-pulse';

  const statusLabel = confirm.status === 'approved'
    ? 'Approved'
    : confirm.status === 'denied'
    ? 'Denied'
    : 'Awaiting approval';

  return (
    <div className={`mt-3 rounded-xl border p-3 ${borderColor}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span className="text-xs font-semibold text-gray-200">{statusLabel}</span>
      </div>
      <p className="text-xs text-gray-400 mb-2">
        {confirm.description || `Execute ${confirm.tool}`}
      </p>
      {confirm.status === 'pending' && (
        <div className="flex gap-2">
          <button
            onClick={onApprove}
            className="px-3 py-1 text-xs font-medium rounded-lg bg-green-700/50 text-green-200 hover:bg-green-700/70 transition"
          >
            Approve
          </button>
          <button
            onClick={onDeny}
            className="px-3 py-1 text-xs font-medium rounded-lg bg-red-700/50 text-red-200 hover:bg-red-700/70 transition"
          >
            Deny
          </button>
        </div>
      )}
    </div>
  );
}

function BouncingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

export function AgentMessageBubble({ message, onApprove, onDeny }: Props) {
  const isUser = message.role === 'user';

  // ── User message: branded right-aligned bubble ──
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] sm:max-w-[75%]">
          {message.attachments && message.attachments.length > 0 && (
            <div className="mb-1.5 flex flex-wrap gap-1 justify-end">
              {message.attachments.map((att, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-500/30 border border-indigo-500/40 rounded text-xs text-indigo-200">
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                  {att.name}
                </span>
              ))}
            </div>
          )}
          <div className="bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // ── Assistant message: flat, no bubble, markdown rendered ──
  return (
    <div className="w-full">
      {/* Tool pills */}
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="mb-2">
          {message.toolCalls.map(tc => (
            <ToolPill key={tc.toolUseId} tc={tc} />
          ))}
        </div>
      )}

      {/* Message content */}
      {message.content ? (
        <MarkdownContent content={message.content} />
      ) : message.isStreaming ? (
        <BouncingDots />
      ) : null}

      {/* Confirmation card */}
      {message.pendingConfirm && (
        <ConfirmationCard
          confirm={message.pendingConfirm}
          onApprove={() => onApprove?.(message.id)}
          onDeny={() => onDeny?.(message.id)}
        />
      )}
    </div>
  );
}
