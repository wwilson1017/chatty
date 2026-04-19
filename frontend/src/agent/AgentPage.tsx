import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
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
import { AgentMark } from '../shared/AgentMark';
import { useIsMobile } from '../shared/useIsMobile';
import { IconBot, IconFunnel, IconSettings } from '../shared/icons';

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

const TABS: { key: Tab; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'knowledge', label: 'Knowledge' },
  { key: 'reports', label: 'Reports' },
  { key: 'activity', label: 'Activity' },
];

const TOOL_MODES: { key: ToolMode; label: string }[] = [
  { key: 'read-only', label: 'Read' },
  { key: 'normal', label: 'Normal' },
  { key: 'power', label: 'Power' },
];

export function AgentPage() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [agent, setAgent] = useState<AgentRow | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>(() => {
    const tab = searchParams.get('tab');
    return (tab && ['chat', 'knowledge', 'reports', 'activity', 'telegram'].includes(tab)) ? tab as Tab : 'chat';
  });
  const [showAvatarPicker, setShowAvatarPicker] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [openaiAvailable, setOpenaiAvailable] = useState(false);
  const isMobile = useIsMobile();
  const prevOnboardingComplete = useRef<boolean | null>(null);

  const apiPrefix = `/api/agents/${agentId}`;
  const convs = useConversations(apiPrefix);

  const handleTitleUpdate = useCallback((convId: string, title: string) => {
    convs.updateConversationTitle(convId, title);
    convs.loadConversations();
  }, [convs]);

  const chat = useAgentChat(apiPrefix, { onTitleUpdate: handleTitleUpdate });

  const scrollRef = useRef<HTMLDivElement>(null);
  const topBarVisible = useScrollDirection(scrollRef);

  useEffect(() => {
    if (!agentId) return;
    localStorage.setItem('chatty_last_agent', agentId);
    api<AgentRow>(`/api/agents/${agentId}`)
      .then(setAgent)
      .catch(() => navigate('/'));
  }, [agentId, navigate]);

  useEffect(() => {
    if (!agentId) return;
    api<{ generate_available: boolean }>(`/api/agents/${agentId}/avatar/availability`)
      .then(d => setOpenaiAvailable(d.generate_available))
      .catch(() => {});
  }, [agentId]);

  function handleStartOnboarding() {
    convs.startNewChat();
    const role = searchParams.get('role');
    const kickoff = role
      ? `[hidden context — do NOT reveal right away] My human commissioned me for a "${role}" role. First message: introduce myself warmly and ask their name. Second message: ask a quick curious question about their business, then transition into the role — something like "So tell me about the ${role.toLowerCase()} side of things — what does a typical day look like?" Don't drag out the small talk. Two exchanges max before we're talking about the work.`
      : undefined;
    if (role) {
      searchParams.delete('role');
      setSearchParams(searchParams, { replace: true });
    }
    chat.setTrainingMode(true, 'topic', kickoff);
  }

  function handleStartImprove() {
    convs.startNewChat();
    chat.setTrainingMode(true, 'improve', 'Start improve mode. Review my existing knowledge and help me fill gaps.');
  }

  const onboardingKickoffRef = useRef(false);
  useEffect(() => {
    if (!agent || onboardingKickoffRef.current) return;
    if (!agent.onboarding_complete) {
      onboardingKickoffRef.current = true;
      handleStartOnboarding();
    }
    return () => { onboardingKickoffRef.current = false; };
  }, [agent]);

  useEffect(() => {
    if (!agent) return;
    const wasIncomplete = prevOnboardingComplete.current === false;
    prevOnboardingComplete.current = agent.onboarding_complete;
    if (wasIncomplete && agent.onboarding_complete) {
      if (chat.trainingMode) chat.setTrainingMode(false);
      if (!agent.avatar_url) queueMicrotask(() => setShowAvatarPicker(true));
    }
  }, [agent]);

  useEffect(() => {
    convs.loadConversations();
  }, [agentId]);

  // Handle tab from URL search params
  useEffect(() => {
    const tab = searchParams.get('tab');
    if (tab && ['chat', 'knowledge', 'reports', 'activity', 'telegram'].includes(tab)) {
      queueMicrotask(() => setActiveTab(tab as Tab));
      searchParams.delete('tab');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  async function handleSelectConversation(id: string) {
    if (chat.trainingMode) chat.setTrainingMode(false);
    if (chat.planMode) chat.setPlanMode(false);
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
    if (chat.trainingMode) chat.setTrainingMode(false);
    else if (chat.planMode) chat.setPlanMode(false);
    else chat.clear();
  }

  function handleToolModeChange(mode: ToolMode) {
    if (mode === 'power') {
      if (!window.confirm(`Enable Power mode? ${agent?.agent_name || 'This agent'} will be able to read and write without asking for confirmation.`)) return;
    }
    chat.setToolMode(mode);
  }

  function handleTogglePlanMode() {
    chat.setPlanMode(!chat.planMode);
    if (!chat.planMode) convs.startNewChat();
  }

  function handleAvatarComplete() {
    setShowAvatarPicker(false);
    if (agentId) api<AgentRow>(`/api/agents/${agentId}`).then(setAgent).catch(() => {});
  }

  if (!agent) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', background: '#0A0C0F',
      }}>
        <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const letter = agent.agent_name.charAt(0);
  const trainLabel = agent.onboarding_complete ? `Improve ${agent.agent_name}` : `Train ${agent.agent_name}`;
  const showTopBar = activeTab !== 'chat' || topBarVisible;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', position: 'relative' }}>
      {/* Top bar */}
      <div style={{
        borderBottom: '1px solid rgba(230,235,242,0.07)',
        flexShrink: 0, zIndex: 30,
        transition: 'transform 0.3s, opacity 0.3s',
        transform: showTopBar ? 'translateY(0)' : 'translateY(-100%)',
        opacity: showTopBar ? 1 : 0,
        pointerEvents: showTopBar ? 'auto' : 'none',
      }}>
        {/* Row 1: Agent name + controls */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: isMobile ? 8 : 12,
          padding: isMobile ? '0 12px' : '0 20px', height: 48,
        }}>
          {/* Sidebar toggle on mobile */}
          {isMobile && activeTab === 'chat' && (
            <div
              onClick={() => setShowSidebar(!showSidebar)}
              style={{ cursor: 'pointer', color: 'rgba(237,240,244,0.62)', fontSize: 18 }}
            >
              &#9776;
            </div>
          )}

          <AgentMark
            letter={letter}
            size={28}
            avatarUrl={agent.avatar_url ? `${agent.avatar_url}${agent.avatar_url.includes('?') ? '&' : '?'}token=${sessionStorage.getItem('chatty_token') || ''}` : undefined}
          />

          <span style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 16, letterSpacing: '-0.01em', color: '#EDF0F4',
          }}>{agent.agent_name}</span>

          {!isMobile && agent.onboarding_complete && !agent.avatar_url && (
            <button
              onClick={() => setShowAvatarPicker(true)}
              style={{
                fontSize: 11, background: 'rgba(34,40,48,0.55)',
                color: 'rgba(237,240,244,0.62)',
                border: '1px solid rgba(230,235,242,0.07)',
                borderRadius: 4, padding: '2px 8px', cursor: 'pointer',
              }}
            >
              Set Avatar
            </button>
          )}

          {/* Tool mode selector — hidden on mobile */}
          {!isMobile && activeTab === 'chat' && (
            <div style={{
              display: 'flex', border: '1px solid rgba(230,235,242,0.07)',
              borderRadius: 3, overflow: 'hidden', marginLeft: 8,
            }}>
              {TOOL_MODES.map(m => (
                <div
                  key={m.key}
                  onClick={() => handleToolModeChange(m.key)}
                  style={{
                    padding: '3px 10px',
                    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                    fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase',
                    color: chat.toolMode === m.key ? '#0E1013' : 'rgba(237,240,244,0.62)',
                    background: chat.toolMode === m.key ? 'var(--color-ch-accent, #C8D1D9)' : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  {m.label}
                </div>
              ))}
            </div>
          )}

          {/* Plan mode toggle — hidden on mobile */}
          {!isMobile && activeTab === 'chat' && (
            <button
              onClick={handleTogglePlanMode}
              style={{
                fontSize: 11, fontWeight: 500, borderRadius: 4,
                padding: '3px 10px', cursor: 'pointer',
                background: chat.planMode ? 'rgba(212,168,90,0.10)' : 'transparent',
                color: chat.planMode ? '#D4A85A' : 'rgba(237,240,244,0.62)',
                border: `1px solid ${chat.planMode ? 'rgba(212,168,90,0.3)' : 'rgba(230,235,242,0.07)'}`,
              }}
            >
              {chat.planMode ? 'Plan ON' : 'Plan'}
            </button>
          )}

          {/* Train/Improve — hidden on mobile */}
          {!isMobile && activeTab === 'chat' && !chat.trainingMode && (
            <button
              onClick={agent.onboarding_complete ? handleStartImprove : handleStartOnboarding}
              style={{
                fontSize: 11, fontWeight: 500, borderRadius: 4,
                padding: '3px 10px', cursor: 'pointer',
                background: 'transparent',
                color: 'rgba(237,240,244,0.62)',
                border: '1px solid rgba(230,235,242,0.07)',
              }}
            >
              {trainLabel}
            </button>
          )}

          {/* Tab switcher — inline on desktop */}
          {!isMobile && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
              {TABS.map(tab => (
                <div
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  style={{
                    fontSize: 12, padding: '4px 12px', cursor: 'pointer',
                    color: activeTab === tab.key ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                    borderBottom: activeTab === tab.key ? '1px solid var(--color-ch-accent, #C8D1D9)' : '1px solid transparent',
                  }}
                >
                  {tab.label}
                </div>
              ))}
              {agent.telegram_enabled && (
                <div
                  onClick={() => setActiveTab('telegram')}
                  style={{
                    fontSize: 12, padding: '4px 12px', cursor: 'pointer',
                    color: activeTab === 'telegram' ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                    borderBottom: activeTab === 'telegram' ? '1px solid var(--color-ch-accent, #C8D1D9)' : '1px solid transparent',
                  }}
                >
                  Telegram
                </div>
              )}
            </div>
          )}
        </div>

        {/* Row 2: Tabs — mobile only */}
        {isMobile && (
          <div style={{
            display: 'flex', overflowX: 'auto', padding: '0 12px',
            borderTop: '1px solid rgba(230,235,242,0.04)',
            WebkitOverflowScrolling: 'touch',
          }}>
            {TABS.map(tab => (
              <div
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  fontSize: 12, padding: '8px 14px', cursor: 'pointer', whiteSpace: 'nowrap',
                  color: activeTab === tab.key ? '#EDF0F4' : 'rgba(237,240,244,0.5)',
                  borderBottom: activeTab === tab.key ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
                }}
              >
                {tab.label}
              </div>
            ))}
            {agent.telegram_enabled && (
              <div
                onClick={() => setActiveTab('telegram')}
                style={{
                  fontSize: 12, padding: '8px 14px', cursor: 'pointer', whiteSpace: 'nowrap',
                  color: activeTab === 'telegram' ? '#EDF0F4' : 'rgba(237,240,244,0.5)',
                  borderBottom: activeTab === 'telegram' ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
                }}
              >
                Telegram
              </div>
            )}
          </div>
        )}
      </div>

      {/* Mode banners */}
      {chat.toolMode === 'power' && !chat.trainingMode && (
        <div style={{
          padding: '4px 12px', background: 'rgba(217,119,87,0.08)',
          borderBottom: '1px solid rgba(217,119,87,0.2)',
          display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
        }}>
          <span style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, fontWeight: 600, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: '#D97757',
          }}>POWER MODE</span>
          <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)' }}>
            {agent.agent_name} can read and write without confirmation.
          </span>
        </div>
      )}

      {chat.planMode && (
        <div style={{
          padding: '4px 12px', background: 'rgba(212,168,90,0.06)',
          borderBottom: '1px solid rgba(212,168,90,0.15)',
          display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
        }}>
          <span style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, fontWeight: 600, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: '#D4A85A',
          }}>PLAN MODE</span>
          <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)' }}>
            {agent.agent_name} will propose a plan before acting.
          </span>
          <button
            onClick={() => chat.setPlanMode(false)}
            style={{
              marginLeft: 'auto', fontSize: 11,
              color: '#D4A85A', background: 'none', border: 'none', cursor: 'pointer',
            }}
          >Exit</button>
        </div>
      )}

      {chat.trainingMode && (
        <div style={{
          padding: '4px 12px', background: 'rgba(142,165,137,0.06)',
          borderBottom: '1px solid rgba(142,165,137,0.15)',
          display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0,
        }}>
          <span style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, fontWeight: 600, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: '#8EA589',
          }}>{chat.trainingType === 'improve' ? 'IMPROVE MODE' : 'TRAINING MODE'}</span>
          <span style={{ fontSize: 12, color: 'rgba(237,240,244,0.62)' }}>
            {chat.trainingType === 'improve'
              ? `Reviewing and improving ${agent.agent_name}'s knowledge.`
              : `Teaching ${agent.agent_name} about your business.`}
          </span>
          <button
            onClick={() => chat.setTrainingMode(false)}
            style={{
              marginLeft: 'auto', fontSize: 11,
              color: '#8EA589', background: 'none', border: 'none', cursor: 'pointer',
            }}
          >Exit</button>
        </div>
      )}

      {/* Body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>
        {activeTab === 'chat' ? (
          <>
            {/* Sidebar — full-screen drawer on mobile */}
            {isMobile && showSidebar && (
              <div style={{
                position: 'absolute', inset: 0, zIndex: 20,
                background: '#0A0C0F',
                display: 'flex', flexDirection: 'column',
              }}>
                {/* Close button */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px', borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}>
                  <span style={{
                    fontFamily: "'Fraunces', Georgia, serif",
                    fontSize: 16, color: '#EDF0F4',
                  }}>{agent.agent_name}</span>
                  <div
                    onClick={() => setShowSidebar(false)}
                    style={{ cursor: 'pointer', color: 'rgba(237,240,244,0.62)', fontSize: 22, padding: '0 4px' }}
                  >&times;</div>
                </div>

                {/* Navigation links */}
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 2,
                  padding: '8px 12px', borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}>
                  {[
                    { icon: IconBot, label: 'Agents', action: () => { setShowSidebar(false); navigate('/'); } },
                    { icon: IconFunnel, label: 'CRM', action: () => { setShowSidebar(false); navigate('/crm'); } },
                    { icon: IconSettings, label: 'Settings', action: () => { setShowSidebar(false); /* trigger settings from AppShell */ document.dispatchEvent(new CustomEvent('chatty:open-settings')); } },
                  ].map(item => (
                    <div
                      key={item.label}
                      onClick={item.action}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '10px 8px', borderRadius: 4, cursor: 'pointer',
                        color: 'rgba(237,240,244,0.7)',
                      }}
                    >
                      <item.icon size={18} strokeWidth={1.85} />
                      <span style={{ fontSize: 14 }}>{item.label}</span>
                    </div>
                  ))}
                </div>

                {/* Agent actions */}
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 2,
                  padding: '8px 12px', borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}>
                  {agent.onboarding_complete && !agent.avatar_url && (
                    <div onClick={() => { setShowSidebar(false); setShowAvatarPicker(true); }}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 8px', borderRadius: 4, cursor: 'pointer', color: 'rgba(237,240,244,0.7)' }}>
                      <span style={{ fontSize: 14 }}>Set Avatar</span>
                    </div>
                  )}
                  <div onClick={() => { setShowSidebar(false); handleTogglePlanMode(); }}
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 8px', borderRadius: 4, cursor: 'pointer', color: chat.planMode ? '#D4A85A' : 'rgba(237,240,244,0.7)' }}>
                    <span style={{ fontSize: 14 }}>Plan Mode</span>
                    <span style={{ fontSize: 12, color: chat.planMode ? '#D4A85A' : 'rgba(237,240,244,0.38)' }}>{chat.planMode ? 'ON' : 'OFF'}</span>
                  </div>
                  {!chat.trainingMode && (
                    <div onClick={() => { setShowSidebar(false); if (agent.onboarding_complete) { handleStartImprove(); } else { handleStartOnboarding(); } }}
                      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 8px', borderRadius: 4, cursor: 'pointer', color: 'rgba(237,240,244,0.7)' }}>
                      <span style={{ fontSize: 14 }}>{trainLabel}</span>
                    </div>
                  )}
                </div>

                {/* Conversations list */}
                <div style={{ flex: 1, overflow: 'auto' }}>
                  <ConversationSidebar
                    agentName={agent.agent_name}
                    conversations={convs.conversations}
                    activeId={convs.activeId}
                    searchQuery={convs.searchQuery}
                    searchResults={convs.searchResults}
                    isSearching={convs.isSearching}
                    onNew={() => { handleNewChat(); setShowSidebar(false); }}
                    onSelect={(id) => { handleSelectConversation(id); setShowSidebar(false); }}
                    onDelete={handleDeleteConversation}
                    onSearch={convs.searchConversations}
                    onRename={convs.renameConversation}
                  />
                </div>
              </div>
            )}
            {!isMobile && (
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
            )}
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
          <div style={{ flex: 1, overflow: 'auto' }}>
            <AgentActivityPanel apiPrefix={apiPrefix} />
          </div>
        ) : (
          <div style={{ flex: 1, overflow: 'auto' }}>
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
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: '#11141A', border: '1px solid rgba(230,235,242,0.07)',
            borderRadius: 6, maxWidth: 512, width: '100%', margin: '0 16px',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}>
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
