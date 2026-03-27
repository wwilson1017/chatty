/**
 * Chatty — AgentChatPanel.
 * Floating pill input with send/stop controls, file upload (paperclip + drag-and-drop).
 */

import { useState, useRef, useEffect, useCallback, type KeyboardEvent, type DragEvent } from 'react';
import type { ChatMessage } from '../hooks/useAgentChat';
import { AgentMessageBubble } from './AgentMessageBubble';

const ALLOWED_EXTENSIONS = new Set(['csv', 'xlsx', 'md', 'txt']);
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
const MAX_FILES = 5;

function getExtension(name: string): string {
  return (name.split('.').pop() || '').toLowerCase();
}

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string, files?: File[]) => void;
  onStop: () => void;
}

export function AgentChatPanel({ messages, isStreaming, onSend, onStop }: Props) {
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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
      if (f.size > MAX_FILE_SIZE) {
        errors.push(`${f.name}: exceeds 10 MB`);
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

  const isEmpty = messages.length === 0;

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

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isEmpty && !isStreaming ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="text-5xl mb-4">💬</div>
            <p className="text-gray-400">Start a conversation</p>
            <p className="text-gray-600 text-sm mt-1">Type a message below</p>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <AgentMessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* File error toast */}
      {fileError && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-40 bg-red-900/90 border border-red-700 rounded-lg px-4 py-2 text-xs text-red-200 max-w-md">
          {fileError}
        </div>
      )}

      {/* Floating pill input */}
      <div className="px-4 pb-4 pt-2">
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

        <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-xl focus-within:border-indigo-500/60 transition">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={autoResize}
            onKeyDown={handleKeyDown}
            placeholder="Message..."
            disabled={isStreaming}
            rows={1}
            className="w-full bg-transparent text-white placeholder-gray-500 text-sm px-4 pt-3 pb-0 resize-none focus:outline-none disabled:opacity-50"
          />

          <div className="flex items-center justify-between px-3 pb-2 pt-1">
            {/* Paperclip */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              title="Attach files (CSV, XLSX, MD, TXT)"
              className="text-gray-500 hover:text-gray-300 disabled:opacity-30 transition p-1"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".csv,.xlsx,.md,.txt"
              className="hidden"
              onChange={e => {
                if (e.target.files?.length) {
                  validateAndAddFiles(Array.from(e.target.files));
                  e.target.value = '';
                }
              }}
            />

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
                  className="bg-brand text-white text-xs font-semibold px-4 py-1.5 rounded-lg hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="text-center text-gray-700 text-xs mt-2">
          Enter to send · Shift+Enter for new line · Drop or clip files to attach
        </p>
      </div>
    </div>
  );
}
