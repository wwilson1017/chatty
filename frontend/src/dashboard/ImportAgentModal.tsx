import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../core/api/client';

interface Props {
  onClose: () => void;
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
  color: 'rgba(237,240,244,0.38)', marginBottom: 6,
};

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  background: 'rgba(20,24,30,0.78)',
  border: '1px solid rgba(230,235,242,0.14)',
  color: '#EDF0F4', borderRadius: 4,
  padding: '10px 14px', fontSize: 14,
  outline: 'none',
  fontFamily: "'Inter Tight', system-ui, sans-serif",
};

export function ImportAgentModal({ onClose }: Props) {
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setLoading(true);
    setError('');
    try {
      const result = await api<{
        agent_id: string;
        agent_slug: string;
        conversation_id: string;
        session_token: string;
      }>('/api/agents/import/start', {
        method: 'POST',
        body: JSON.stringify({ agent_name: name.trim() }),
      });
      navigate(`/agent/${result.agent_id}?conversation=${result.conversation_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start import');
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#11141A', borderRadius: 6,
          border: '1px solid rgba(230,235,242,0.14)',
          padding: 32, width: '100%', maxWidth: 420,
          boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <h2 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 24, fontWeight: 400, letterSpacing: '-0.02em',
          marginBottom: 8, color: '#EDF0F4',
        }}>Import Existing Agent</h2>

        <p style={{
          fontSize: 13, color: 'rgba(237,240,244,0.5)',
          marginBottom: 24, lineHeight: 1.5,
        }}>
          Bring knowledge from another AI system into a new Chatty agent.
          Your agent will walk you through the import.
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 24 }}>
            <label style={labelStyle}>Agent name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Name for your new agent"
              autoFocus
              maxLength={60}
              style={inputStyle}
            />
            <p style={{
              fontSize: 11, color: 'rgba(237,240,244,0.28)', marginTop: 4,
            }}>You can change this during import if you're cloning an existing agent.</p>
          </div>

          {error && <p style={{ color: '#D97757', fontSize: 13, marginBottom: 16 }}>{error}</p>}

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                flex: 1, padding: '9px 16px', borderRadius: 4,
                border: '1px solid rgba(230,235,242,0.14)',
                background: 'transparent', color: 'rgba(237,240,244,0.62)',
                cursor: 'pointer', fontSize: 13,
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !name.trim()}
              style={{
                flex: 1, padding: '9px 16px', borderRadius: 4,
                background: '#D4A85A', color: '#0E1013',
                border: 'none', fontWeight: 500, cursor: 'pointer', fontSize: 13,
                opacity: (loading || !name.trim()) ? 0.5 : 1,
              }}
            >
              {loading ? 'Starting...' : 'Start Import'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
