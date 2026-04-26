import { useState, useRef, useEffect, useCallback, type RefObject, type KeyboardEvent, type DragEvent, type MouseEvent } from 'react';
import type { ChatMessage, ContextUsage, ToolMode } from '../hooks/useAgentChat';
import { AgentMessageBubble } from './AgentMessageBubble';
import { IconAttach, IconArrowUp } from '../../shared/icons';
import { useIsMobile } from '../../shared/useIsMobile';

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
  onSend: (text: string, files?: File[]) => void;
  onStop: () => void;
  onApprove?: (msgId: string) => void;
  onDeny?: (msgId: string) => void;
  onApprovePlan?: (msgId: string) => void;
  onIteratePlan?: (msgId: string) => void;
  scrollRef?: RefObject<HTMLDivElement | null>;
  contextUsage?: ContextUsage | null;
  toolMode?: ToolMode;
  onToolModeChange?: (mode: ToolMode) => void;
  agentName?: string;
  conversationSource?: string | null;
  importMode?: boolean;
  onCancelImport?: () => void;
  greetingPending?: boolean;
}

const TOOL_MODES: { key: ToolMode; label: string }[] = [
  { key: 'read-only', label: 'Read' },
  { key: 'normal', label: 'Normal' },
  { key: 'power', label: 'Power' },
];

export function AgentChatPanel({
  messages, isStreaming, onSend, onStop, onApprove, onDeny,
  onApprovePlan, onIteratePlan, scrollRef: externalScrollRef,
  contextUsage, toolMode, onToolModeChange, agentName, conversationSource, importMode, onCancelImport,
  greetingPending,
}: Props) {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const internalScrollRef = useRef<HTMLDivElement>(null);
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

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  function handleSend() {
    const text = input.trim();
    if ((!text && pendingFiles.length === 0) || isStreaming) return;
    setInput('');
    onSend(text || '(see attached files)', pendingFiles.length > 0 ? pendingFiles : undefined);
    setPendingFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
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
    if (!onToolModeChange) return;
    if (mode === 'power') {
      if (!window.confirm(`Enable Power mode? ${agentName || 'This agent'} will be able to read and write without asking for confirmation.`)) return;
    }
    onToolModeChange(mode);
  }

  const isMobile = useIsMobile();
  const isEmpty = messages.length === 0;
  const showEmptyState = isEmpty && !isStreaming && !greetingPending;

  function renderInputBox() {
    return (
      <div>
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
          background: '#11141A',
          border: '1px solid rgba(230,235,242,0.14)',
          borderRadius: 6, padding: '13px 16px',
          boxShadow: '0 6px 32px rgba(0,0,0,0.5)',
        }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${agentName || 'agent'}…`}
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
                }}>
                  {TOOL_MODES.map(m => (
                    <div
                      key={m.key}
                      onClick={() => handleToolModeClick(m.key)}
                      style={{
                        padding: '3px 10px',
                        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                        fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
                        color: toolMode === m.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
                        background: toolMode === m.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
                        cursor: 'pointer',
                      }}
                    >
                      {m.label}
                    </div>
                  ))}
                </div>
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
                  background: (!input.trim() && pendingFiles.length === 0) ? 'rgba(200,209,217,0.3)' : 'var(--color-ch-accent, #C8D1D9)',
                  color: '#0E1013',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: (!input.trim() && pendingFiles.length === 0) ? 'default' : 'pointer',
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
          {contextUsage ? (() => {
            const pct = Math.round((contextUsage.inputTokens / contextUsage.contextWindow) * 100);
            return `${pct}% ctx · ⏎ send`;
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
            {messages.filter(msg => !msg.hidden).map(msg => {
              const displayMsg = (msg.role === 'user' && msg.content.match(/^\[via (Telegram|WhatsApp) from [^\]]+\] /))
                ? { ...msg, content: msg.content.replace(/^\[via (?:Telegram|WhatsApp) from [^\]]+\] /, '') }
                : msg;
              return (
                <AgentMessageBubble
                  key={msg.id}
                  message={displayMsg}
                  onApprove={onApprove}
                  onDeny={onDeny}
                  onApprovePlan={onApprovePlan}
                  onIteratePlan={onIteratePlan}
                  agentName={agentName}
                />
              );
            })}
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
