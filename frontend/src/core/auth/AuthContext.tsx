/**
 * Chatty — Password auth context.
 *
 * Single-user: authenticates with a password, gets back a JWT.
 * JWT stored in sessionStorage (cleared on browser close).
 * BroadcastChannel syncs login/logout across tabs.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import { TOKEN_KEY } from './tokenUtils';

const CHANNEL_NAME = 'chatty_auth';

// One-time migration: move token from localStorage to sessionStorage
function migrateToken() {
  const old = localStorage.getItem(TOKEN_KEY);
  if (old) {
    sessionStorage.setItem(TOKEN_KEY, old);
    localStorage.removeItem(TOKEN_KEY);
  }
}

interface AuthContextType {
  isLoggedIn: boolean;
  loading: boolean;
  login: (password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);

  const validateToken = useCallback(async (token: string): Promise<boolean> => {
    try {
      const res = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${token}` },
      });
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    migrateToken();

    async function init() {
      const token = sessionStorage.getItem(TOKEN_KEY);
      if (token) {
        const valid = await validateToken(token);
        setIsLoggedIn(valid);
        if (!valid) sessionStorage.removeItem(TOKEN_KEY);
      }
      setLoading(false);
    }
    init();

    // Cross-tab sync via BroadcastChannel
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel(CHANNEL_NAME);
      channel.onmessage = async (e: MessageEvent) => {
        if (e.data?.type === 'login' && e.data.token) {
          const valid = await validateToken(e.data.token);
          if (!valid) return;
          sessionStorage.setItem(TOKEN_KEY, e.data.token);
          setIsLoggedIn(true);
        } else if (e.data?.type === 'logout') {
          sessionStorage.removeItem(TOKEN_KEY);
          setIsLoggedIn(false);
        }
      };
    } catch {
      // BroadcastChannel not supported — single-tab fallback
    }

    return () => { channel?.close(); };
  }, [validateToken]);

  const login = useCallback(async (password: string) => {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || 'Login failed');
    }
    const data = await res.json();
    sessionStorage.setItem(TOKEN_KEY, data.access_token);
    setIsLoggedIn(true);

    // Notify other tabs
    try {
      const ch = new BroadcastChannel(CHANNEL_NAME);
      ch.postMessage({ type: 'login', token: data.access_token });
      ch.close();
    } catch { /* noop */ }
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    setIsLoggedIn(false);

    // Notify other tabs
    try {
      const ch = new BroadcastChannel(CHANNEL_NAME);
      ch.postMessage({ type: 'logout' });
      ch.close();
    } catch { /* noop */ }
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

