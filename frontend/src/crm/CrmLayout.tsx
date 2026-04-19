import { NavLink, Outlet } from 'react-router-dom';

const NAV_ITEMS = [
  { to: '/crm', label: 'Dashboard', end: true },
  { to: '/crm/contacts', label: 'Contacts' },
  { to: '/crm/pipeline', label: 'Pipeline' },
  { to: '/crm/tasks', label: 'Tasks' },
];

export function CrmLayout() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{
        height: 48, borderBottom: '1px solid rgba(230,235,242,0.07)',
        padding: '0 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 16, letterSpacing: '-0.01em', color: '#EDF0F4',
          }}>CRM</div>
          <div style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase' as const,
            color: 'rgba(237,240,244,0.38)',
          }}>/ Pipeline</div>
        </div>
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
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        <Outlet />
      </div>
    </div>
  );
}
