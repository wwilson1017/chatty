/**
 * Chatty — AgentChatPanel.
 * Centered reading column with floating pill input and gradient fade.
 * File upload via paperclip + drag-and-drop. PDF support.
 * Context usage indicator. Tool mode selector. Help text.
 */

import { useState, useRef, useEffect, useCallback, type RefObject, type KeyboardEvent, type DragEvent, type MouseEvent } from 'react';
import type { ChatMessage, ContextUsage, ToolMode } from '../hooks/useAgentChat';
import { AgentMessageBubble } from './AgentMessageBubble';

const ALLOWED_EXTENSIONS = new Set(['csv', 'xlsx', 'md', 'txt', 'pdf']);
const MAX_FILE_SIZE = 1 * 1024 * 1024; // 1 MB for non-PDF
const MAX_PDF_SIZE = 10 * 1024 * 1024; // 10 MB for PDF
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
}

const TOOL_MODES: { key: ToolMode; label: string; activeClass: string }[] = [
  { key: 'read-only', label: 'Read Only', activeClass: 'bg-gray-600' },
  { key: 'normal', label: 'Normal', activeClass: 'bg-indigo-600' },
  { key: 'power', label: 'Power', activeClass: 'bg-amber-600' },
];

export function AgentChatPanel({
  messages, isStreaming, onSend, onStop, onApprove, onDeny,
  onApprovePlan, onIteratePlan, scrollRef: externalScrollRef,
  contextUsage, toolMode, onToolModeChange, agentName,
}: Props) {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const internalScrollRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = externalScrollRef || internalScrollRef;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages (rAF-throttled)
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

  // Auto-focus textarea on mount and after streaming stops
  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus();
  }, [isStreaming]);

  // Auto-dismiss file error
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
      if (!ALLOWED_EXTENSIONS.has(ext)) {
        errors.push(`${f.name}: unsupported type (.${ext})`);
        continue;
      }
      const maxSize = ext === 'pdf' ? MAX_PDF_SIZE : MAX_FILE_SIZE;
      const maxLabel = ext === 'pdf' ? '10 MB' : '1 MB';
      if (f.size > maxSize) {
        errors.push(`${f.name}: exceeds ${maxLabel}`);
        continue;
      }
      if (f.size === 0) {
        errors.push(`${f.name}: empty file`);
        continue;
      }
      if (pendingFiles.some(p => p.name === f.name)) {
        errors.push(`${f.name}: already attached`);
        continue;
      }
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

  function removeFile(idx: number) {
    setPendingFiles(prev => prev.filter((_, i) => i !== idx));
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    setDragOver(true);
  }
  function handleDragLeave(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
  }
  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) validateAndAddFiles(files);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
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

  // Click on messages area refocuses input (unless clicking interactive elements)
  function handleMessagesClick(e: MouseEvent) {
    if ((e.target as HTMLElement).closest?.('button, a, input, textarea, pre, code')) return;

    // Don't steal focus if the user just highlighted text (they probably want to copy it)
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

  const isEmpty = messages.length === 0;

  function renderInputBox() {
    return (
      <div>
        {/* Pending file chips */}
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2 px-1">
            {pendingFiles.map((f, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-gray-700 border border-gray-600 rounded-lg text-xs text-gray-300">
                <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                {f.name}
                <button onClick={() => removeFile(i)} className="text-gray-500 hover:text-gray-300 ml-0.5">&times;</button>
              </span>
            ))}
          </div>
        )}

        <div className="bg-gray-800/80 border border-gray-700 rounded-2xl shadow-lg focus-within:shadow-xl focus-within:border-indigo-500/60 transition">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            placeholder="How can I help you today?"
            disabled={isStreaming}
            rows={1}
            className="w-full bg-transparent text-white placeholder-gray-500 text-sm px-5 pt-4 pb-1 resize-none focus:outline-none disabled:opacity-50"
          />

          <div className="flex items-center justify-between px-4 pb-3 pt-1">
            {/* Left side: paperclip + tool mode */}
            <div className="flex items-center gap-2">
              {/* Paperclip */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isStreaming}
                title="Attach files (CSV, XLSX, MD, TXT, PDF)"
                className="text-gray-500 hover:text-gray-300 disabled:opacity-30 transition p-1"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".csv,.xlsx,.md,.txt,.pdf"
                className="hidden"
                onChange={e => {
                  if (e.target.files?.length) {
                    validateAndAddFiles(Array.from(e.target.files));
                    e.target.value = '';
                  }
                }}
              />

              {/* Inline tool mode selector (visible on sm+) */}
              {toolMode && onToolModeChange && (
                <div className="hidden sm:flex items-center bg-gray-900/60 rounded-full p-0.5 gap-0.5">
                  {TOOL_MODES.map(m => (
                    <button
                      key={m.key}
                      onClick={() => handleToolModeClick(m.key)}
                      className={`px-2 py-0.5 text-[10px] font-medium rounded-full transition-all ${
                        toolMode === m.key
                          ? `${m.activeClass} text-white`
                          : 'text-gray-500 hover:text-gray-300'
                      }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex gap-2">
              {isStreaming ? (
                <button
                  onClick={onStop}
                  className="text-xs text-red-400 border border-red-500/30 rounded-lg px-3 py-1.5 hover:bg-red-500/10 transition"
                >
                  Stop
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!input.trim() && pendingFiles.length === 0}
                  className="bg-brand text-white text-xs font-semibold px-4 py-1.5 rounded-full hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" /></svg>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Help text + context usage bar */}
        <div className="flex items-center justify-center gap-3 mt-1.5">
          <p className="text-[10px] text-gray-600">
            Enter to send &middot; Shift+Enter for new line
          </p>
          {contextUsage && (() => {
            const pct = Math.round((contextUsage.inputTokens / contextUsage.contextWindow) * 100);
            const barColor = pct >= 80 ? 'bg-red-400' : pct >= 60 ? 'bg-amber-400' : 'bg-emerald-400';
            return (
              <div className="w-16 h-[3px] rounded-full bg-gray-700 overflow-hidden" title={`${pct}% context used`}>
                <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>
            );
          })()}
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex-1 flex flex-col relative overflow-hidden"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div className="absolute inset-0 z-50 bg-indigo-600/20 border-2 border-dashed border-indigo-400 rounded-xl flex items-center justify-center">
          <p className="text-indigo-300 text-lg font-medium">Drop files here</p>
        </div>
      )}

      {/* Messages -- centered reading column */}
      <div
        ref={scrollContainerRef}
        className={`flex-1 overflow-y-auto ${isEmpty && !isStreaming ? '' : 'pb-40 sm:pb-48'}`}
        onClick={handleMessagesClick}
      >
        {isEmpty && !isStreaming ? (
          <div className="flex flex-col items-center justify-center min-h-full px-6">
            {/* Claude-style centered greeting + input */}
            <div className="w-full max-w-2xl -mt-16">
              <h2 className="text-3xl sm:text-4xl font-semibold text-gray-300 text-center mb-10">
                How can I help you today?
              </h2>

              {/* Inline input for empty state */}
              {renderInputBox()}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-6 sm:px-10 py-6 space-y-6">
            {messages.filter(msg => !msg.hidden).map(msg => (
              <AgentMessageBubble
                key={msg.id}
                message={msg}
                onApprove={onApprove}
                onDeny={onDeny}
                onApprovePlan={onApprovePlan}
                onIteratePlan={onIteratePlan}
              />
            ))}
          </div>
        )}
      </div>

      {/* File error toast */}
      {fileError && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 bg-red-900/90 border border-red-700 rounded-lg px-4 py-2 text-xs text-red-200 max-w-md">
          {fileError}
        </div>
      )}

      {/* Floating input -- only when messages exist */}
      {(!isEmpty || isStreaming) && (
        <div className="absolute bottom-0 inset-x-0 pointer-events-none z-20">
          <div className="h-12 bg-gradient-to-t from-gray-950 to-transparent" />

          <div className="bg-gray-950 px-3 sm:px-4 pb-3 sm:pb-4 pointer-events-auto">
            <div className="mx-auto max-w-3xl px-2 sm:px-6">
              {renderInputBox()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
