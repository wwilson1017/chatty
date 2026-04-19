import { useState, useEffect, memo } from 'react';
import type { ChatMessage, ToolCallInfo, PendingConfirmation, PendingPlan } from '../hooks/useAgentChat';
import MarkdownContent from './MarkdownContent';
import { useCopyToClipboard } from '../hooks/useCopyToClipboard';
import ReportRenderer from '../reports/ReportRenderer';
import { AgentMark } from '../../shared/AgentMark';
import { IconAttach } from '../../shared/icons';

interface Props {
  message: ChatMessage;
  onApprove?: (msgId: string) => void;
  onDeny?: (msgId: string) => void;
  onApprovePlan?: (msgId: string) => void;
  onIteratePlan?: (msgId: string) => void;
  agentName?: string;
}

const HUNG_THRESHOLD_SEC = 30;

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
  try { return JSON.stringify(args, null, 2); } catch { return String(args); }
}

function _formatResult(result: unknown): string {
  if (result === undefined || result === null) return '(none)';
  if (typeof result === 'string') return result;
  try { return JSON.stringify(result, null, 2); } catch { return String(result); }
}

function CopyButton({ copied, onClick }: { copied: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: 'none', border: 'none', padding: 4,
        color: copied ? '#8EA589' : 'rgba(237,240,244,0.38)',
        cursor: 'pointer',
      }}
      title={copied ? 'Copied!' : 'Copy message'}
    >
      {copied ? (
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
        </svg>
      )}
    </button>
  );
}

function ToolCallBubble({ tc, isExpanded, onToggle }: {
  tc: ToolCallInfo;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const isRunning = tc.status === 'running';
  const [elapsed, setElapsed] = useState<number | null>(null);
  useEffect(() => {
    if (!isRunning) return;
    const update = () => setElapsed(Math.round((Date.now() - tc.startedAt) / 1000));
    update();
    const id = setInterval(update, 1000);
    return () => { clearInterval(id); setElapsed(null); };
  }, [isRunning, tc.startedAt]);
  const isHung = isRunning && elapsed !== null && elapsed >= HUNG_THRESHOLD_SEC;

  return (
    <div style={{
      fontSize: 12, borderRadius: 6, overflow: 'hidden',
      background: 'rgba(20,24,30,0.78)',
      border: '1px solid rgba(230,235,242,0.07)',
    }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 10px', cursor: 'pointer',
          color: 'rgba(237,240,244,0.62)', background: 'transparent', border: 'none',
          fontFamily: "'Inter Tight', system-ui, sans-serif", fontSize: 12,
        }}
      >
        <span style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: isRunning ? (isHung ? '#D97757' : '#D4A85A') : '#8EA589',
          animation: isRunning ? 'pulse 2s infinite' : 'none',
        }} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#EDF0F4' }}>
          {_toolLabel(tc.tool)}
        </span>
        {isRunning && elapsed !== null && elapsed > 2 && (
          <span style={{
            marginLeft: 'auto',
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, color: isHung ? '#D97757' : 'rgba(237,240,244,0.38)',
            fontVariantNumeric: 'tabular-nums',
          }}>{elapsed}s</span>
        )}
        {!isRunning && tc.durationMs != null && (
          <span style={{
            marginLeft: 'auto',
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, color: 'rgba(237,240,244,0.38)',
            fontVariantNumeric: 'tabular-nums',
          }}>
            {tc.durationMs < 1000 ? `${tc.durationMs}ms` : `${(tc.durationMs / 1000).toFixed(1)}s`}
          </span>
        )}
        {!isRunning && tc.durationMs == null && tc.elapsedMs != null && (
          <span style={{
            marginLeft: 'auto',
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, color: 'rgba(237,240,244,0.38)',
            fontVariantNumeric: 'tabular-nums',
          }}>
            {tc.elapsedMs < 1000 ? `${tc.elapsedMs}ms` : `${(tc.elapsedMs / 1000).toFixed(1)}s`}
          </span>
        )}
        <svg width={12} height={12} viewBox="0 0 20 20" fill="currentColor"
          style={{ flexShrink: 0, transition: 'transform 0.2s', transform: isExpanded ? 'rotate(180deg)' : '', color: 'rgba(237,240,244,0.38)' }}>
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" />
        </svg>
      </button>

      {isExpanded && (
        <div style={{
          padding: '0 10px 10px', borderTop: '1px solid rgba(230,235,242,0.07)',
          fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 11,
        }}>
          {tc.description && (
            <p style={{ fontSize: 11, fontStyle: 'italic', color: 'rgba(237,240,244,0.38)', marginTop: 6 }}>
              {tc.description}
            </p>
          )}
          {tc.args && Object.keys(tc.args).length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(237,240,244,0.38)' }}>Input</div>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: 1.4, maxHeight: 128, overflowY: 'auto', color: 'rgba(237,240,244,0.62)', marginTop: 4 }}>
                {_formatArgs(tc.args)}
              </pre>
            </div>
          )}
          {tc.result !== undefined && tc.status === 'done' && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'rgba(237,240,244,0.38)' }}>Output</div>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: 1.4, maxHeight: 192, overflowY: 'auto', color: 'rgba(237,240,244,0.62)', marginTop: 4 }}>
                {_formatResult(tc.result)}
              </pre>
            </div>
          )}
          {isRunning && !tc.result && (
            <p style={{ fontSize: 10, fontStyle: 'italic', marginTop: 6, color: isHung ? '#D97757' : 'rgba(237,240,244,0.38)' }}>
              {isHung ? 'Tool may be stuck...' : 'Waiting for result...'}
            </p>
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
  const bg = confirm.status === 'approved' ? 'rgba(142,165,137,0.08)' : confirm.status === 'denied' ? 'rgba(217,119,87,0.08)' : 'rgba(212,168,90,0.06)';
  const border = confirm.status === 'approved' ? 'rgba(142,165,137,0.2)' : confirm.status === 'denied' ? 'rgba(217,119,87,0.2)' : 'rgba(212,168,90,0.15)';
  const dotColor = confirm.status === 'approved' ? '#8EA589' : confirm.status === 'denied' ? '#D97757' : '#D4A85A';
  const statusLabel = confirm.status === 'approved' ? 'Approved' : confirm.status === 'denied' ? 'Denied' : 'Awaiting approval';

  return (
    <div style={{ marginTop: 12, borderRadius: 6, border: `1px solid ${border}`, background: bg, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, animation: confirm.status === 'pending' ? 'pulse 2s infinite' : 'none' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: '#EDF0F4' }}>{statusLabel}</span>
      </div>
      <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)', marginBottom: 8 }}>
        {confirm.description || `Execute ${confirm.tool}`}
      </p>
      {confirm.status === 'pending' && (
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onApprove} style={{
            padding: '5px 12px', fontSize: 12, fontWeight: 500, borderRadius: 4,
            background: 'rgba(142,165,137,0.2)', color: '#8EA589',
            border: 'none', cursor: 'pointer',
          }}>Approve</button>
          <button onClick={onDeny} style={{
            padding: '5px 12px', fontSize: 12, fontWeight: 500, borderRadius: 4,
            background: 'rgba(217,119,87,0.15)', color: '#D97757',
            border: 'none', cursor: 'pointer',
          }}>Deny</button>
        </div>
      )}
    </div>
  );
}

function PlanCard({ plan, onApprove, onIterate }: {
  plan: PendingPlan;
  onApprove?: () => void;
  onIterate?: () => void;
}) {
  const bg = plan.status === 'approved' ? 'rgba(142,165,137,0.06)' : plan.status === 'iterating' ? 'rgba(34,40,48,0.55)' : 'rgba(212,168,90,0.06)';
  const border = plan.status === 'approved' ? 'rgba(142,165,137,0.15)' : plan.status === 'iterating' ? 'rgba(230,235,242,0.07)' : 'rgba(212,168,90,0.15)';

  return (
    <div style={{ marginTop: 12, borderRadius: 6, border: `1px solid ${border}`, background: bg, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: plan.status === 'approved' ? '#8EA589' : plan.status === 'iterating' ? 'rgba(237,240,244,0.38)' : '#D4A85A',
        }}>
          {plan.status === 'pending' && 'Proposed Plan'}
          {plan.status === 'approved' && 'Plan Approved'}
          {plan.status === 'iterating' && 'Refining Plan...'}
        </span>
      </div>
      <div style={{ fontSize: 14, color: '#EDF0F4' }}>
        <MarkdownContent content={plan.plan} />
      </div>
      {plan.status === 'pending' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 16, paddingTop: 12, borderTop: `1px solid ${border}` }}>
          <button onClick={onApprove} style={{
            padding: '7px 14px', fontSize: 12, fontWeight: 500, borderRadius: 4,
            background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
            border: 'none', cursor: 'pointer',
          }}>Approve & Execute</button>
          <button onClick={onIterate} style={{
            padding: '7px 14px', fontSize: 12, fontWeight: 500, borderRadius: 4,
            background: 'transparent', color: '#EDF0F4',
            border: '1px solid rgba(230,235,242,0.14)', cursor: 'pointer',
          }}>Keep Iterating</button>
        </div>
      )}
    </div>
  );
}

function TypingDots() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3, paddingLeft: 42 }}>
      <div style={{ display: 'flex', gap: 3 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 5, height: 5, borderRadius: '50%',
            background: 'var(--color-ch-accent, #C8D1D9)', opacity: 0.7,
            animation: `typedot 1.2s infinite ${i * 0.15}s`,
          }} />
        ))}
      </div>
      <style>{`@keyframes typedot { 0%,80%,100% { transform: scale(0.6); opacity: 0.3; } 40% { transform: scale(1); opacity: 1; } }`}</style>
    </div>
  );
}

function AgentMessageBubbleInner({ message, onApprove, onDeny, onApprovePlan, onIteratePlan, agentName }: Props) {
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

  const hasRunningTool = message.toolCalls?.some(tc => tc.status === 'running');
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!hasRunningTool) return;
    const interval = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(interval);
  }, [hasRunningTool]);

  if (isUser) {
    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <div style={{ maxWidth: '80%' }}>
            {message.attachments && message.attachments.length > 0 && (
              <div style={{ marginBottom: 6, display: 'flex', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-end' }}>
                {message.attachments.map((att, i) => (
                  <span key={i} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    padding: '2px 8px', background: 'rgba(200,209,217,0.12)',
                    border: '1px solid rgba(230,235,242,0.14)', borderRadius: 3,
                    fontSize: 11, color: 'rgba(237,240,244,0.62)',
                  }}>
                    <IconAttach size={12} strokeWidth={1.85} />
                    {att.name}
                  </span>
                ))}
              </div>
            )}
            <div style={{
              padding: '11px 16px',
              background: 'rgba(200,209,217,0.12)',
              border: '1px solid rgba(230,235,242,0.14)',
              borderRadius: '10px 10px 3px 10px',
              fontSize: 14.5, lineHeight: 1.5, color: '#EDF0F4',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {message.content}
            </div>
          </div>
        </div>
        {message.content && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
            <CopyButton copied={copied} onClick={() => copy(message.content)} />
          </div>
        )}
      </div>
    );
  }

  const letter = agentName?.charAt(0) || 'A';

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      <AgentMark letter={letter} size={30} />
      <div style={{ flex: 1, maxWidth: '85%' }}>
        {/* Agent name + timestamp */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 14, color: '#D4A85A',
          }}>{agentName || 'Agent'}</div>
        </div>

        {/* Tool calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {message.toolCalls.map(tc => (
              <ToolCallBubble
                key={tc.toolUseId}
                tc={tc}
                isExpanded={expandedTools.has(tc.toolUseId)}
                onToggle={() => toggleTool(tc.toolUseId)}
              />
            ))}
          </div>
        )}

        {/* Content */}
        {message.content ? (
          <div style={{ fontSize: 14.5, lineHeight: 1.6, color: '#EDF0F4' }}>
            <MarkdownContent content={message.content} />
          </div>
        ) : message.isStreaming && (!message.toolCalls || message.toolCalls.length === 0) ? (
          <TypingDots />
        ) : null}

        {/* Reports */}
        {message.reports && message.reports.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {message.reports.map(report => (
              <ReportRenderer key={report.id} report={report} compact />
            ))}
          </div>
        )}

        {/* Confirmation */}
        {message.pendingConfirm && (
          <ConfirmationCard
            confirm={message.pendingConfirm}
            onApprove={() => onApprove?.(message.id)}
            onDeny={() => onDeny?.(message.id)}
          />
        )}

        {/* Plan */}
        {message.pendingPlan && (
          <PlanCard
            plan={message.pendingPlan}
            onApprove={() => onApprovePlan?.(message.id)}
            onIterate={() => onIteratePlan?.(message.id)}
          />
        )}

        {/* Copy */}
        {message.content && (
          <div style={{ marginTop: 4 }}>
            <CopyButton copied={copied} onClick={() => copy(message.content)} />
          </div>
        )}
      </div>
    </div>
  );
}

export const AgentMessageBubble = memo(AgentMessageBubbleInner);
