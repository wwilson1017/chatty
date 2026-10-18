/**
 * Chatty — Protected route guard.
 * Redirects unauthenticated users to /login, remembering where they were
 * headed so a deep link (e.g. a Telegram link to /computer) lands after login.
 */

import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isLoggedIn, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ch-bg">
        <div className="w-8 h-8 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!isLoggedIn) {
    // Remember where we were going (e.g. a `chatty login` QR's /?pair=<code>) for after login.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
