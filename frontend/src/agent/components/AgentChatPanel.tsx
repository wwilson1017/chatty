import { useState, useRef, useEffect, useCallback, useMemo, Fragment, type RefObject, type KeyboardEvent, type DragEvent, type MouseEvent } from 'react';
import type { ChatMessage, ContextUsage, ToolMode, ModelTier } from '../hooks/useAgentChat';
import type { AgentAlert } from '../../core/types';
import { AgentMessageBubble } from './AgentMessageBubble';
import { DateDivider } from './DateDivider';
import AlertBanner from './AlertBanner';
import NotificationLog from './NotificationLog';
import { IconAttach, IconArrowUp, IconZap } from '../../shared/icons';
import { useIsMobile } from '../../shared/useIsMobile';
import { api } from '../../core/api/client';
import { toast } from '../../shared/toast';
import { localDateKey } from '../utils/dateFormat';
import { PlaybookChipsRow } from '../playbooks/PlaybookChipsRow';
import { SlashCommandMenu } from '../playbooks/SlashCommandMenu';
import { integrationLabel, type PlaybookSummary } from '../playbooks/types';

const ALLOWED_EXTENSIONS = new Set(['csv', 'xlsx', 'md', 'txt', 'pdf', 'docx']);
const MAX_FILE_SIZE = 1 * 1024 * 1024;
const MAX_PDF_SIZE = 10 * 1024 * 1024;
const MAX_FILES = 5;

function getExtension(name: string): string {
  return (name.split('.').pop() || '').toLowerCase();
}

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string, files?: File[], opts?: { playbook?: { slug: string; name: string } }) => void;
  onStop: () => void;
  onApprove?: (msgId: string) => void;
  onDeny?: (msgId: string) => void;
  onApprovePlan?: (msgId: string) => void;
  onIteratePlan?: (msgId: string) => void;
  scrollRef?: RefObject<HTMLDivElement | null>;
  contextUsage?: ContextUsage | null;
  toolMode?: ToolMode;
  onToolModeChange?: (mode: ToolMode) => void;
  alwaysPowerMode?: boolean;
  agentName?: string;
  agentSlug?: string;
  conversationSource?: string | null;
  importMode?: boolean;
  onCancelImport?: () => void;
  greetingPending?: boolean;
  modelTier?: ModelTier;
  tierLabels?: Record<string, string>;
  onSwitchTier?: (tier: ModelTier) => void;
  playbooks?: PlaybookSummary[];
  onOpenPlaybooks?: () => void;
}

const TOOL_MODES: { key: ToolMode; label: string }[] = [
  { key: 'read-only', label: 'Read' },
  { key: 'normal', label: 'Normal' },
  { key: 'power', label: 'Power' },
];

const TIER_KEYS: ModelTier[] = ['auto', 'top', 'mid', 'light'];

export function AgentChatPanel({
  messages, isStreaming, onSend, onStop, onApprove, onDeny,
  onApprovePlan, onIteratePlan, scrollRef: externalScrollRef,
  contextUsage, toolMode, onToolModeChange, alwaysPowerMode, agentName, agentSlug, conversationSource, importMode, onCancelImport,
  greetingPending,
  modelTier, tierLabels, onSwitchTier,
  playbooks, onOpenPlaybooks,
}: Props) {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AgentAlert[]>([]);
  const [stagedPlaybook, setStagedPlaybook] = useState<PlaybookSummary | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const internalScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!agentSlug) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api<{ alerts: AgentAlert[] }>(`/api/alerts?agent=${agentSlug}`);
        if (!cancelled) setAlerts(res.alerts);
      } catch { /* alerts are supplementary */ }
    })();
    return () => { cancelled = true; };
  }, [agentSlug]);
  const scrollContainerRef = externalScrollRef || internalScrollRef;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollRafRef = useRef<number | null>(null);
  useEffect(() => {
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const el = scrollContainerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
  }, [messages, scrollContainerRef]);

  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus();
  }, [isStreaming]);

  useEffect(() => {
    if (!fileError) return;
    const id = setTimeout(() => setFileError(null), 4000);
    return () => clearTimeout(id);
  }, [fileError]);

  const validateAndAddFiles = useCallback((incoming: File[]) => {
    const errors: string[] = [];
    const valid: File[] = [];

    for (const f of incoming) {
      const ext = getExtension(f.name);
      const allowed = importMode ? new Set([...ALLOWED_EXTENSIONS, 'zip']) : ALLOWED_EXTENSIONS;
      if (!allowed.has(ext)) { errors.push(`${f.name}: unsupported type (.${ext})`); continue; }
      const maxSize = ext === 'zip' ? 25 * 1024 * 1024 : (ext === 'pdf' || ext === 'docx') ? MAX_PDF_SIZE : MAX_FILE_SIZE;
      const maxLabel = ext === 'zip' ? '25 MB' : (ext === 'pdf' || ext === 'docx') ? '10 MB' : '1 MB';
      if (f.size > maxSize) { errors.push(`${f.name}: exceeds ${maxLabel}`); continue; }
      if (f.size === 0) { errors.push(`${f.name}: empty file`); continue; }
      if (pendingFiles.some(p => p.name === f.name)) { errors.push(`${f.name}: already attached`); continue; }
      valid.push(f);
    }

    const remaining = MAX_FILES - pendingFiles.length;
    if (valid.length > remaining) {
      errors.push(`Max ${MAX_FILES} files. Dropped ${valid.length - remaining}.`);
      valid.splice(remaining);
    }

    if (errors.length) setFileError(errors.join(' '));
    if (valid.length) setPendingFiles(prev => [...prev, ...valid]);
  }, [pendingFiles]);

  function removeFile(idx: number) { setPendingFiles(prev => prev.filter((_, i) => i !== idx)); }
  function handleDragOver(e: DragEvent) { e.preventDefault(); setDragOver(true); }
  function handleDragLeave(e: DragEvent) { e.preventDefault(); setDragOver(false); }
  function handleDrop(e: DragEvent) {
    e.preventDefault(); setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) validateAndAddFiles(files);
  }

  // ── Playbook staging + slash menu state machine ─────────────────────
  // Open is derived from the input ("/" as first char), so typing and
  // backspacing naturally open/filter/close the menu.
  const activePlaybooks = useMemo(
    () => (playbooks || []).filter(p => !p.archived),
    [playbooks],
  );
  const slashOpen = !importMode && input.startsWith('/') && !stagedPlaybook && activePlaybooks.length > 0;
  const slashQuery = slashOpen ? input.slice(1).toLowerCase() : '';
  const slashMatches = useMemo(
    () => activePlaybooks.filter(p =>
      p.name.toLowerCase().includes(slashQuery) || p.description.toLowerCase().includes(slashQuery)),
    [activePlaybooks, slashQuery],
  );

  // The highlight resets where the query changes (typing / opening the menu),
  // not via an effect — react-hooks/set-state-in-effect.

  function stagePlaybook(p: PlaybookSummary) {
    if (!p.available) {
      const needs = p.missing_integrations.map(integrationLabel).join(', ');
      toast.info(`“${p.name}” needs ${needs} connected. Connect it in Settings → Integrations.`);
      return;
    }
    setStagedPlaybook(p);
    setInput('');
    textareaRef.current?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (slashOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSlashIndex(i => (slashMatches.length ? (i + 1) % slashMatches.length : 0));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSlashIndex(i => (slashMatches.length ? (i - 1 + slashMatches.length) % slashMatches.length : 0));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        const pick = slashMatches[slashIndex];
        if (pick) stagePlaybook(pick);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setInput('');
        return;
      }
    }
    if (stagedPlaybook && e.key === 'Backspace' && input === '') {
      setStagedPlaybook(null);
      return;
    }
    if (stagedPlaybook && e.key === 'Escape') {
      e.preventDefault();
      setStagedPlaybook(null);
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  function handleSend() {
    const text = input.trim();
    if (slashOpen) return; // Enter is handled by the menu
    if ((!text && pendingFiles.length === 0 && !stagedPlaybook) || isStreaming) return;
    setInput('');
    if (stagedPlaybook) {
      onSend(text, pendingFiles.length > 0 ? pendingFiles : undefined,
        { playbook: { slug: stagedPlaybook.slug, name: stagedPlaybook.name } });
      setStagedPlaybook(null);
    } else {
      onSend(text || '(see attached files)', pendingFiles.length > 0 ? pendingFiles : undefined);
    }
    setPendingFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    setSlashIndex(0); // typing changes the slash query — reset the highlight
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
  }

  function handleMessagesClick(e: MouseEvent) {
    if ((e.target as HTMLElement).closest?.('button, a, input, textarea, pre, code')) return;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed && selection.toString().length > 0) return;
    textareaRef.current?.focus();
  }

  function handleToolModeClick(mode: ToolMode) {
    // The Power-mode confirm lives in AgentPage.handleToolModeChange —
    // confirming here too showed two stacked dialogs for one click.
    onToolModeChange?.(mode);
  }

  const isMobile = useIsMobile();
  const isEmpty = messages.length === 0;
  const showEmptyState = isEmpty && !isStreaming && !greetingPending;

  const chipPlaybooks = useMemo(
    () => activePlaybooks.filter(p => p.chip),
    [activePlaybooks],
  );

  function renderInputBox() {
    return (
      <div>
        {/* Playbook quick-action chips */}
        {!importMode && !stagedPlaybook && (
          <PlaybookChipsRow
            playbooks={chipPlaybooks}
            disabled={!!isStreaming}
            onInvoke={stagePlaybook}
            onOverflow={() => { setInput('/'); setSlashIndex(0); textareaRef.current?.focus(); }}
          />
        )}

        {/* Staged playbook token */}
        {stagedPlaybook && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8, padding: '0 4px' }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', background: 'rgba(212,168,90,0.10)',
              border: '1px solid rgba(212,168,90,0.3)', borderRadius: 999,
              fontSize: 11, color: '#D4A85A',
            }}>
              <IconZap size={12} strokeWidth={2} />
              {stagedPlaybook.name}
              <button onClick={() => setStagedPlaybook(null)} style={{
                background: 'none', border: 'none', color: 'rgba(212,168,90,0.7)',
                cursor: 'pointer', marginLeft: 2, fontSize: 14,
              }}>&times;</button>
            </span>
          </div>
        )}

        {/* Pending file chips */}
        {pendingFiles.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8, padding: '0 4px' }}>
            {pendingFiles.map((f, i) => (
              <span key={i} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '4px 10px', background: 'rgba(34,40,48,0.55)',
                border: '1px solid rgba(230,235,242,0.07)', borderRadius: 4,
                fontSize: 11, color: 'rgba(237,240,244,0.62)',
              }}>
                <IconAttach size={12} strokeWidth={1.85} />
                {f.name}
                <button onClick={() => removeFile(i)} style={{
                  background: 'none', border: 'none', color: 'rgba(237,240,244,0.38)',
                  cursor: 'pointer', marginLeft: 2, fontSize: 14,
                }}>&times;</button>
              </span>
            ))}
          </div>
        )}

        <div style={{
          position: 'relative',
          background: '#11141A',
          border: '1px solid rgba(230,235,242,0.14)',
          borderRadius: 6, padding: '13px 16px',
          boxShadow: '0 6px 32px rgba(0,0,0,0.5)',
        }}>
          {slashOpen && (
            <SlashCommandMenu
              matches={slashMatches}
              highlightIndex={slashIndex}
              onHighlight={setSlashIndex}
              onSelect={stagePlaybook}
              onManage={() => { setInput(''); onOpenPlaybooks?.(); }}
            />
          )}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            placeholder={stagedPlaybook
              ? `Add details for “${stagedPlaybook.name}” (optional) — Enter to run`
              : `Message ${agentName || 'agent'}…`}
            disabled={isStreaming}
            rows={1}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: 'transparent', color: '#EDF0F4',
              fontSize: 14, resize: 'none', border: 'none', outline: 'none',
              fontFamily: "'Inter Tight', system-ui, sans-serif",
              marginBottom: 12, opacity: isStreaming ? 0.5 : 1,
            }}
          />

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', color: '#EDF0F4' }}>
              <div
                onClick={() => fileInputRef.current?.click()}
                style={{ cursor: 'pointer', color: isStreaming ? 'rgba(237,240,244,0.2)' : 'rgba(237,240,244,0.62)' }}
              >
                <IconAttach size={16} strokeWidth={1.85} />
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".csv,.xlsx,.md,.txt,.pdf,.docx"
                style={{ display: 'none' }}
                onChange={e => {
                  if (e.target.files?.length) {
                    validateAndAddFiles(Array.from(e.target.files));
                    e.target.value = '';
                  }
                }}
              />

              {/* Mode selector */}
              {toolMode && onToolModeChange && (
                <div style={{
                  display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
                  borderRadius: 3, overflow: 'hidden',
                  opacity: alwaysPowerMode ? 0.5 : 1,
                }}>
                  {TOOL_MODES.map(m => (
                    <div
                      key={m.key}
                      onClick={() => !alwaysPowerMode && handleToolModeClick(m.key)}
                      style={{
                        padding: '3px 10px',
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
                        color: toolMode === m.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
                        background: toolMode === m.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
                        cursor: alwaysPowerMode ? 'default' : 'pointer',
                      }}
                    >
                      {m.label}
                    </div>
                  ))}
                </div>
              )}

              {/* Model tier toggle */}
              {tierLabels && Object.keys(tierLabels).length > 0 && onSwitchTier && !isMobile && (
                <div
                  title="Model tier"
                  style={{
                    display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
                    borderRadius: 3, overflow: 'hidden',
                    opacity: isStreaming ? 0.5 : 1,
                  }}
                >
                  {TIER_KEYS.map(tier => {
                    const isActive = modelTier === tier;
                    const label = tier === 'auto' ? 'Auto' : tierLabels[tier] || tier;
                    return (
                      <div
                        key={tier}
                        onClick={() => !isStreaming && !isActive && onSwitchTier(tier)}
                        style={{
                          padding: '3px 10px',
                          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                          fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
                          color: isActive ? '#0E1013' : 'rgba(237,240,244,0.62)',
                          background: isActive ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
                          cursor: isStreaming || isActive ? 'default' : 'pointer',
                        }}
                      >
                        {label}
                      </div>
                    );
                  })}
                </div>
              )}
              {/* Mobile tier dropdown */}
              {tierLabels && Object.keys(tierLabels).length > 0 && onSwitchTier && isMobile && (
                <select
                  value={modelTier}
                  onChange={e => !isStreaming && onSwitchTier(e.target.value as ModelTier)}
                  disabled={isStreaming}
                  style={{
                    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                    fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
                    color: 'rgba(237,240,244,0.62)',
                    background: 'transparent',
                    border: '1px solid rgba(230,235,242,0.07)',
                    borderRadius: 3, padding: '3px 6px',
                    opacity: isStreaming ? 0.5 : 1,
                  }}
                >
                  {TIER_KEYS.map(tier => (
                    <option key={tier} value={tier}>
                      {tier === 'auto' ? 'Auto' : tierLabels[tier] || tier}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {isStreaming ? (
              <button
                onClick={onStop}
                style={{
                  fontSize: 11, color: '#D97757',
                  border: '1px solid rgba(217,119,87,0.3)',
                  borderRadius: 4, padding: '4px 12px',
                  background: 'transparent', cursor: 'pointer',
                }}
              >Stop</button>
            ) : (
              <div
                onClick={handleSend}
                style={{
                  width: 32, height: 32, borderRadius: 4,
                  background: (!input.trim() && pendingFiles.length === 0 && !stagedPlaybook) ? 'rgba(200,209,217,0.3)' : 'var(--color-ch-accent, #C8D1D9)',
                  color: '#0E1013',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: (!input.trim() && pendingFiles.length === 0 && !stagedPlaybook) ? 'default' : 'pointer',
                }}
              >
                <IconArrowUp size={16} strokeWidth={2.5} />
              </div>
            )}
          </div>
        </div>

        {/* Context stats */}
        <div style={{
          textAlign: 'center', marginTop: 8,
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
          color: 'rgba(237,240,244,0.38)',
        }}>
          {contextUsage && contextUsage.contextWindow > 0 ? (() => {
            const pct = Math.max(0, Math.min(100, Math.round((contextUsage.contextTokens / contextUsage.contextWindow) * 100)));
            // Neutral < 75%, amber 75–90%, red > 90%.
            const color = pct > 90 ? '#e0524d' : pct >= 75 ? '#d9a441' : 'rgba(237,240,244,0.38)';
            return <span style={{ color }}>{`${pct}% ctx · ⏎ send`}</span>;
          })() : '⏎ send'}
        </div>
      </div>
    );
  }

  return (
    <>
    {greetingPending && <style>{`@keyframes chatty-dot-pulse { 0%,80%,100% { opacity: 0.3; } 40% { opacity: 1; } }`}</style>}
    <div
      style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 50,
          background: 'rgba(200,209,217,0.08)',
          border: '2px dashed rgba(200,209,217,0.3)',
          borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <p style={{ color: 'rgba(237,240,244,0.62)', fontSize: 16 }}>Drop files here</p>
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        style={{
          flex: 1, overflowY: 'auto',
          paddingBottom: showEmptyState ? 0 : 180,
        }}
        onClick={handleMessagesClick}
      >
        {showEmptyState ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', minHeight: '100%', padding: isMobile ? '24px 16px' : 24,
          }}>
            <div style={{ width: '100%', maxWidth: 680, marginTop: -64 }}>
              <h2 style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: isMobile ? 28 : 36, fontWeight: 400, letterSpacing: '-0.02em',
                color: 'rgba(237,240,244,0.62)', textAlign: 'center',
                marginBottom: 40, lineHeight: 1.1,
              }}>
                How can I help?
              </h2>
              {renderInputBox()}
            </div>
          </div>
        ) : (
          <div style={{ maxWidth: 680, margin: '0 auto', padding: isMobile ? '20px 16px' : '30px 40px', display: 'flex', flexDirection: 'column', gap: 22 }}>
            {conversationSource && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 8,
                ...(conversationSource?.startsWith('telegram')
                  ? { background: 'rgba(0,136,204,0.08)', border: '1px solid rgba(0,136,204,0.2)' }
                  : { background: 'rgba(37,211,102,0.08)', border: '1px solid rgba(37,211,102,0.2)' }),
              }}>
                <span style={{
                  fontSize: 11, fontWeight: 600, letterSpacing: '0.05em',
                  color: conversationSource?.startsWith('telegram') ? '#0088cc' : '#25D366',
                }}>
                  {conversationSource?.startsWith('telegram') ? (conversationSource === 'telegram-group' ? 'Telegram Group' : 'Telegram') : 'WhatsApp'}
                </span>
                <span style={{ fontSize: 11, color: 'rgba(237,240,244,0.4)' }}>
                  Messages from {conversationSource?.startsWith('telegram') ? 'Telegram' : 'WhatsApp'} appear here
                </span>
              </div>
            )}
            {importMode && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 8,
                background: 'rgba(212,168,90,0.08)', border: '1px solid rgba(212,168,90,0.2)',
              }}>
                <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', color: '#D4A85A' }}>
                  Import Mode
                </span>
                <span style={{ flex: 1, fontSize: 11, color: 'rgba(237,240,244,0.4)' }}>
                  Importing knowledge from another system
                </span>
                {onCancelImport && (
                  <button
                    onClick={onCancelImport}
                    style={{
                      background: 'transparent', border: '1px solid rgba(212,168,90,0.3)',
                      color: '#D4A85A', borderRadius: 4,
                      padding: '3px 10px', fontSize: 11, cursor: 'pointer',
                      fontFamily: "'Inter Tight', system-ui, sans-serif",
                    }}
                  >
                    Cancel
                  </button>
                )}
              </div>
            )}
            {agentSlug && <NotificationLog agentSlug={agentSlug} />}
            <AlertBanner
              alerts={alerts}
              onDismiss={async (alertId) => {
                try {
                  await api(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' });
                  setAlerts(prev => prev.filter(a => a.id !== alertId));
                } catch { toast.error('Failed to dismiss alert.'); }
              }}
              onDiscuss={(alertId) => {
                const alert = alerts.find(a => a.id === alertId);
                if (alert) {
                  onSend(`Tell me about this alert: "${alert.title}" — ${alert.message}`);
                  api(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' })
                    .catch(() => toast.error('Failed to acknowledge alert.'));
                  setAlerts(prev => prev.filter(a => a.id !== alertId));
                }
              }}
            />
            {greetingPending && isEmpty && !isStreaming && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 0' }}>
                <span style={{
                  display: 'inline-flex', gap: 4, alignItems: 'center',
                  color: 'rgba(237,240,244,0.38)', fontSize: 13,
                }}>
                  {[0, 1, 2].map(i => (
                    <span key={i} style={{
                      width: 5, height: 5, borderRadius: '50%',
                      background: 'rgba(237,240,244,0.38)',
                      animation: `chatty-dot-pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
                    }} />
                  ))}
                </span>
              </div>
            )}
            {(() => {
              const visible = messages.filter(msg => !msg.hidden);
              return visible.map((msg, i) => {
                const dayKey = localDateKey(msg.timestamp);
                const prevDayKey = i > 0 ? localDateKey(visible[i - 1].timestamp) : '';
                const showDivider = !!dayKey && dayKey !== prevDayKey;
                let displayMsg = (msg.role === 'user' && msg.content.match(/^\[via (Telegram|WhatsApp) from [^\]]+\] /))
                  ? { ...msg, content: msg.content.replace(/^\[via (?:Telegram|WhatsApp) from [^\]]+\] /, '') }
                  : msg;
                // Playbook invocation marker → strip from display, surface as a pill.
                // History reloads lack .playbook, so resolve the name from the list.
                // Unanchored: the upload path persists attached-file text before the marker.
                const pbMatch = displayMsg.role === 'user' ? displayMsg.content.match(/\[playbook:([a-z0-9-]+)\]\s*/) : null;
                if (pbMatch) {
                  const slug = pbMatch[1];
                  const known = displayMsg.playbook
                    || (playbooks?.find(p => p.slug === slug) && { slug, name: playbooks.find(p => p.slug === slug)!.name })
                    || { slug, name: slug.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase()) };
                  displayMsg = { ...displayMsg, content: displayMsg.content.replace(pbMatch[0], ''), playbook: known };
                }
                return (
                  <Fragment key={msg.id}>
                    {showDivider && <DateDivider timestamp={msg.timestamp} />}
                    <AgentMessageBubble
                      message={displayMsg}
                      onApprove={onApprove}
                      onDeny={onDeny}
                      onApprovePlan={onApprovePlan}
                      onIteratePlan={onIteratePlan}
                      agentName={agentName}
                      showModelBadge={modelTier === 'auto'}
                    />
                  </Fragment>
                );
              });
            })()}
          </div>
        )}
      </div>

      {/* File error toast */}
      {fileError && (
        <div style={{
          position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
          zIndex: 40, background: 'rgba(217,119,87,0.15)',
          border: '1px solid rgba(217,119,87,0.3)', borderRadius: 6,
          padding: '8px 16px', fontSize: 12, color: '#D97757', maxWidth: 400,
        }}>
          {fileError}
        </div>
      )}

      {/* Floating input */}
      {(!showEmptyState) && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          padding: isMobile ? '40px 12px 12px' : '60px 40px 22px',
          background: 'linear-gradient(to top, #0A0C0F 65%, transparent)',
          pointerEvents: 'none', zIndex: 20,
        }}>
          <div style={{ maxWidth: 680, margin: '0 auto', pointerEvents: 'auto' }}>
            {renderInputBox()}
          </div>
        </div>
      )}
    </div>
    </>
  );
}
