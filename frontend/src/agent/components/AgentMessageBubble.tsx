/**
 * Chatty — AgentMessageBubble.
 * Claude-style: flat assistant messages with markdown, branded user bubbles.
 * Individual expandable tool pills with elapsed timer. Confirmation cards for write ops.
 * Plan mode cards. Copy button per message.
 */

import { useState, useEffect, memo } from 'react';
import type { ChatMessage, ToolCallInfo, PendingConfirmation, PendingPlan } from '../hooks/useAgentChat';
import MarkdownContent from './MarkdownContent';
import { useCopyToClipboard } from '../hooks/useCopyToClipboard';
import ReportRenderer from '../reports/ReportRenderer';

interface Props {
  message: ChatMessage;
  onApprove?: (msgId: string) => void;
  onDeny?: (msgId: string) => void;
  onApprovePlan?: (msgId: string) => void;
  onIteratePlan?: (msgId: string) => void;
}

const HUNG_THRESHOLD_SEC = 30;

/* ── Helper functions ────────────────────────────────────────────── */

const TOOL_LABELS: Record<string, string> = {
  list_context_files: 'Listing files',
  read_context_file: 'Reading file',
  write_context_file: 'Writing file',
  append_to_context_file: 'Appending to file',
  delete_context_file: 'Deleting file',
  search_memory: 'Searching memory',
  append_daily_note: 'Adding daily note',
  read_daily_note: 'Reading daily note',
  list_daily_notes: 'Listing daily notes',
  read_memory: 'Reading MEMORY.md',
  update_memory: 'Updating MEMORY.md',
  add_fact: 'Recording fact',
  query_facts: 'Querying facts',
  invalidate_fact: 'Invalidating fact',
  search_emails: 'Searching emails',
  get_email: 'Reading email',
  get_email_thread: 'Reading thread',
  list_calendar_events: 'Listing events',
  get_calendar_event: 'Reading event',
  search_calendar_events: 'Searching events',
  web_search: 'Searching web',
  web_fetch: 'Fetching page',
  generate_report: 'Generating report',
  create_reminder: 'Creating reminder',
  list_reminders: 'Listing reminders',
  cancel_reminder: 'Cancelling reminder',
  create_scheduled_action: 'Creating action',
  list_scheduled_actions: 'Listing actions',
  list_shared_context: 'Listing shared context',
  read_shared_context: 'Reading shared context',
  write_shared_context: 'Writing shared context',
};

function _toolLabel(name: string): string {
  return TOOL_LABELS[name] || name.replace(/_/g, ' ');
}

function _formatArgs(args: Record<string, unknown> | undefined): string {
  if (!args || Object.keys(args).length === 0) return '(none)';
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function _formatResult(result: unknown): string {
  if (result === undefined || result === null) return '(none)';
  if (typeof result === 'string') return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

/* ── Copy Button ─────────────────────────────────────────────────── */

function CopyButton({ copied, onClick }: { copied: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="p-1 text-gray-500 hover:text-gray-300 rounded transition-colors"
      title={copied ? 'Copied!' : 'Copy message'}
    >
      {copied ? (
        <svg className="w-3.5 h-3.5 text-green-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
        </svg>
      )}
    </button>
  );
}

/* ── Tool Call Bubble (individual expandable pill) ────────────────── */

function ToolCallBubble({ tc, isExpanded, onToggle }: {
  tc: ToolCallInfo;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const isRunning = tc.status === 'running';
  const elapsed = isRunning ? Math.round((Date.now() - tc.startedAt) / 1000) : null;
  const isHung = isRunning && elapsed !== null && elapsed >= HUNG_THRESHOLD_SEC;

  return (
    <div className="text-xs rounded-lg overflow-hidden bg-gray-800/80 border border-gray-700/60 shadow-sm">
      {/* Compact header -- always visible, clickable */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-1.5 px-2.5 py-1.5 transition-opacity cursor-pointer text-gray-400 hover:bg-gray-700/40"
      >
        {/* Status dot */}
        {isRunning ? (
          <span className={`w-2 h-2 rounded-full flex-shrink-0 animate-pulse ${
            isHung ? 'bg-red-400 ring-2 ring-red-500/40' : 'bg-amber-400'
          }`} />
        ) : (
          <span className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
        )}

        {/* Tool label */}
        <span className="truncate text-gray-300">{_toolLabel(tc.tool)}</span>

        {/* Duration / elapsed timer */}
        {isRunning && elapsed !== null && elapsed > 2 && (
          <span className={`ml-auto text-[10px] tabular-nums ${
            isHung ? 'text-red-400 font-semibold' : 'text-gray-500'
          }`}>
            {elapsed}s
          </span>
        )}
        {!isRunning && tc.durationMs != null && (
          <span className="ml-auto text-[10px] tabular-nums text-gray-500">
            {tc.durationMs < 1000 ? `${tc.durationMs}ms` : `${(tc.durationMs / 1000).toFixed(1)}s`}
          </span>
        )}
        {!isRunning && tc.durationMs == null && tc.elapsedMs != null && (
          <span className="ml-auto text-[10px] tabular-nums text-gray-500">
            {tc.elapsedMs < 1000 ? `${tc.elapsedMs}ms` : `${(tc.elapsedMs / 1000).toFixed(1)}s`}
          </span>
        )}

        {/* Expand/collapse chevron */}
        <svg
          className={`w-3 h-3 flex-shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''} text-gray-500`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" />
        </svg>
      </button>

      {/* Expanded detail panel */}
      {isExpanded && (
        <div className="px-2.5 pb-2.5 space-y-1.5 border-t border-gray-700/40">
          {/* Description */}
          {tc.description && (
            <p className="text-[11px] mt-1.5 italic text-gray-500">
              {tc.description}
            </p>
          )}

          {/* Arguments */}
          {tc.args && Object.keys(tc.args).length > 0 && (
            <div>
              <div className="text-[10px] font-semibold mt-1 text-gray-500 uppercase tracking-wide">Input</div>
              <pre className="text-[11px] mt-0.5 whitespace-pre-wrap break-all leading-snug max-h-32 overflow-y-auto text-gray-300">
                {_formatArgs(tc.args)}
              </pre>
            </div>
          )}

          {/* Result */}
          {tc.result !== undefined && tc.status === 'done' && (
            <div>
              <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Output</div>
              <pre className="text-[11px] mt-0.5 whitespace-pre-wrap break-all leading-snug max-h-48 overflow-y-auto text-gray-300">
                {_formatResult(tc.result)}
              </pre>
            </div>
          )}

          {/* Still running */}
          {isRunning && !tc.result && (
            <p className={`text-[10px] italic mt-1 ${isHung ? 'text-red-400' : 'text-gray-500'}`}>
              {isHung ? 'Tool may be stuck...' : 'Waiting for result...'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Confirmation Card ────────────────────────────────────────────── */

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

/* ── Plan Card ────────────────────────────────────────────────────── */

function PlanCard({ plan, onApprove, onIterate }: {
  plan: PendingPlan;
  onApprove?: () => void;
  onIterate?: () => void;
}) {
  const borderColor = plan.status === 'approved'
    ? 'border-green-700/40 bg-green-900/15'
    : plan.status === 'iterating'
    ? 'border-gray-600/40 bg-gray-800/30'
    : 'border-teal-600/40 bg-teal-900/15';

  return (
    <div className={`mt-3 rounded-xl border p-4 ${borderColor}`}>
      <div className="flex items-center gap-2 mb-3">
        {plan.status === 'pending' && (
          <svg className="w-4 h-4 text-teal-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M8 7h8M8 12h8M8 17h4" />
          </svg>
        )}
        {plan.status === 'approved' && (
          <svg className="w-4 h-4 text-green-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {plan.status === 'iterating' && (
          <svg className="w-4 h-4 text-gray-400 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12a9 9 0 11-6.219-8.56" />
          </svg>
        )}
        <span className={`text-xs font-semibold ${
          plan.status === 'approved' ? 'text-green-300' : plan.status === 'iterating' ? 'text-gray-400' : 'text-teal-300'
        }`}>
          {plan.status === 'pending' && 'Proposed Plan'}
          {plan.status === 'approved' && 'Plan Approved'}
          {plan.status === 'iterating' && 'Refining Plan...'}
        </span>
      </div>
      <div className="text-sm text-gray-200">
        <MarkdownContent content={plan.plan} />
      </div>
      {plan.status === 'pending' && (
        <div className="flex gap-2 mt-4 pt-3 border-t border-teal-700/30">
          <button
            onClick={onApprove}
            className="px-4 py-2 text-xs font-medium bg-teal-700/60 text-teal-200 rounded-lg hover:bg-teal-700/80 transition"
          >
            Approve & Execute
          </button>
          <button
            onClick={onIterate}
            className="px-4 py-2 text-xs font-medium bg-gray-700/50 text-gray-300 rounded-lg hover:bg-gray-700/70 transition"
          >
            Keep Iterating
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Bouncing Dots ────────────────────────────────────────────────── */

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

/* ── Main Component ───────────────────────────────────────────────── */

function AgentMessageBubbleInner({ message, onApprove, onDeny, onApprovePlan, onIteratePlan }: Props) {
  const isUser = message.role === 'user';
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());
  const { copied, copy } = useCopyToClipboard();

  const toggleTool = (toolUseId: string) => {
    setExpandedTools(prev => {
      const next = new Set(prev);
      if (next.has(toolUseId)) next.delete(toolUseId);
      else next.add(toolUseId);
      return next;
    });
  };

  // Tick every second while any tool is running (for elapsed timer)
  const hasRunningTool = message.toolCalls?.some(tc => tc.status === 'running');
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!hasRunningTool) return;
    const interval = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(interval);
  }, [hasRunningTool]);

  // ── User message: branded right-aligned bubble ──
  if (isUser) {
    return (
      <div>
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
        {message.content && (
          <div className="flex justify-end mt-1">
            <CopyButton copied={copied} onClick={() => copy(message.content)} />
          </div>
        )}
      </div>
    );
  }

  // ── Assistant message: flat, no bubble, markdown rendered ──
  return (
    <div className="w-full">
      {/* Tool calls -- individual expandable pills */}
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="mb-3 space-y-1.5">
          {message.toolCalls.map((tc) => (
            <ToolCallBubble
              key={tc.toolUseId}
              tc={tc}
              isExpanded={expandedTools.has(tc.toolUseId)}
              onToggle={() => toggleTool(tc.toolUseId)}
            />
          ))}
        </div>
      )}

      {/* Message content */}
      {message.content ? (
        <MarkdownContent content={message.content} />
      ) : message.isStreaming && (!message.toolCalls || message.toolCalls.length === 0) ? (
        <BouncingDots />
      ) : null}

      {/* Inline reports */}
      {message.reports && message.reports.length > 0 && (
        <div className="mt-2 space-y-2">
          {message.reports.map(report => (
            <ReportRenderer key={report.id} report={report} compact />
          ))}
        </div>
      )}

      {/* Confirmation card */}
      {message.pendingConfirm && (
        <ConfirmationCard
          confirm={message.pendingConfirm}
          onApprove={() => onApprove?.(message.id)}
          onDeny={() => onDeny?.(message.id)}
        />
      )}

      {/* Plan card */}
      {message.pendingPlan && (
        <PlanCard
          plan={message.pendingPlan}
          onApprove={() => onApprovePlan?.(message.id)}
          onIterate={() => onIteratePlan?.(message.id)}
        />
      )}

      {/* Copy button */}
      {message.content && (
        <div className="mt-1">
          <CopyButton copied={copied} onClick={() => copy(message.content)} />
        </div>
      )}
    </div>
  );
}

export const AgentMessageBubble = memo(AgentMessageBubbleInner);
