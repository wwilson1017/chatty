import { useState, useEffect, useCallback } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';
import { useIsMobile } from '../shared/useIsMobile';
import { MobileMenuDrawer } from '../shared/MobileMenuDrawer';
import { INK, INK_SOFT, INK_MUTE, LINE, LINE_STRONG, ACCENT, FONT_DISPLAY, FONT_SANS, FONT_MONO, SAGE, GOLD } from '../shared/styles';
import { modalOverlay, modalContent, btnPrimary, btnSecondary } from './styles';

const NAV_ITEMS = [
  { to: '/crm', label: 'Dashboard', end: true },
  { to: '/crm/contacts', label: 'Contacts' },
  { to: '/crm/pipeline', label: 'Pipeline' },
  { to: '/crm/tasks', label: 'Tasks' },
];

function DemoDialog({ onClear, onDismiss }: {
  onClear: () => Promise<void>; onDismiss: (wasCleared: boolean) => void;
}) {
  const [clearing, setClearing] = useState(false);
  const [cleared, setCleared] = useState(false);
  const isMobile = useIsMobile();

  async function handleClear() {
    setClearing(true);
    try {
      await onClear();
      setCleared(true);
    } catch {
      // stays on prompt screen so user can retry
    } finally {
      setClearing(false);
    }
  }

  return (
    <div style={modalOverlay(isMobile)}>
      <div style={modalContent(isMobile, 480)} onClick={e => e.stopPropagation()}>
        {!cleared ? (
          <>
            <h2 style={{
              fontFamily: FONT_DISPLAY, fontSize: 22, fontWeight: 400,
              letterSpacing: '-0.02em', color: INK, margin: '0 0 12px',
            }}>This CRM has example data</h2>
            <p style={{
              fontFamily: FONT_SANS, fontSize: 14, color: INK_MUTE,
              lineHeight: 1.6, margin: 0,
            }}>
              We added sample contacts, deals, and tasks so you can see how
              everything works. Would you like to clear it and start fresh?
            </p>
            <div style={{ display: 'flex', gap: 12, marginTop: 24, justifyContent: 'flex-end' }}>
              <button onClick={() => onDismiss(false)} style={btnSecondary}>Keep exploring</button>
              <button
                onClick={handleClear}
                disabled={clearing}
                style={{ ...btnPrimary, opacity: clearing ? 0.6 : 1, cursor: clearing ? 'wait' : 'pointer' }}
              >{clearing ? 'Clearing...' : 'Clear example data'}</button>
            </div>
          </>
        ) : (
          <>
            <div style={{
              width: 40, height: 40, borderRadius: '50%',
              background: 'rgba(142,165,137,0.12)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: 16, color: SAGE, fontSize: 20,
            }}>&#10003;</div>
            <h2 style={{
              fontFamily: FONT_DISPLAY, fontSize: 22, fontWeight: 400,
              letterSpacing: '-0.02em', color: INK, margin: '0 0 8px',
            }}>You're all set</h2>
            <p style={{
              fontFamily: FONT_SANS, fontSize: 14, color: INK_MUTE,
              lineHeight: 1.6, margin: 0,
            }}>Example data cleared. Your CRM is ready to use.</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
              <button onClick={() => onDismiss(true)} style={btnPrimary}>Get started</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function CrmLayout() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [demoMode, setDemoMode] = useState<boolean | null>(null);
  const [dialogDismissed, setDialogDismissed] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api<{ demo_mode: boolean }>('/api/crm/demo-status').then(r => setDemoMode(r.demo_mode)).catch(() => setDemoMode(false));
  }, []);

  const handleClearDemo = useCallback(async () => {
    try {
      await api('/api/crm/demo-clear', { method: 'POST' });
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error('Failed to clear demo data:', err);
      throw err;
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
            {demoMode && dialogDismissed && (
              <button
                onClick={() => setDialogDismissed(false)}
                style={{
                  background: 'rgba(212,168,90,0.10)', color: GOLD,
                  border: '1px solid rgba(212,168,90,0.20)', borderRadius: 4,
                  padding: '2px 8px', fontSize: 10, fontFamily: FONT_MONO,
                  letterSpacing: '0.08em', textTransform: 'uppercase',
                  cursor: 'pointer',
                }}
              >Example data</button>
            )}
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

      {demoMode && !dialogDismissed && (
        <DemoDialog
          onClear={handleClearDemo}
          onDismiss={(wasCleared) => {
            setDialogDismissed(true);
            if (wasCleared) setDemoMode(false);
          }}
        />
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
