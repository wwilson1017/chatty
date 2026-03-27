/**
 * Chatty — AgentPage.
 * Chat + Knowledge tabs with collapsible sidebar.
 */

import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { useAgentChat } from './hooks/useAgentChat';
import { useConversations } from './hooks/useConversations';
import { AgentChatPanel } from './components/AgentChatPanel';
import { AgentContextEditor } from './components/AgentContextEditor';
import ReportsPanel from './reports/ReportsPanel';
import { ConversationSidebar } from './components/ConversationSidebar';

interface AgentRow {
  id: string;
  slug: string;
  agent_name: string;
  avatar_url?: string;
  onboarding_complete: boolean;
  gmail_enabled: boolean;
  calendar_enabled: boolean;
}

type Tab = 'chat' | 'knowledge' | 'reports';

export function AgentPage() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [agent, setAgent] = useState<AgentRow | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('chat');

  const apiPrefix = `/api/agents/${agentId}`;

  const convs = useConversations(apiPrefix);

  const handleTitleUpdate = useCallback((convId: string, title: string) => {
    convs.updateConversationTitle(convId, title);
    convs.loadConversations();
  }, [convs]);

  const chat = useAgentChat(apiPrefix, { onTitleUpdate: handleTitleUpdate });

  // Load agent details
  useEffect(() => {
    if (!agentId) return;
    api<AgentRow>(`/api/agents/${agentId}`)
      .then(setAgent)
      .catch(() => navigate('/'));
  }, [agentId, navigate]);

  // Load conversation list on mount
  useEffect(() => {
    convs.loadConversations();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

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

  function handleStartOnboarding() {
    convs.startNewChat();
    chat.setTrainingMode(true);
  }

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const initials = agent.agent_name
    .split(' ')
    .map(w => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-950 flex-shrink-0">
        <button
          onClick={() => navigate('/')}
          className="text-gray-400 hover:text-white transition p-1.5 rounded-lg hover:bg-gray-800 text-sm"
          title="Back to dashboard"
        >
          ←
        </button>

        <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-bold flex-shrink-0 overflow-hidden">
          {agent.avatar_url
            ? <img src={agent.avatar_url} alt={agent.agent_name} className="w-full h-full object-cover" />
            : initials}
        </div>

        <span className="font-semibold text-white">{agent.agent_name}</span>

        {!agent.onboarding_complete && (
          <button
            onClick={handleStartOnboarding}
            className="text-xs bg-yellow-900/40 text-yellow-400 border border-yellow-700/40 rounded-full px-2.5 py-0.5 hover:bg-yellow-900/60 transition"
            title="Run onboarding interview"
          >
            Start Onboarding
          </button>
        )}

        {chat.trainingMode && (
          <span className="text-xs bg-blue-900/40 text-blue-400 border border-blue-700/40 rounded-full px-2.5 py-0.5 animate-pulse">
            Training
          </span>
        )}

        {/* Tab switcher */}
        <div className="ml-auto flex items-center bg-gray-800 rounded-lg p-0.5 gap-0.5">
          {(['chat', 'knowledge', 'reports'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition ${
                activeTab === tab
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              {tab === 'chat' ? 'Chat' : tab === 'knowledge' ? 'Knowledge' : 'Reports'}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        {activeTab === 'chat' ? (
          <>
            <ConversationSidebar
              agentName={agent.agent_name}
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
        ) : activeTab === 'knowledge' ? (
          <AgentContextEditor agentId={agentId!} />
        ) : (
          <ReportsPanel apiPrefix={apiPrefix} />
        )}
      </div>
    </div>
  );
}
