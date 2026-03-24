/**
 * Chatty — AgentChatPanel.
 * Floating pill input with send/stop controls.
 */

import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import type { ChatMessage } from '../hooks/useAgentChat';
import { AgentMessageBubble } from './AgentMessageBubble';

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function AgentChatPanel({ messages, isStreaming, onSend, onStop }: Props) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');
    onSend(text);
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }

  function autoResize(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="flex-1 flex flex-col relative overflow-hidden">
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

      {/* Floating pill input */}
      <div className="px-4 pb-4 pt-2">
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

          <div className="flex items-center justify-end px-3 pb-2 pt-1 gap-2">
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
                disabled={!input.trim()}
                className="bg-brand text-white text-xs font-semibold px-4 py-1.5 rounded-lg hover:opacity-90 transition disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Send
              </button>
            )}
          </div>
        </div>
        <p className="text-center text-gray-700 text-xs mt-2">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
