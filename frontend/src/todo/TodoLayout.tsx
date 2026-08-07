import { useCallback, useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { todoApi } from './api';
import type { TodoFilters, TodoProject, TodoStatus } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { MobileMenuDrawer } from '../shared/MobileMenuDrawer';
import { ACCENT, FONT_DISPLAY, INK, INK_MUTE, INK_SOFT, LINE, LINE_STRONG, ACCENT_INK, inputStyle } from '../shared/styles';
import { QuickAdd } from './components/QuickAdd';
import { isTodoPublicMode, todoPath } from './publicMode';

export interface TodoOutletContext {
  counts: Record<TodoStatus, number>;
  contexts: string[];
  tags: string[];
  projects: TodoProject[];
  /** Refetch filters + projects. Call after every mutation so badges stay honest. */
  refreshMeta: () => void;
  /** Bumps when QuickAdd inserts — InboxPage watches this to refetch its list. */
  quickAddSeq: number;
}

const EMPTY_COUNTS: Record<TodoStatus, number> = {
  inbox: 0, next_action: 0, waiting_for: 0, delegated: 0,
  someday_maybe: 0, done: 0, dropped: 0,
};

const NAV_ITEMS = [
  { to: todoPath(), label: 'Inbox', end: true },
  { to: todoPath('/next'), label: 'To Do' },
  { to: todoPath('/projects'), label: 'Projects' },
  { to: todoPath('/waiting'), label: 'Waiting' },
  { to: todoPath('/someday'), label: 'Someday' },
  { to: todoPath('/done'), label: 'Done' },
  { to: todoPath('/review'), label: 'Review' },
  { to: todoPath('/search'), label: 'Contexts' },
];

export function TodoLayout() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const location = useLocation();
  const [showMenu, setShowMenu] = useState(false);
  const [filters, setFilters] = useState<TodoFilters | null>(null);
  const [projects, setProjects] = useState<TodoProject[]>([]);
  const [quickAddSeq, setQuickAddSeq] = useState(0);
  const [searchText, setSearchText] = useState('');

  const onSearchPage = location.pathname.startsWith(todoPath('/search'));
  // The inbox page carries its own capture box, under its filter bar — where
  // you're already looking when you're working the inbox. Everywhere else it
  // stays up here in the header.
  const trimSlash = (p: string) => p.replace(/\/+$/, '');
  const onInboxPage = trimSlash(location.pathname) === trimSlash(todoPath());

  // Keep the header box in sync with ?q= — covers deep links, Back/Forward,
  // and leaving the results page (urlQuery becomes ''). Typing is unaffected:
  // navigate() puts the same value in the URL, so the effect is a no-op.
  const urlQuery = onSearchPage ? new URLSearchParams(location.search).get('q') || '' : '';
  useEffect(() => { setSearchText(urlQuery); }, [urlQuery]);

  // Global search: typing anywhere drops straight into live results. The
  // keystroke that starts a search pushes one history entry (back returns
  // to wherever you were — a tab or the Contexts browse); refining or
  // clearing replaces, so history isn't one entry per character.
  const onSearchChange = (v: string) => {
    setSearchText(v);
    if (!v.trim() && !onSearchPage) return;
    const refining = onSearchPage && new URLSearchParams(location.search).has('q');
    navigate(
      v.trim() ? `${todoPath('/search')}?q=${encodeURIComponent(v)}` : todoPath('/search'),
      { replace: refining },
    );
  };

  const refreshMeta = useCallback(() => {
    todoApi<TodoFilters>('/api/todo/filters').then(setFilters).catch(() => {});
    todoApi<{ projects: TodoProject[] }>('/api/todo/projects').then(d => setProjects(d.projects)).catch(() => {});
  }, []);

  useEffect(() => { refreshMeta(); }, [refreshMeta]);

  const counts = filters?.status_counts || EMPTY_COUNTS;

  const inboxBadge = counts.inbox > 0 && (
    <span style={{
      marginLeft: 6, fontSize: 11, fontWeight: 600,
      background: ACCENT, color: ACCENT_INK,
      borderRadius: 8, padding: '1px 7px', verticalAlign: 'middle',
    }}>{counts.inbox}</span>
  );

  const navLinkStyle = (isActive: boolean, mobile: boolean): React.CSSProperties => ({
    fontSize: mobile ? 12 : 15, padding: mobile ? '8px 12px' : '6px 12px',
    whiteSpace: 'nowrap',
    color: isActive ? INK : INK_SOFT,
    borderBottom: isActive ? `2px solid ${ACCENT}` : '2px solid transparent',
    cursor: 'pointer', textDecoration: 'none',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ borderBottom: `1px solid ${LINE}` }}>
        {/* Row 1: Title + nav tabs (desktop) or hamburger (mobile) + QuickAdd (desktop) */}
        <div style={{
          height: 52, padding: isMobile ? '0 16px' : '0 28px',
          display: 'flex', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {isMobile && !isTodoPublicMode && (
              <div
                onClick={() => setShowMenu(!showMenu)}
                style={{ cursor: 'pointer', color: INK_MUTE, fontSize: 18 }}
              >&#9776;</div>
            )}
            <div style={{
              fontFamily: FONT_DISPLAY,
              fontSize: isMobile ? 20 : 18, letterSpacing: '-0.01em', color: INK,
            }}>Todos</div>
          </div>
          {!isMobile && (
            <>
              <div style={{ width: 1, height: 22, background: LINE_STRONG, margin: '0 20px' }} />
              <div style={{ display: 'flex', gap: 4, flex: 1 }}>
                {NAV_ITEMS.map(item => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    style={({ isActive }) => navLinkStyle(isActive, false)}
                  >
                    {item.label}
                    {item.label === 'Inbox' && inboxBadge}
                  </NavLink>
                ))}
              </div>
              <input
                value={searchText}
                onChange={e => onSearchChange(e.target.value)}
                placeholder="Search todos..."
                aria-label="Search todos"
                style={{ ...inputStyle, width: 200, padding: '7px 12px', fontSize: 14, marginRight: 8 }}
              />
              {!onInboxPage && (
                <QuickAdd isMobile={false} onAdded={() => { refreshMeta(); setQuickAddSeq(s => s + 1); }} />
              )}
            </>
          )}
        </div>

        {/* Row 2 (mobile): scrollable tabs */}
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
                style={({ isActive }) => navLinkStyle(isActive, true)}
              >
                {item.label}
                {item.label === 'Inbox' && inboxBadge}
              </NavLink>
            ))}
          </div>
        )}

        {/* Row 3 (mobile): QuickAdd + global search */}
        {isMobile && (
          <div style={{
            padding: '10px 16px', borderTop: '1px solid rgba(230,235,242,0.04)',
            display: 'flex', flexDirection: 'column', gap: 8,
          }}>
            <QuickAdd isMobile onAdded={() => { refreshMeta(); setQuickAddSeq(s => s + 1); }} />
            <input
              value={searchText}
              onChange={e => onSearchChange(e.target.value)}
              placeholder="Search todos..."
              aria-label="Search todos"
              style={{ ...inputStyle, padding: '7px 12px', fontSize: 14 }}
            />
          </div>
        )}
      </div>

      {isMobile && showMenu && !isTodoPublicMode && (
        <MobileMenuDrawer onClose={() => setShowMenu(false)} navigate={navigate} />
      )}

      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
        <Outlet context={{
          counts, contexts: filters?.contexts || [], tags: filters?.tags || [],
          projects, refreshMeta, quickAddSeq,
        } satisfies TodoOutletContext} />
      </div>
    </div>
  );
}
