import { useState, useEffect, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../core/auth/AuthContext';
import { IconWordmark } from '../shared/icons';
import { WarmHalo } from '../shared/WarmHalo';
import { AgentMark } from '../shared/AgentMark';
import { useIsMobile } from '../shared/useIsMobile';

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

  const isMobile = useIsMobile();
  const [activeAgent, setActiveAgent] = useState(0);

  const agents = [
    { letter: 'C', name: 'Clara' },
    { letter: 'H', name: 'Harper' },
    { letter: 'A', name: 'Arlo' },
    { letter: 'T', name: 'Tessa' },
    { letter: 'T', name: 'Tobias' },
    { letter: 'Y', name: 'Yuri' },
  ];

  useEffect(() => {
    const id = setInterval(() => setActiveAgent(i => (i + 1) % 6), 2000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{
      width: '100%', height: '100vh',
      background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      display: 'flex', flexDirection: isMobile ? 'column' : 'row',
      overflow: 'hidden', position: 'relative',
    }}>
      <WarmHalo opacity={0.7} />

      {/* Left marketing panel — hidden on mobile */}
      {!isMobile && (
        <div style={{
          flex: 1.1, borderRight: '1px solid rgba(230,235,242,0.07)',
          padding: '52px 56px', display: 'flex', flexDirection: 'column',
          justifyContent: 'flex-end', gap: 40,
          paddingBottom: 80, position: 'relative', zIndex: 2,
        }}>
          <div>
            <div style={{ color: 'var(--color-ch-accent, #C8D1D9)', marginBottom: 28 }}>
              <IconWordmark height={56} color="currentColor" />
            </div>
            <h1 style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: 54, fontWeight: 400, letterSpacing: '-0.025em',
              lineHeight: 1.1, margin: 0,
            }}>
              Hire a team of agents,<br />not just a&nbsp;chatbot.
            </h1>
            <p style={{
              fontSize: 16, color: 'rgba(237,240,244,0.52)',
              marginTop: 20, maxWidth: 420, lineHeight: 1.6,
            }}>
              Commission a personal assistant, an AP clerk, a sales rep.
              They learn your business, handle the tedious work, and stay quietly at their desks.
            </p>
          </div>

          <div style={{ display: 'flex', gap: 12 }}>
            {agents.map((agent, i) => (
              <div key={i} style={{ position: 'relative' }}>
                <AgentMark letter={agent.letter} size={36} />
                <div style={{
                  position: 'absolute',
                  bottom: 'calc(100% + 8px)',
                  left: '50%',
                  transform: activeAgent === i ? 'translateX(-50%) translateY(0)' : 'translateX(-50%) translateY(4px)',
                  background: '#1a1f27',
                  color: '#EDF0F4',
                  fontFamily: "'Inter Tight', system-ui, sans-serif",
                  fontSize: 12, fontWeight: 500,
                  padding: '5px 10px', borderRadius: 6,
                  whiteSpace: 'nowrap',
                  border: '1px solid rgba(230, 235, 242, 0.1)',
                  opacity: activeAgent === i ? 1 : 0,
                  transition: 'opacity 0.3s, transform 0.3s',
                  pointerEvents: 'none',
                }}>
                  {agent.name}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Login form — full screen on mobile */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column',
        padding: isMobile ? '0 28px' : 40,
        position: 'relative', zIndex: 2,
      }}>
        {/* Branding for mobile */}
        {isMobile && (
          <div style={{ marginBottom: 40, color: 'var(--color-ch-accent, #C8D1D9)', width: '100%', display: 'flex', justifyContent: 'center' }}>
            <IconWordmark height={88} color="currentColor" style={{ maxWidth: '80vw' }} />
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ maxWidth: 360, width: '100%' }}>
          <div style={mono(10, 'rgba(237,240,244,0.38)')}>Sign in</div>
          <h2 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: isMobile ? 30 : 36, fontWeight: 400, letterSpacing: '-0.02em',
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
                borderRadius: 4, padding: '12px 14px',
                background: 'rgba(20,24,30,0.78)',
                fontSize: 16, color: '#EDF0F4',
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
              padding: '13px 16px', borderRadius: 4, cursor: 'pointer',
              opacity: (loading || !password) ? 0.5 : 1,
            }}
          >
            {loading ? 'Signing in...' : 'Continue'}
          </button>
        </form>

        {/* CHATTY letter marks for mobile — auto-cycles tooltips */}
        {isMobile && (
          <div style={{ display: 'flex', gap: 10, marginTop: 48 }}>
            {agents.map((agent, i) => (
              <div key={i} style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <AgentMark letter={agent.letter} size={32} />
                <div style={{
                  position: 'absolute',
                  top: 'calc(100% + 8px)',
                  background: '#1a1f27',
                  color: '#EDF0F4',
                  fontFamily: "'Inter Tight', system-ui, sans-serif",
                  fontSize: 11, fontWeight: 500,
                  padding: '4px 8px', borderRadius: 5,
                  whiteSpace: 'nowrap',
                  border: '1px solid rgba(230, 235, 242, 0.1)',
                  opacity: activeAgent === i ? 1 : 0,
                  transform: activeAgent === i ? 'translateY(0)' : 'translateY(-4px)',
                  transition: 'opacity 0.3s, transform 0.3s',
                }}>
                  {agent.name}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
