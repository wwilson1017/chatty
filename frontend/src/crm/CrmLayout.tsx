import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useIsMobile } from '../shared/useIsMobile';
import { MobileMenuDrawer } from '../shared/MobileMenuDrawer';
import { INK, INK_SOFT, INK_MUTE, LINE, LINE_STRONG, ACCENT, FONT_DISPLAY } from '../shared/styles';

const NAV_ITEMS = [
  { to: '/crm', label: 'Dashboard', end: true },
  { to: '/crm/contacts', label: 'Contacts' },
  { to: '/crm/pipeline', label: 'Pipeline' },
  { to: '/crm/tasks', label: 'Tasks' },
];

export function CrmLayout() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);

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

      {isMobile && showMenu && (
        <MobileMenuDrawer onClose={() => setShowMenu(false)} navigate={navigate} />
      )}

      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        <Outlet />
      </div>
    </div>
  );
}
