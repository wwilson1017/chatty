import { useNavigate } from 'react-router-dom';
import { AgentMark } from '../shared/AgentMark';
import { StatusDot } from '../shared/StatusDot';
import type { Agent } from '../core/types';

interface Props {
  agent: Agent;
}

export function AgentCard({ agent }: Props) {
  const navigate = useNavigate();
  const letter = agent.agent_name.charAt(0);
  const avatarUrl = agent.avatar_url
    ? `${agent.avatar_url}${agent.avatar_url.includes('?') ? '&' : '?'}token=${sessionStorage.getItem('chatty_token') || ''}`
    : undefined;

  const capabilities = [
    agent.gmail_enabled && 'Email',
    agent.calendar_enabled && 'Calendar',
  ].filter(Boolean);

  return (
    <div
      style={{
        background: 'rgba(20,24,30,0.78)',
        border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 6, padding: '12px 14px',
        display: 'flex', gap: 12, alignItems: 'center',
        cursor: 'pointer', position: 'relative',
      }}
      onClick={() => navigate(`/agent/${agent.id}`)}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(230,235,242,0.14)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(230,235,242,0.07)'; }}
    >
      <AgentMark letter={letter} size={34} avatarUrl={avatarUrl} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 17, letterSpacing: '-0.015em', lineHeight: 1.1,
            color: '#EDF0F4',
          }}>
            {agent.agent_name}
          </div>
          <StatusDot status="idle" showLabel={false} />
        </div>
        {capabilities.length > 0 && (
          <div style={{
            fontSize: 11, color: 'rgba(237,240,244,0.38)', marginTop: 2,
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            letterSpacing: '0.1em', textTransform: 'uppercase',
          }}>
            {capabilities.join(' · ')}
          </div>
        )}
      </div>

    </div>
  );
}
