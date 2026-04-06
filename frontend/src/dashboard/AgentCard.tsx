import { useNavigate } from 'react-router-dom';
import type { Agent } from '../core/types';

interface Props {
  agent: Agent;
  onDelete: (id: string) => void;
}

export function AgentCard({ agent, onDelete }: Props) {
  const navigate = useNavigate();

  const initials = agent.agent_name
    .split(' ')
    .map(w => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="group relative bg-gray-900 border border-gray-800 rounded-2xl p-6 hover:border-indigo-500/50 hover:bg-gray-800/80 transition cursor-pointer"
      onClick={() => navigate(`/agent/${agent.id}`)}
    >
      {/* Delete button */}
      <button
        onClick={e => { e.stopPropagation(); onDelete(agent.id); }}
        className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition text-xl leading-none"
        title="Delete agent"
      >
        ×
      </button>

      {/* Avatar */}
      <div className="w-14 h-14 rounded-xl bg-brand flex items-center justify-center text-white font-bold text-xl mb-4">
        {agent.avatar_url
          ? <img src={`${agent.avatar_url}${agent.avatar_url.includes('?') ? '&' : '?'}token=${localStorage.getItem('chatty_token') || ''}`} alt={agent.agent_name} className="w-full h-full object-cover rounded-xl" />
          : initials
        }
      </div>

      <h3 className="text-white font-semibold text-lg mb-1">{agent.agent_name}</h3>

      <div className="flex items-center gap-2 mt-3">
        <span className={`text-xs px-2 py-0.5 rounded-full ${agent.onboarding_complete ? 'bg-green-900/50 text-green-400' : 'bg-yellow-900/50 text-yellow-400'}`}>
          {agent.onboarding_complete ? 'Ready' : 'Onboarding'}
        </span>
        {agent.gmail_enabled && <span className="text-xs text-gray-500">📧</span>}
        {agent.calendar_enabled && <span className="text-xs text-gray-500">📅</span>}
      </div>
    </div>
  );
}
