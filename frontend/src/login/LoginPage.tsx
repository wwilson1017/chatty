import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../core/auth/AuthContext';
import { IconWordmark } from '../shared/icons';
import { WarmHalo } from '../shared/WarmHalo';
import { AgentMark } from '../shared/AgentMark';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

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
    <div style={{
      width: '100%', height: '100vh',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      display: 'flex', overflow: 'hidden', position: 'relative',
    }}>
      <WarmHalo opacity={0.7} />

      {/* Left marketing panel */}
      <div style={{
        flex: 1.1, borderRight: '1px solid rgba(230,235,242,0.07)',
        padding: '44px 48px', display: 'flex', flexDirection: 'column',
        justifyContent: 'space-between', position: 'relative', zIndex: 2,
      }}>
        <div style={{ color: 'var(--color-ch-accent, #C8D1D9)' }}>
          <IconWordmark height={26} color="currentColor" />
        </div>

        <div>
          <div style={mono(10, 'rgba(237,240,244,0.38)')}>AI Agents for small business</div>
          <h1 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 60, fontWeight: 400, letterSpacing: '-0.028em',
            lineHeight: 1.02, margin: '16px 0 0',
          }}>
            Hire a team<br />of <span style={{ fontStyle: 'italic', color: '#D4A85A' }}>agents</span>,
            <br />not just <span style={{ color: 'rgba(237,240,244,0.62)' }}>a chatbot.</span>
          </h1>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 18, fontStyle: 'italic',
            color: 'rgba(237,240,244,0.62)', marginTop: 22,
            maxWidth: 440, lineHeight: 1.5,
          }}>
            Commission a personal assistant, an AP clerk, a sales rep.
            They learn your business, handle the tedious work, and stay quietly at their desks.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          {['C', 'H', 'A', 'T', 'T', 'Y'].map((l, i) => (
            <AgentMark key={i} letter={l} size={36} />
          ))}
        </div>
      </div>

      {/* Right login form */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 40, position: 'relative', zIndex: 2,
      }}>
        <form onSubmit={handleSubmit} style={{ maxWidth: 360, width: '100%' }}>
          <div style={mono(10, 'rgba(237,240,244,0.38)')}>Sign in</div>
          <h2 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 36, fontWeight: 400, letterSpacing: '-0.02em',
            lineHeight: 1.05, margin: '10px 0 24px',
          }}>Welcome back.</h2>

          <div style={{ marginBottom: 22 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={mono(9, 'rgba(237,240,244,0.38)')}>Password</div>
            </div>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoFocus
              style={{
                width: '100%', boxSizing: 'border-box',
                border: '1px solid rgba(230,235,242,0.14)',
                borderRadius: 4, padding: '10px 14px',
                background: 'rgba(20,24,30,0.78)',
                fontSize: 14, color: '#EDF0F4',
                outline: 'none',
                fontFamily: "'Inter Tight', system-ui, sans-serif",
              }}
              onFocus={e => { e.target.style.borderColor = 'var(--color-ch-accent, #C8D1D9)'; }}
              onBlur={e => { e.target.style.borderColor = 'rgba(230,235,242,0.14)'; }}
            />
          </div>

          {error && (
            <p style={{ color: '#D97757', fontSize: 13, marginBottom: 16 }}>{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            style={{
              width: '100%',
              background: 'var(--color-ch-accent, #C8D1D9)',
              color: '#0E1013',
              border: 'none', fontSize: 14, fontWeight: 500,
              padding: '11px 16px', borderRadius: 4, cursor: 'pointer',
              opacity: (loading || !password) ? 0.5 : 1,
            }}
          >
            {loading ? 'Signing in...' : 'Continue'}
          </button>
        </form>
      </div>
    </div>
  );
}
