import { useState, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { NavRail } from './NavRail';
import { ErrorBoundary, RouteErrorFallback } from './ErrorBoundary';
import { SettingsPanel } from '../dashboard/SettingsPanel';
import { useIsMobile } from './useIsMobile';
import { IconBot, IconFunnel, IconChart, IconBook, IconSettings, IconListCheck } from './icons';
import type { BrandingConfig } from '../core/types';

export function AppShell() {
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [activeNavKey, setActiveNavKey] = useState<string | null>(null);
  // null = unknown (loading). CRM nav stays hidden until confirmed enabled —
  // the right default now that new installs ship with CRM off. Seeded from
  // sessionStorage so enabled installs don't get a nav pop-in on every load;
  // MobileMenuDrawer reads the same key directly.
  const [crmEnabled, setCrmEnabled] = useState<boolean | null>(() => {
    const cached = sessionStorage.getItem('chatty_crm_enabled');
    return cached === null ? null : cached === '1';
  });
  const isMobile = useIsMobile();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const handler = () => setShowSettings(true);
    document.addEventListener('chatty:open-settings', handler);
    return () => document.removeEventListener('chatty:open-settings', handler);
  }, []);

  useEffect(() => {
    const fetchCrm = () => {
      api<{ integrations: { id: string; enabled: boolean }[] }>('/api/integrations')
        .then(data => {
          const enabled = data.integrations.find(i => i.id === 'crm_lite')?.enabled ?? false;
          setCrmEnabled(enabled);
          sessionStorage.setItem('chatty_crm_enabled', enabled ? '1' : '0');
        })
        .catch(() => setCrmEnabled(prev => prev ?? false));
    };
    fetchCrm();
    // IntegrationsTab dispatches this after any enable/disable toggle.
    document.addEventListener('chatty:integrations-changed', fetchCrm);
    return () => document.removeEventListener('chatty:integrations-changed', fetchCrm);
  }, []);

  useEffect(() => {
    api<BrandingConfig>('/api/branding').then(data => {
      setBranding(data);
      const OLD_DEFAULT = '#393c74';
      if (data.accent_color && data.accent_color.toLowerCase() !== OLD_DEFAULT) {
        document.documentElement.style.setProperty('--brand-color', data.accent_color);
      }
    }).catch(() => {}); // best-effort: default branding applies
  }, []);

  const userInitial = branding?.company_name?.charAt(0) || 'C';

  const mobileNavItems = [
    { key: 'agents', icon: IconBot, label: 'Agents', path: '/', match: (p: string) => p === '/' || p.startsWith('/agent/') },
    { key: 'todos', icon: IconListCheck, label: 'Todos', path: '/todos', match: (p: string) => p.startsWith('/todos') },
    ...(crmEnabled === true
      ? [{ key: 'crm', icon: IconFunnel, label: 'CRM', path: '/crm', match: (p: string) => p.startsWith('/crm') }]
      : []),
    { key: 'usage', icon: IconChart, label: 'Usage', path: '/usage', match: (p: string) => p.startsWith('/usage') },
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
    <div style={{
      display: 'flex', width: '100%', height: '100vh',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      overflow: 'hidden',
      flexDirection: isMobile ? 'column' : 'row',
    }}>
      {!isMobile && (
        <NavRail onSettingsClick={() => setShowSettings(true)} userInitial={userInitial} crmEnabled={crmEnabled === true} />
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
        {/* Keyed by route group so navigating away resets a crashed route
            while the nav rail (outside) survives. CRM and Todos each share
            one key: their nested tabs change the pathname, and a
            full-pathname key would remount the stateful layout on every tab
            switch (re-showing CRM's dismissed demo dialog, refetching Todo
            badge counts). Recovery from a crash inside either still works
            via the fallback's Back to Dashboard / Reload. */}
        <ErrorBoundary
          key={location.pathname.startsWith('/crm') ? '/crm'
            : location.pathname.startsWith('/todos') ? '/todos'
            : location.pathname}
          fallback={(error, reset) => <RouteErrorFallback error={error} reset={reset} />}
        >
          <Outlet context={{ branding, setBranding, crmEnabled }} />
        </ErrorBoundary>
      </div>

      {isMobile && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-around',
          height: 56, borderTop: '1px solid rgba(230,235,242,0.07)',
          background: '#0A0C0F', flexShrink: 0,
        }}>
          {mobileNavItems.map(item => {
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
  );
}
