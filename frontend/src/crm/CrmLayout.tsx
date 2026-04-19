import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useIsMobile } from '../shared/useIsMobile';
import { MobileMenuDrawer } from '../shared/MobileMenuDrawer';

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
        borderBottom: '1px solid rgba(230,235,242,0.07)',
      }}>
        {/* Row 1: Title + nav tabs (desktop) or hamburger (mobile) */}
        <div style={{
          height: 48, padding: isMobile ? '0 16px' : '0 28px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {isMobile && (
              <div
                onClick={() => setShowMenu(!showMenu)}
                style={{ cursor: 'pointer', color: 'rgba(237,240,244,0.62)', fontSize: 18 }}
              >&#9776;</div>
            )}
            <div style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: isMobile ? 20 : 16, letterSpacing: '-0.01em', color: '#EDF0F4',
            }}>CRM</div>
          </div>
          {!isMobile && (
            <div style={{ display: 'flex', gap: 2 }}>
              {NAV_ITEMS.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  style={({ isActive }) => ({
                    fontSize: 12, padding: '4px 12px',
                    color: isActive ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                    borderBottom: isActive ? '1px solid var(--color-ch-accent, #C8D1D9)' : '1px solid transparent',
                    cursor: 'pointer', textDecoration: 'none',
                  })}
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
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
                  color: isActive ? '#EDF0F4' : 'rgba(237,240,244,0.5)',
                  borderBottom: isActive ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
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
