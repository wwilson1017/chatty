import { useState, useEffect, useCallback } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { useIsMobile } from '../shared/useIsMobile';
import { MobileMenuDrawer } from '../shared/MobileMenuDrawer';
import { INK, INK_SOFT, INK_MUTE, LINE, LINE_STRONG, ACCENT, FONT_DISPLAY } from '../shared/styles';

const NAV_ITEMS = [
  { to: '/crm', label: 'Dashboard', end: true },
  { to: '/crm/contacts', label: 'Contacts' },
  { to: '/crm/pipeline', label: 'Pipeline' },
  { to: '/crm/tasks', label: 'Tasks' },
];

function DemoBanner({ onClear, clearing, isMobile }: {
  onClear: () => void; clearing: boolean; isMobile: boolean;
}) {
  const [hoverBtn, setHoverBtn] = useState(false);
  return (
    <div style={{
      padding: isMobile ? '14px 16px' : '14px 28px',
      background: 'rgba(212, 168, 90, 0.06)',
      borderLeft: '2px solid #D4A85A',
      display: 'flex', alignItems: isMobile ? 'flex-start' : 'center',
      flexDirection: isMobile ? 'column' : 'row',
      gap: isMobile ? 12 : 20,
      justifyContent: 'space-between',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, color: '#EDF0F4', fontFamily: "'Inter Tight', system-ui, sans-serif",
        }}>You're viewing example data</div>
        <div style={{
          fontSize: 12, color: 'rgba(237,240,244,0.5)', marginTop: 2,
          fontFamily: "'Inter Tight', system-ui, sans-serif",
        }}>Explore the CRM, then start fresh when you're ready.</div>
      </div>
      <button
        onClick={onClear}
        disabled={clearing}
        onMouseEnter={() => setHoverBtn(true)}
        onMouseLeave={() => setHoverBtn(false)}
        style={{
          background: hoverBtn && !clearing ? '#c9a04e' : '#D4A85A',
          color: '#11141A', border: 'none', borderRadius: 4,
          padding: '7px 16px', fontSize: 13, fontWeight: 600, cursor: clearing ? 'wait' : 'pointer',
          fontFamily: "'Inter Tight', system-ui, sans-serif",
          whiteSpace: 'nowrap', opacity: clearing ? 0.6 : 1,
          flexShrink: 0,
        }}
      >{clearing ? 'Clearing...' : 'Start using CRM'}</button>
    </div>
  );
}

export function CrmLayout() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [demoMode, setDemoMode] = useState<boolean | null>(null);
  const [clearing, setClearing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api<{ demo_mode: boolean }>('/api/crm/demo-status').then(r => setDemoMode(r.demo_mode)).catch(() => setDemoMode(false));
  }, []);

  const handleClearDemo = useCallback(async () => {
    setClearing(true);
    try {
      await api('/api/crm/demo-clear', { method: 'POST' });
      setDemoMode(false);
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error('Failed to clear demo data:', err);
    } finally {
      setClearing(false);
    }
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{
        borderBottom: `1px solid ${LINE}`,
      }}>
        {/* Row 1: Title + nav tabs (desktop) or hamburger (mobile) */}
        <div style={{
          height: 52, padding: isMobile ? '0 16px' : '0 28px',
          display: 'flex', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {isMobile && (
              <div
                onClick={() => setShowMenu(!showMenu)}
                style={{ cursor: 'pointer', color: INK_MUTE, fontSize: 18 }}
              >&#9776;</div>
            )}
            <div style={{
              fontFamily: FONT_DISPLAY,
              fontSize: isMobile ? 20 : 18, letterSpacing: '-0.01em', color: INK,
            }}>CRM</div>
          </div>
          {!isMobile && (
            <>
              <div style={{
                width: 1, height: 22, background: LINE_STRONG,
                margin: '0 20px',
              }} />
              <div style={{ display: 'flex', gap: 4 }}>
                {NAV_ITEMS.map(item => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    style={({ isActive }) => ({
                      fontSize: 15, padding: '6px 14px',
                      color: isActive ? INK : INK_SOFT,
                      borderBottom: isActive ? `2px solid ${ACCENT}` : '2px solid transparent',
                      cursor: 'pointer', textDecoration: 'none',
                    })}
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Row 2: Tabs (mobile only) */}
        {isMobile && (
          <div style={{
            display: 'flex', overflowX: 'auto', padding: '0 16px',
            borderTop: '1px solid rgba(230,235,242,0.04)',
            WebkitOverflowScrolling: 'touch',
          }}>
            {NAV_ITEMS.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                style={({ isActive }) => ({
                  fontSize: 12, padding: '8px 14px', whiteSpace: 'nowrap',
                  color: isActive ? INK : INK_SOFT,
                  borderBottom: isActive ? `2px solid ${ACCENT}` : '2px solid transparent',
                  cursor: 'pointer', textDecoration: 'none',
                })}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        )}
      </div>

      {demoMode && (
        <DemoBanner onClear={handleClearDemo} clearing={clearing} isMobile={isMobile} />
      )}

      {isMobile && showMenu && (
        <MobileMenuDrawer onClose={() => setShowMenu(false)} navigate={navigate} />
      )}

      <div key={refreshKey} style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        <Outlet />
      </div>
    </div>
  );
}
