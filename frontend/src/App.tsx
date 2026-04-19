import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './core/auth/AuthContext';
import { ProtectedRoute } from './core/auth/ProtectedRoute';
import { AppShell } from './shared/AppShell';
import { LoginPage } from './login/LoginPage';
import { DashboardPage } from './dashboard/DashboardPage';
import { OnboardingPage } from './onboarding/OnboardingPage';
import { AgentPage } from './agent/AgentPage';
import { WebbyPage } from './webby/WebbyPage';
import { CrmLayout } from './crm/CrmLayout';
import { CrmDashboardPage } from './crm/CrmDashboardPage';
import { ContactsPage } from './crm/ContactsPage';
import { ContactDetailPage } from './crm/ContactDetailPage';
import { PipelinePage } from './crm/PipelinePage';
import { TasksPage } from './crm/TasksPage';

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
            <Route path="/webby" element={<WebbyPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
