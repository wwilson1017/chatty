/**
 * Chatty — Password auth context with optional TOTP 2FA.
 *
 * Single-user: authenticates with a password, gets back a JWT.
 * If 2FA is enabled, login() returns a pending token that must be
 * verified via verify2fa() before access is granted.
 *
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

export type LoginResult =
  | { success: true }
  | { requires2fa: true; pendingToken: string };

interface AuthContextType {
  isLoggedIn: boolean;
  loading: boolean;
  login: (password: string) => Promise<LoginResult>;
  verify2fa: (pendingToken: string, code: string, trustDevice?: boolean) => Promise<void>;
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

  const _completeLogin = useCallback((token: string) => {
    sessionStorage.setItem(TOKEN_KEY, token);
    setIsLoggedIn(true);
    try {
      const ch = new BroadcastChannel(CHANNEL_NAME);
      ch.postMessage({ type: 'login', token });
      ch.close();
    } catch { /* noop */ }
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

  const login = useCallback(async (password: string): Promise<LoginResult> => {
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

    if (data.requires_2fa) {
      return { requires2fa: true, pendingToken: data.pending_token };
    }

    _completeLogin(data.access_token);
    return { success: true };
  }, [_completeLogin]);

  const verify2fa = useCallback(async (pendingToken: string, code: string, trustDevice = false) => {
    const res = await fetch('/api/login/verify-2fa', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pending_token: pendingToken, code, trust_device: trustDevice }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || 'Verification failed');
    }
    const data = await res.json();
    _completeLogin(data.access_token);
  }, [_completeLogin]);

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
    <AuthContext.Provider value={{ isLoggedIn, loading, login, verify2fa, logout }}>
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

