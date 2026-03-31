import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../core/auth/AuthContext';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(password);
      navigate('/');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <img src="/chatty-logo.png" alt="Chatty" className="h-16 w-16 mx-auto mb-4 rounded-xl" />
          <h1 className="text-3xl font-bold text-white">Chatty</h1>
          <p className="text-gray-400 mt-2">Your personal AI agent platform</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-gray-900 rounded-2xl p-8 border border-gray-800 shadow-xl">
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-300 mb-2">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-3 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm mb-4">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="w-full bg-brand text-white font-semibold py-3 rounded-lg hover:opacity-90 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
