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
  showToolCalls?: boolean;
}

const HUNG_THRESHOLD_SEC = 30;

function ToolCallBox({ toolCalls }: { toolCalls: ToolCallInfo[] }) {
  const [expanded, setExpanded] = useState(false);
  const [, setTick] = useState(0);

  // Tick for running timers
  const anyRunning = toolCalls.some(tc => tc.status === 'running');
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, [anyRunning]);

  // Show the latest tool call in the summary line
  const latest = toolCalls[toolCalls.length - 1];
  const doneCount = toolCalls.filter(tc => tc.status === 'done').length;
  const failedCount = toolCalls.filter(tc => tc.status === 'error').length;
  const runningCount = toolCalls.filter(tc => tc.status === 'running').length;

  const latestElapsed = latest.status === 'running'
    ? ((Date.now() - latest.startedAt) / 1000).toFixed(1)
    : latest.elapsedMs ? (latest.elapsedMs / 1000).toFixed(1) : null;
  const isHung = latest.status === 'running' && latestElapsed !== null && parseFloat(latestElapsed) >= HUNG_THRESHOLD_SEC;

  const summaryIcon = runningCount > 0 ? '⏳' : failedCount > 0 ? '✗' : '✓';
  const summaryBg = runningCount > 0
    ? isHung ? 'bg-red-900/30 border-red-700/40' : 'bg-yellow-900/30 border-yellow-700/40'
    : failedCount > 0 ? 'bg-red-900/20 border-red-700/30' : 'bg-green-900/20 border-green-700/30';
  const summaryColor = runningCount > 0
    ? isHung ? 'text-red-300' : 'text-yellow-300'
    : failedCount > 0 ? 'text-red-300' : 'text-green-300';

  return (
    <div className={`rounded-lg border ${summaryBg} text-xs`}>
      {/* Summary line — shows latest tool + counts */}
      <button
        onClick={() => setExpanded(e => !e)}
        className={`flex items-center gap-2 px-3 py-1.5 w-full text-left ${summaryColor}`}
      >
        <span className={runningCount > 0 ? 'animate-pulse' : ''}>{summaryIcon}</span>
        <span className="font-mono font-medium">{latest.tool}</span>
        {toolCalls.length > 1 && (
          <span className="text-gray-500">
            {runningCount > 0
              ? `(${doneCount + failedCount}/${toolCalls.length})`
              : `(${toolCalls.length} tools)`}
          </span>
        )}
        {latestElapsed && (
          <span className={`ml-auto ${isHung ? 'text-red-400' : 'text-gray-500'}`}>{latestElapsed}s</span>
        )}
        <span className={`text-gray-500 transition ${expanded ? 'rotate-180' : ''}`}>▾</span>
      </button>

      {/* Expanded: all tool calls with details */}
      {expanded && (
        <div className="border-t border-gray-700/50 px-3 pb-2 space-y-3 max-h-80 overflow-y-auto">
          {toolCalls.map((tc, i) => {
            const tcIcon = tc.status === 'running' ? '⏳' : tc.status === 'done' ? '✓' : '✗';
            const tcColor = tc.status === 'running' ? 'text-yellow-300' : tc.status === 'done' ? 'text-green-300' : 'text-red-300';
            const tcElapsed = tc.status === 'running'
              ? ((Date.now() - tc.startedAt) / 1000).toFixed(1)
              : tc.elapsedMs ? (tc.elapsedMs / 1000).toFixed(1) : null;

            return (
              <div key={tc.toolUseId} className="pt-2">
                <div className={`flex items-center gap-2 ${tcColor}`}>
                  <span className={tc.status === 'running' ? 'animate-pulse' : ''}>{tcIcon}</span>
                  <span className="font-mono font-medium">{tc.tool}</span>
                  {tcElapsed && <span className="ml-auto text-gray-500">{tcElapsed}s</span>}
                </div>
                {tc.args && Object.keys(tc.args).length > 0 && (
                  <div>
                    <p className="text-gray-500 uppercase text-[10px] tracking-wide mt-1.5 mb-0.5">Args</p>
                    <pre className="text-gray-300 text-[11px] overflow-auto max-h-24 whitespace-pre-wrap">
                      {JSON.stringify(tc.args, null, 2)}
                    </pre>
                  </div>
                )}
                {tc.result !== undefined && tc.status === 'done' && (
                  <div>
                    <p className="text-gray-500 uppercase text-[10px] tracking-wide mt-1.5 mb-0.5">Result</p>
                    <pre className="text-gray-300 text-[11px] overflow-auto max-h-24 whitespace-pre-wrap">
                      {typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)}
                    </pre>
                  </div>
                )}
                {tc.status === 'running' && (
                  <p className="mt-1 text-[11px] text-gray-500">Waiting for result...</p>
                )}
                {i < toolCalls.length - 1 && <div className="border-b border-gray-700/30 mt-2" />}
              </div>
            );
          })}
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

export function AgentMessageBubble({ message, onApprove, onDeny, showToolCalls = false }: Props) {
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
          <div className="bg-indigo-600 text-white rounded-2xl rounded-br-sm px-5 py-3.5 text-sm leading-relaxed whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // ── Assistant message: flat, no bubble, markdown rendered ──
  return (
    <div className="w-full">
      {/* Tool calls — single compact box */}
      {showToolCalls && message.toolCalls && message.toolCalls.length > 0 && (
        <div className="mb-2">
          <ToolCallBox toolCalls={message.toolCalls} />
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
