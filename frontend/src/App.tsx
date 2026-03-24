/**
 * Chatty — App shell.
 * Routes: /login → / (dashboard) → /agent/:id
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './core/auth/AuthContext';
import { ProtectedRoute } from './core/auth/ProtectedRoute';
import { LoginPage } from './login/LoginPage';
import { DashboardPage } from './dashboard/DashboardPage';
import { AgentPage } from './agent/AgentPage';
import { WebbyPage } from './webby/WebbyPage';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

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
