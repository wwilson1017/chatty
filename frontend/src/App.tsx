import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './core/auth/AuthContext';
import { ToastViewport } from './shared/ToastViewport';
import { ConfirmHost } from './shared/ConfirmHost';
import { ProtectedRoute } from './core/auth/ProtectedRoute';
import { AppShell } from './shared/AppShell';
import { LoginPage } from './login/LoginPage';
import { DashboardPage } from './dashboard/DashboardPage';
import { OnboardingPage } from './onboarding/OnboardingPage';
import { AgentPage } from './agent/AgentPage';
import { WebbyPage } from './webby/WebbyPage';
import { UsagePage } from './usage/UsagePage';
import { CrmLayout } from './crm/CrmLayout';
import { CrmDashboardPage } from './crm/CrmDashboardPage';
import { ContactsPage } from './crm/ContactsPage';
import { ContactDetailPage } from './crm/ContactDetailPage';
import { PipelinePage } from './crm/PipelinePage';
import { TasksPage } from './crm/TasksPage';
import { TodoLayout } from './todo/TodoLayout';
import { InboxPage } from './todo/InboxPage';
import { NextActionsPage } from './todo/NextActionsPage';
import { ProjectsPage } from './todo/ProjectsPage';
import { ProjectDetailPage } from './todo/ProjectDetailPage';
import { WaitingPage } from './todo/WaitingPage';
import { SomedayPage } from './todo/SomedayPage';
import { DonePage } from './todo/DonePage';
import { ReviewPage } from './todo/ReviewPage';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            path="/setup"
            element={
              <ProtectedRoute>
                <OnboardingPage />
              </ProtectedRoute>
            }
          />

          <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/agent/:id" element={<AgentPage />} />
            <Route path="/crm" element={<CrmLayout />}>
              <Route index element={<CrmDashboardPage />} />
              <Route path="contacts" element={<ContactsPage />} />
              <Route path="contacts/:id" element={<ContactDetailPage />} />
              <Route path="pipeline" element={<PipelinePage />} />
              <Route path="tasks" element={<TasksPage />} />
            </Route>
            <Route path="/todos" element={<TodoLayout />}>
              <Route index element={<InboxPage />} />
              <Route path="next" element={<NextActionsPage />} />
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="projects/:id" element={<ProjectDetailPage />} />
              <Route path="waiting" element={<WaitingPage />} />
              <Route path="someday" element={<SomedayPage />} />
              <Route path="done" element={<DonePage />} />
              <Route path="review" element={<ReviewPage />} />
            </Route>
            <Route path="/usage" element={<UsagePage />} />
            <Route path="/webby" element={<WebbyPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <ConfirmHost />
        <ToastViewport />
      </BrowserRouter>
    </AuthProvider>
  );
}
