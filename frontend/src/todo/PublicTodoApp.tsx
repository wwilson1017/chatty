import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ToastViewport } from '../shared/ToastViewport';
import { ConfirmHost } from '../shared/ConfirmHost';
import { ErrorBoundary, RouteErrorFallback } from '../shared/ErrorBoundary';
import { TodoLayout } from './TodoLayout';
import { InboxPage } from './InboxPage';
import { NextActionsPage } from './NextActionsPage';
import { ProjectsPage } from './ProjectsPage';
import { ProjectDetailPage } from './ProjectDetailPage';
import { WaitingPage } from './WaitingPage';
import { SomedayPage } from './SomedayPage';
import { DonePage } from './DonePage';
import { ReviewPage } from './ReviewPage';
import { SearchPage } from './SearchPage';
import { TODO_PUBLIC_BASE } from './publicMode';

/**
 * The todo app on its own, with no login and no dashboard around it —
 * served at /todo or /todo/{token} (see backend core/todo/web.py).
 *
 * Same pages as the dashboard's /todos section: the router basename makes
 * the URLs hang off the public root, and todoPath()/todoApi() follow it.
 */
export function PublicTodoApp() {
  // The shell is Chatty's index.html; on this page the bookmark should read
  // as the todo list, not the app it happens to be served from.
  useEffect(() => { document.title = 'Todos'; }, []);

  return (
    <div style={{
      width: '100%', height: '100vh', overflow: 'hidden',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
    }}>
      <BrowserRouter basename={TODO_PUBLIC_BASE ?? undefined}>
        <ErrorBoundary fallback={(error, reset) => <RouteErrorFallback error={error} reset={reset} homeLabel="Back to Todos" />}>
          <Routes>
            <Route path="/" element={<TodoLayout />}>
              <Route index element={<InboxPage />} />
              <Route path="next" element={<NextActionsPage />} />
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="projects/:id" element={<ProjectDetailPage />} />
              <Route path="waiting" element={<WaitingPage />} />
              <Route path="someday" element={<SomedayPage />} />
              <Route path="done" element={<DonePage />} />
              <Route path="review" element={<ReviewPage />} />
              <Route path="search" element={<SearchPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ErrorBoundary>
        <ConfirmHost />
        <ToastViewport />
      </BrowserRouter>
    </div>
  );
}
