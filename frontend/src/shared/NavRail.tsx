import { useLocation, useNavigate } from 'react-router-dom';
import { IconLogo, IconBot, IconUsers, IconBook, IconSettings } from './icons';

interface NavRailProps {
  onSettingsClick: () => void;
  userInitial?: string;
}

const navItems = [
  { key: 'agents', icon: IconBot, path: '/', match: (p: string) => p === '/' || p.startsWith('/agent/') },
  { key: 'crm', icon: IconUsers, path: '/crm', match: (p: string) => p.startsWith('/crm') },
  { key: 'knowledge', icon: IconBook, path: null as string | null, match: () => false },
];

export function NavRail({ onSettingsClick, userInitial = 'U' }: NavRailProps) {
  const location = useLocation();
  const navigate = useNavigate();

  function handleKnowledgeClick() {
    const lastAgent = localStorage.getItem('chatty_last_agent');
    if (lastAgent) {
      navigate(`/agent/${lastAgent}?tab=knowledge`);
    } else {
      navigate('/');
    }
  }

  return (
    <div style={{
      width: 60, borderRight: '1px solid rgba(230,235,242,0.07)',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '16px 0', position: 'relative', zIndex: 2,
    }}>
      <div style={{ color: 'var(--color-ch-accent, #C8D1D9)', cursor: 'pointer' }} onClick={() => navigate('/')}>
        <IconLogo size={26} />
      </div>
      <div style={{ width: 24, height: 1, background: 'rgba(230,235,242,0.07)', margin: '16px 0' }} />

      {navItems.map(item => {
        const active = item.match(location.pathname);
        const Icon = item.icon;
        return (
          <div
            key={item.key}
            onClick={() => item.key === 'knowledge' ? handleKnowledgeClick() : item.path && navigate(item.path)}
            style={{
              padding: '10px 11px',
              color: active ? '#EDF0F4' : 'rgba(237,240,244,0.78)',
              background: active ? 'rgba(200,209,217,0.12)' : 'transparent',
              borderRadius: 4,
              marginBottom: 4,
              borderLeft: active ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
              marginLeft: active ? -2 : 0,
              cursor: 'pointer',
            }}
          >
            <Icon size={18} strokeWidth={1.85} />
          </div>
        );
      })}

      <div style={{ flex: 1 }} />

      <div
        onClick={onSettingsClick}
        style={{ color: 'rgba(237,240,244,0.78)', marginBottom: 12, cursor: 'pointer' }}
      >
        <IconSettings size={18} strokeWidth={1.85} />
      </div>

      <div style={{
        width: 28, height: 28, borderRadius: 4,
        background: 'var(--color-ch-accent, #C8D1D9)',
        color: '#0E1013',
        fontFamily: "'Fraunces', Georgia, serif",
        fontSize: 14, fontWeight: 500,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {userInitial.charAt(0).toUpperCase()}
      </div>
    </div>
  );
}
