import { useState, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { NavRail } from './NavRail';
import { SettingsPanel } from '../dashboard/SettingsPanel';
import { useIsMobile } from './useIsMobile';
import { IconBot, IconFunnel, IconBook, IconSettings } from './icons';
import { CrmVisibilityProvider } from './CrmVisibilityContext';
import type { BrandingConfig, Integration } from '../core/types';

export function AppShell() {
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [activeNavKey, setActiveNavKey] = useState<string | null>(null);
  const [crmHidden, setCrmHidden] = useState(false);
  const isMobile = useIsMobile();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const handler = () => setShowSettings(true);
    document.addEventListener('chatty:open-settings', handler);
    return () => document.removeEventListener('chatty:open-settings', handler);
  }, []);

  useEffect(() => {
    api<BrandingConfig>('/api/branding').then(data => {
      setBranding(data);
      const OLD_DEFAULT = '#393c74';
      if (data.accent_color && data.accent_color.toLowerCase() !== OLD_DEFAULT) {
        document.documentElement.style.setProperty('--brand-color', data.accent_color);
      }
    }).catch(() => {});
    api<{ integrations: Integration[] }>('/api/integrations').then(data => {
      const crm = data.integrations.find(i => i.id === 'crm_lite');
      setCrmHidden(!!crm?.hidden);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const handler = () => {
      api<{ integrations: Integration[] }>('/api/integrations').then(data => {
        const crm = data.integrations.find(i => i.id === 'crm_lite');
        setCrmHidden(!!crm?.hidden);
      }).catch(() => {});
    };
    document.addEventListener('chatty:integrations-changed', handler);
    return () => document.removeEventListener('chatty:integrations-changed', handler);
  }, []);

  const userInitial = branding?.company_name?.charAt(0) || 'C';

  const mobileNavItems = [
    { key: 'agents', icon: IconBot, label: 'Agents', path: '/', match: (p: string) => p === '/' || p.startsWith('/agent/') },
    { key: 'crm', icon: IconFunnel, label: 'CRM', path: '/crm', match: (p: string) => p.startsWith('/crm') },
    { key: 'knowledge', icon: IconBook, label: 'Knowledge', path: null as string | null, match: () => false },
    { key: 'settings', icon: IconSettings, label: 'Settings', path: null as string | null, match: () => false },
  ];

  function handleMobileNav(item: typeof mobileNavItems[0]) {
    if (item.key === 'settings') {
      setShowSettings(true);
    } else if (item.key === 'knowledge') {
      setActiveNavKey('knowledge');
      const lastAgent = localStorage.getItem('chatty_last_agent');
      navigate(lastAgent ? `/agent/${lastAgent}?tab=knowledge` : '/');
    } else if (item.path) {
      setActiveNavKey(null);
      navigate(item.path);
    }
  }

  return (
    <CrmVisibilityProvider value={crmHidden}>
    <div style={{
      display: 'flex', width: '100%', height: '100vh',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      overflow: 'hidden',
      flexDirection: isMobile ? 'column' : 'row',
    }}>
      {!isMobile && (
        <NavRail onSettingsClick={() => setShowSettings(true)} userInitial={userInitial} />
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
        <Outlet context={{ branding, setBranding }} />
      </div>

      {isMobile && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-around',
          height: 56, borderTop: '1px solid rgba(230,235,242,0.07)',
          background: '#0A0C0F', flexShrink: 0,
        }}>
          {mobileNavItems.filter(item => !(item.key === 'crm' && crmHidden)).map(item => {
            const active = activeNavKey === item.key || (!activeNavKey && item.match(location.pathname));
            const Icon = item.icon;
            return (
              <div
                key={item.key}
                onClick={() => handleMobileNav(item)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                  color: active ? '#EDF0F4' : 'rgba(237,240,244,0.5)',
                  cursor: 'pointer', padding: '6px 12px',
                }}
              >
                <Icon size={20} strokeWidth={1.85} />
                <span style={{ fontSize: 10, letterSpacing: '0.04em' }}>{item.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {showSettings && (
        <SettingsPanel
          branding={branding}
          onBrandingUpdate={setBranding}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
    </CrmVisibilityProvider>
  );
}
