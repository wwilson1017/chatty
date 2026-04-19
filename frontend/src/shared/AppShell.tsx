import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { api } from '../core/api/client';
import { NavRail } from './NavRail';
import { SettingsPanel } from '../dashboard/SettingsPanel';
import type { BrandingConfig } from '../core/types';

export function AppShell() {
  const [branding, setBranding] = useState<BrandingConfig | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  useEffect(() => {
    api<BrandingConfig>('/api/branding').then(data => {
      setBranding(data);
      const OLD_DEFAULT = '#393c74';
      if (data.accent_color && data.accent_color.toLowerCase() !== OLD_DEFAULT) {
        document.documentElement.style.setProperty('--brand-color', data.accent_color);
      }
    }).catch(() => {});
  }, []);

  const userInitial = branding?.company_name?.charAt(0) || 'C';

  return (
    <div style={{
      display: 'flex', width: '100%', height: '100vh',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      overflow: 'hidden',
    }}>
      <NavRail onSettingsClick={() => setShowSettings(true)} userInitial={userInitial} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
        <Outlet context={{ branding, setBranding }} />
      </div>

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
