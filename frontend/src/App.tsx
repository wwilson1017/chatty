/**
 * Chatty — App shell.
 * Routes: /login → / (dashboard) → /agent/:id → /crm/*
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './core/auth/AuthContext';
import { ProtectedRoute } from './core/auth/ProtectedRoute';
import { LoginPage } from './login/LoginPage';
import { DashboardPage } from './dashboard/DashboardPage';
import { AgentPage } from './agent/AgentPage';
import { WebbyPage } from './webby/WebbyPage';
import { SetupWizard } from './setup/SetupWizard';
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
                <SetupWizard />
              </ProtectedRoute>
            }
          />

          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/agent/:id"
            element={
              <ProtectedRoute>
                <AgentPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/crm"
            element={
              <ProtectedRoute>
                <CrmLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<CrmDashboardPage />} />
            <Route path="contacts" element={<ContactsPage />} />
            <Route path="contacts/:id" element={<ContactDetailPage />} />
            <Route path="pipeline" element={<PipelinePage />} />
            <Route path="tasks" element={<TasksPage />} />
          </Route>

          <Route
            path="/webby"
            element={
              <ProtectedRoute>
                <WebbyPage />
              </ProtectedRoute>
            }
          />

          {/* Catch-all → dashboard */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
