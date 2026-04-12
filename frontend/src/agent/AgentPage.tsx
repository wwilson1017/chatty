/**
 * Chatty — AgentPage.
 * Immersive chat with auto-hiding top bar, tool mode selector,
 * collapsible sidebar, Chat/Knowledge/Reports/Activity tabs,
 * plan mode toggle, and Train/Improve smart detection.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { useAgentChat, type ToolMode } from './hooks/useAgentChat';
import { useConversations } from './hooks/useConversations';
import { useScrollDirection } from './hooks/useScrollDirection';
import { AgentChatPanel } from './components/AgentChatPanel';
import { AgentContextEditor } from './components/AgentContextEditor';
import ReportsPanel from './reports/ReportsPanel';
import AgentActivityPanel from './components/AgentActivityPanel';
import { ConversationSidebar } from './components/ConversationSidebar';
import { AvatarPicker } from './components/AvatarPicker';
import { TelegramSettings } from './components/TelegramSettings';

interface AgentRow {
  id: string;
  slug: string;
  agent_name: string;
  avatar_url?: string;
  onboarding_complete: boolean;
  gmail_enabled: boolean;
  calendar_enabled: boolean;
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_bot_username: string;
}

type Tab = 'chat' | 'knowledge' | 'reports' | 'activity' | 'telegram';

const TOOL_MODES: { key: ToolMode; label: string; activeClass: string }[] = [
  { key: 'read-only', label: 'Read Only', activeClass: 'bg-gray-600' },
  { key: 'normal', label: 'Normal', activeClass: 'bg-indigo-600' },
  { key: 'power', label: 'Power', activeClass: 'bg-amber-600' },
];

export function AgentPage() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [agent, setAgent] = useState<AgentRow | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('chat');
  const [showAvatarPicker, setShowAvatarPicker] = useState(false);
  const [openaiAvailable, setOpenaiAvailable] = useState(false);
  const prevOnboardingComplete = useRef<boolean | null>(null);

  const apiPrefix = `/api/agents/${agentId}`;

  const convs = useConversations(apiPrefix);

  const handleTitleUpdate = useCallback((convId: string, title: string) => {
    convs.updateConversationTitle(convId, title);
    convs.loadConversations();
  }, [convs]);

  const chat = useAgentChat(apiPrefix, { onTitleUpdate: handleTitleUpdate });

  // Scroll direction for auto-hiding top bar
  const scrollRef = useRef<HTMLDivElement>(null);
  const topBarVisible = useScrollDirection(scrollRef);

  // Load agent details
  useEffect(() => {
    if (!agentId) return;
    api<AgentRow>(`/api/agents/${agentId}`)
      .then(setAgent)
      .catch(() => navigate('/'));
  }, [agentId, navigate]);

  // Check avatar availability on mount
  useEffect(() => {
    if (!agentId) return;
    api<{ generate_available: boolean }>(`/api/agents/${agentId}/avatar/availability`)
      .then(d => setOpenaiAvailable(d.generate_available))
      .catch(() => {});
  }, [agentId]);

  // Auto-start onboarding if not complete
  const onboardingKickoffRef = useRef(false);
  useEffect(() => {
    if (!agent || onboardingKickoffRef.current) return;
    if (!agent.onboarding_complete) {
      onboardingKickoffRef.current = true;
      handleStartOnboarding();
    }
  }, [agent]);

  // When onboarding completes, exit training mode and show avatar picker
  useEffect(() => {
    if (!agent) return;
    const wasIncomplete = prevOnboardingComplete.current === false;
    prevOnboardingComplete.current = agent.onboarding_complete;
    if (wasIncomplete && agent.onboarding_complete) {
      if (chat.trainingMode) {
        chat.setTrainingMode(false);
      }
      if (!agent.avatar_url) {
        setShowAvatarPicker(true);
      }
    }
  }, [agent]);

  // Load conversation list on mount
  useEffect(() => {
    convs.loadConversations();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  async function handleSelectConversation(id: string) {
    if (chat.trainingMode) {
      chat.setTrainingMode(false);
    }
    if (chat.planMode) {
      chat.setPlanMode(false);
    }
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
    if (chat.trainingMode) {
      chat.setTrainingMode(false);
    } else if (chat.planMode) {
      chat.setPlanMode(false);
    } else {
      chat.clear();
    }
  }

  function handleStartOnboarding() {
    convs.startNewChat();
    chat.setTrainingMode(true, 'topic');
  }

  function handleStartImprove() {
    convs.startNewChat();
    chat.setTrainingMode(true, 'improve', 'Start improve mode. Review my existing knowledge and help me fill gaps.');
  }

  function handleToolModeChange(mode: ToolMode) {
    if (mode === 'power') {
      if (!window.confirm(`Enable Power mode? ${agent?.agent_name || 'This agent'} will be able to read and write without asking for confirmation.`)) return;
    }
    chat.setToolMode(mode);
  }

  function handleTogglePlanMode() {
    chat.setPlanMode(!chat.planMode);
    if (!chat.planMode) {
      convs.startNewChat();
    }
  }

  function handleAvatarComplete() {
    setShowAvatarPicker(false);
    if (agentId) {
      api<AgentRow>(`/api/agents/${agentId}`).then(setAgent).catch(() => {});
    }
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

  // Smart label: "Train" if not onboarded, "Improve" if already complete
  const trainLabel = agent.onboarding_complete ? `Improve ${agent.agent_name}` : `Train ${agent.agent_name}`;

  // Only auto-hide on chat tab; always visible on other tabs
  const showTopBar = activeTab !== 'chat' || topBarVisible;

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white overflow-hidden">
      {/* Top bar -- auto-hides on scroll in chat tab */}
      <div className={`flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-950/95 backdrop-blur-sm flex-shrink-0 z-30 transition-all duration-300 ${
        showTopBar ? 'translate-y-0 opacity-100' : '-translate-y-full opacity-0 pointer-events-none'
      }`}>
        <button
          onClick={() => navigate('/')}
          className="text-gray-400 hover:text-white transition p-1.5 rounded-lg hover:bg-gray-800 text-sm"
          title="Back to dashboard"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
        </button>

        <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-bold flex-shrink-0 overflow-hidden">
          {agent.avatar_url
            ? <img src={`${agent.avatar_url}${agent.avatar_url.includes('?') ? '&' : '?'}token=${localStorage.getItem('chatty_token') || ''}`} alt={agent.agent_name} className="w-full h-full object-cover" />
            : initials}
        </div>

        <span className="font-semibold text-white">{agent.agent_name}</span>

        {agent.onboarding_complete && !agent.avatar_url && (
          <button
            onClick={() => setShowAvatarPicker(true)}
            className="text-xs bg-gray-800 text-gray-300 border border-gray-700 rounded-full px-2.5 py-0.5 hover:bg-gray-700 transition"
            title="Set an avatar for this agent"
          >
            Set Avatar
          </button>
        )}

        {/* Tool mode selector -- hidden on mobile, only on chat tab */}
        {activeTab === 'chat' && (
          <div className="hidden sm:flex items-center bg-gray-800 rounded-full p-0.5 gap-0.5">
            {TOOL_MODES.map(m => (
              <button
                key={m.key}
                onClick={() => handleToolModeChange(m.key)}
                className={`px-2 py-0.5 text-xs font-medium rounded-full transition-all ${
                  chat.toolMode === m.key
                    ? `${m.activeClass} text-white`
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        )}

        {/* Plan mode toggle -- only on chat tab */}
        {activeTab === 'chat' && (
          <button
            onClick={handleTogglePlanMode}
            className={`hidden sm:inline-flex text-xs font-medium rounded-full px-2.5 py-0.5 transition-all ${
              chat.planMode
                ? 'bg-teal-700/60 text-teal-200 border border-teal-600/40'
                : 'bg-gray-800 text-gray-400 hover:text-white border border-gray-700'
            }`}
            title={chat.planMode ? 'Exit plan mode' : 'Enter plan mode -- agent proposes a plan before acting'}
          >
            {chat.planMode ? 'Plan Mode ON' : 'Plan Mode'}
          </button>
        )}

        {/* Train/Improve button -- only on chat tab */}
        {activeTab === 'chat' && !chat.trainingMode && (
          <button
            onClick={agent.onboarding_complete ? handleStartImprove : handleStartOnboarding}
            className="hidden sm:inline-flex text-xs font-medium rounded-full px-2.5 py-0.5 bg-gray-800 text-gray-400 hover:text-white border border-gray-700 transition"
          >
            {trainLabel}
          </button>
        )}

        {/* Tab switcher */}
        <div className="ml-auto flex items-center bg-gray-800 rounded-lg p-0.5 gap-0.5">
          {(['chat', 'knowledge', 'reports', 'activity', 'telegram'] as Tab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition ${
                activeTab === tab
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              {tab === 'chat' ? 'Chat' : tab === 'knowledge' ? 'Knowledge' : tab === 'reports' ? 'Reports' : tab === 'activity' ? 'Activity' : 'Telegram'}
            </button>
          ))}
        </div>
      </div>

      {/* Power mode warning banner */}
      {chat.toolMode === 'power' && !chat.trainingMode && (
        <div className="px-3 py-1.5 bg-amber-900/30 border-b border-amber-700/40 flex items-center gap-2 flex-shrink-0">
          <span className="text-amber-400 text-xs font-semibold">POWER MODE</span>
          <span className="text-xs text-amber-300">{agent.agent_name} can read and write without confirmation.</span>
        </div>
      )}

      {/* Plan mode banner */}
      {chat.planMode && (
        <div className="px-3 py-1.5 bg-teal-900/30 border-b border-teal-700/40 flex items-center gap-2 flex-shrink-0">
          <span className="text-teal-400 text-xs font-semibold">PLAN MODE</span>
          <span className="text-xs text-teal-300">{agent.agent_name} will propose a plan before taking action.</span>
          <button
            onClick={() => chat.setPlanMode(false)}
            className="ml-auto text-xs text-teal-400 hover:text-teal-200 transition"
          >
            Exit
          </button>
        </div>
      )}

      {/* Training mode banner */}
      {chat.trainingMode && (
        <div className="px-3 py-1.5 bg-purple-900/30 border-b border-purple-700/40 flex items-center gap-2 flex-shrink-0">
          <span className="text-purple-400 text-xs font-semibold">
            {chat.trainingType === 'improve' ? 'IMPROVE MODE' : 'TRAINING MODE'}
          </span>
          <span className="text-xs text-purple-300">
            {chat.trainingType === 'improve'
              ? `Reviewing and improving ${agent.agent_name}'s knowledge.`
              : `Teaching ${agent.agent_name} about your business.`}
          </span>
          <button
            onClick={() => chat.setTrainingMode(false)}
            className="ml-auto text-xs text-purple-400 hover:text-purple-200 transition"
          >
            Exit
          </button>
        </div>
      )}

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
              onApprove={chat.approveAction}
              onDeny={chat.denyAction}
              onApprovePlan={chat.approvePlan}
              onIteratePlan={chat.iteratePlan}
              scrollRef={scrollRef}
              contextUsage={chat.contextUsage}
              toolMode={chat.toolMode}
              onToolModeChange={handleToolModeChange}
              agentName={agent.agent_name}
            />
          </>
        ) : activeTab === 'knowledge' ? (
          <AgentContextEditor agentId={agentId!} />
        ) : activeTab === 'reports' ? (
          <ReportsPanel apiPrefix={apiPrefix} />
        ) : activeTab === 'activity' ? (
          <div className="flex-1 overflow-y-auto">
            <AgentActivityPanel apiPrefix={apiPrefix} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <TelegramSettings
              agentId={agentId!}
              agentName={agent.agent_name}
              botToken={agent.telegram_bot_token || ''}
              botUsername={agent.telegram_bot_username || ''}
              telegramEnabled={agent.telegram_enabled}
              onUpdate={() => {
                api<AgentRow>(`/api/agents/${agentId}`).then(setAgent).catch(() => {});
              }}
            />
          </div>
        )}
      </div>

      {/* Avatar picker overlay */}
      {showAvatarPicker && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl max-w-lg w-full mx-4 shadow-2xl">
            <AvatarPicker
              agentId={agentId!}
              agentName={agent.agent_name}
              openaiAvailable={openaiAvailable}
              onComplete={handleAvatarComplete}
              onSkip={() => setShowAvatarPicker(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
