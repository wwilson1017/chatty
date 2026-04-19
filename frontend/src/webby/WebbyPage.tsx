/**
 * Chatty — WebbyPage.
 * Wraps AgentPage with an additional Preview tab.
 * Phase 1: Preview tab is a placeholder; full implementation in Phase 2.
 *
 * Adapted from CAKE OS webby-website-agent frontend.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { useAgentChat } from '../agent/hooks/useAgentChat';
import { useConversations } from '../agent/hooks/useConversations';
import { AgentChatPanel } from '../agent/components/AgentChatPanel';
import { AgentContextEditor } from '../agent/components/AgentContextEditor';
import { ConversationSidebar } from '../agent/components/ConversationSidebar';
import { PreviewPanel } from './components/PreviewPanel';

interface WebbyStatus {
  exists: boolean;
  agent_id: string | null;
  onboarding_complete?: boolean;
}

type Tab = 'chat' | 'knowledge' | 'preview';

export function WebbyPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<WebbyStatus | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('chat');
  const [creating, setCreating] = useState(false);

  const apiPrefix = `/api/agents/${agentId}`;
  const convs = useConversations(apiPrefix);

  const handleTitleUpdate = useCallback((convId: string, title: string) => {
    convs.updateConversationTitle(convId, title);
    convs.loadConversations();
  }, [convs]);

  const chat = useAgentChat(apiPrefix, { onTitleUpdate: handleTitleUpdate });

  useEffect(() => {
    api<WebbyStatus>('/api/webby/status').then(s => {
      setStatus(s);
      if (s.agent_id) setAgentId(s.agent_id);
    });
  }, []);

  useEffect(() => {
    if (agentId) convs.loadConversations();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  async function handleCreate() {
    setCreating(true);
    try {
      const data = await api<{ agent_id: string }>('/api/webby/create', { method: 'POST' });
      setAgentId(data.agent_id);
      setStatus(prev => prev ? { ...prev, exists: true, agent_id: data.agent_id } : null);
      chat.setTrainingMode(true);
    } finally {
      setCreating(false);
    }
  }

  async function handleSelectConversation(id: string) {
    const msgs = await convs.selectConversation(id);
    chat.loadMessages(msgs, id);
  }

  async function handleDeleteConversation(id: string) {
    if (!confirm('Delete this conversation?')) return;
    await convs.deleteConversation(id);
    if (convs.activeId === id) chat.clear();
  }

  function handleNewChat() {
    convs.startNewChat();
    chat.clear();
  }

  // Loading
  if (!status) {
    return (
      <div className="flex items-center justify-center h-screen bg-ch-bg">
        <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Webby agent doesn't exist yet — show setup prompt
  if (!status.exists || !agentId) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-ch-bg text-center px-6">
        <div className="text-6xl mb-6">🌐</div>
        <h1 className="text-2xl font-bold text-white mb-2">Meet Webby</h1>
        <p className="text-ch-ink-mute max-w-md mb-8">
          Webby manages your website through GitHub. Describe what you want changed
          in plain language — no coding required.
        </p>
        <div className="bg-ch-bg-elev border border-ch-line-strong rounded-md p-4 text-left text-sm text-ch-ink-mute mb-8 max-w-md">
          <p className="font-medium text-ch-ink-mute mb-2">Phase 1 — Preview</p>
          <p>GitHub editing tools are stubs in this version. Webby can be onboarded and chat,
          but file editing and pull requests require Phase 2.</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/')}
            className="px-4 py-2 rounded-lg border border-ch-line-strong text-ch-ink-mute hover:text-white text-sm transition"
          >
            Back to Dashboard
          </button>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-5 py-2 rounded-lg bg-brand text-white text-sm font-semibold hover:opacity-90 transition disabled:opacity-50"
          >
            {creating ? 'Setting up...' : 'Set Up Webby'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-ch-bg text-white overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ch-line bg-ch-bg flex-shrink-0">
        <button
          onClick={() => navigate('/')}
          className="text-ch-ink-mute hover:text-white transition p-1.5 rounded-lg hover:bg-ch-bg-raised text-sm"
        >
          ←
        </button>

        <div className="w-8 h-8 rounded-full bg-emerald-700 flex items-center justify-center text-sm flex-shrink-0">
          🌐
        </div>

        <span className="font-semibold text-white">Webby</span>

        <span className="text-xs bg-yellow-900/40 text-yellow-500 border border-yellow-700/30 rounded-full px-2 py-0.5">
          Phase 1 Stub
        </span>

        {chat.trainingMode && (
          <span className="text-xs bg-blue-900/40 text-blue-400 border border-blue-700/40 rounded-full px-2.5 py-0.5 animate-pulse">
            Onboarding
          </span>
        )}

        {/* Tab switcher */}
        <div className="ml-auto flex items-center bg-ch-bg-raised rounded-lg p-0.5 gap-0.5">
          {(['chat', 'knowledge', 'preview'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition capitalize ${
                activeTab === tab
                  ? 'bg-ch-bg-raised text-white'
                  : 'text-ch-ink-mute hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {activeTab === 'chat' && (
          <>
            <ConversationSidebar
              agentName="Webby"
              conversations={convs.conversations}
              activeId={convs.activeId}
              searchQuery={convs.searchQuery}
              searchResults={convs.searchResults}
              isSearching={convs.isSearching}
              onNew={handleNewChat}
              onSelect={handleSelectConversation}
              onDelete={handleDeleteConversation}
              onSearch={convs.searchConversations}
              onRename={convs.renameConversation}
            />
            <AgentChatPanel
              messages={chat.messages}
              isStreaming={chat.isStreaming}
              onSend={chat.sendMessage}
              onStop={chat.stop}
            />
          </>
        )}

        {activeTab === 'knowledge' && (
          <AgentContextEditor agentId={agentId} />
        )}

        {activeTab === 'preview' && (
          <div className="flex-1 flex flex-col">
            <PreviewPanel preview={null} />
          </div>
        )}
      </div>
    </div>
  );
}
