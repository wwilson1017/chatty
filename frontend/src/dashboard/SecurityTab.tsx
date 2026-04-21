import { useState, useEffect, useRef } from 'react';
import { api } from '../core/api/client';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

interface TwoFAStatus {
  enabled: boolean;
  has_backup_codes: boolean;
  backup_code_count: number;
  trusted_device_count: number;
}

interface SetupResponse {
  secret: string;
  qr_code_data_uri: string;
  provisioning_uri: string;
}

type State = 'loading' | 'disabled' | 'showing-qr' | 'show-backup-codes' | 'enabled' | 'disabling' | 'regenerating';

export function SecurityTab() {
  const [state, setState] = useState<State>('loading');
  const [status, setStatus] = useState<TwoFAStatus | null>(null);
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [verifyCode, setVerifyCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);

  async function loadStatus() {
    try {
      const s = await api<TwoFAStatus>('/api/auth/2fa/status');
      setStatus(s);
      setState(s.enabled ? 'enabled' : 'disabled');
    } catch {
      setState('disabled');
    }
  }

  useEffect(() => { loadStatus(); }, []);

  async function startSetup() {
    setError('');
    setSaving(true);
    try {
      const resp = await api<SetupResponse>('/api/auth/2fa/setup', { method: 'POST' });
      setSetup(resp);
      setState('showing-qr');
      setTimeout(() => codeRef.current?.focus(), 100);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Setup failed');
    } finally {
      setSaving(false);
    }
  }

  async function confirmSetup() {
    if (!setup) return;
    setError('');
    setSaving(true);
    try {
      const resp = await api<{ enabled: boolean; backup_codes: string[] }>('/api/auth/2fa/verify-setup', {
        method: 'POST',
        body: JSON.stringify({ secret: setup.secret, code: verifyCode, password }),
      });
      setBackupCodes(resp.backup_codes);
      setPassword('');
      setState('show-backup-codes');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Invalid code');
    } finally {
      setSaving(false);
    }
  }

  async function disable2fa() {
    setError('');
    setSaving(true);
    try {
      await api('/api/auth/2fa/disable', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      setPassword('');
      setState('disabled');
      setStatus(null);
      loadStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to disable');
    } finally {
      setSaving(false);
    }
  }

  async function regenerateCodes() {
    setError('');
    setSaving(true);
    try {
      const resp = await api<{ backup_codes: string[] }>('/api/auth/2fa/backup-codes/regenerate', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      setBackupCodes(resp.backup_codes);
      setPassword('');
      setState('show-backup-codes');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to regenerate');
    } finally {
      setSaving(false);
    }
  }

  function copyBackupCodes() {
    navigator.clipboard.writeText(backupCodes.join('\n')).catch(() => {});
  }

  function downloadBackupCodes() {
    const text = `Chatty — Backup Codes\n${'='.repeat(30)}\n\nStore these codes in a safe place.\nEach code can only be used once.\n\n${backupCodes.map((c, i) => `${i + 1}. ${c}`).join('\n')}\n`;
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'chatty-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box' as const,
    background: 'rgba(20,24,30,0.78)',
    border: '1px solid rgba(230,235,242,0.14)',
    color: '#EDF0F4', borderRadius: 4,
    padding: '10px 14px', fontSize: 14, outline: 'none',
  };

  const btnPrimary = {
    width: '100%', padding: '10px 16px',
    background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
    border: 'none', borderRadius: 4, fontSize: 14, fontWeight: 500,
    cursor: 'pointer', opacity: saving ? 0.5 : 1,
  };

  const btnDanger = {
    ...btnPrimary,
    background: '#D97757',
  };

  if (state === 'loading') {
    return <p style={{ color: 'rgba(237,240,244,0.52)', fontSize: 14 }}>Loading...</p>;
  }

  // ── Disabled state ──────────────────────────────────────────────────────
  if (state === 'disabled') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <p style={{ fontSize: 14, color: '#EDF0F4', margin: '0 0 8px' }}>Two-factor authentication</p>
          <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.52)', margin: 0, lineHeight: 1.6 }}>
            Add an extra layer of security to your account. You'll need an authenticator app
            like Google Authenticator, Authy, or 1Password.
          </p>
        </div>
        {error && <p style={{ color: '#D97757', fontSize: 13, margin: 0 }}>{error}</p>}
        <button onClick={startSetup} disabled={saving} style={btnPrimary}>
          {saving ? 'Setting up...' : 'Enable two-factor authentication'}
        </button>
      </div>
    );
  }

  // ── QR code setup ───────────────────────────────────────────────────────
  if (state === 'showing-qr' && setup) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <p style={{ fontSize: 14, color: '#EDF0F4', margin: '0 0 8px' }}>Scan QR code</p>
          <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.52)', margin: 0, lineHeight: 1.6 }}>
            Scan this QR code with your authenticator app, then enter the 6-digit code to confirm.
          </p>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
          <img
            src={setup.qr_code_data_uri}
            alt="2FA QR Code"
            style={{ borderRadius: 8, background: '#fff', padding: 8 }}
          />
        </div>

        <div>
          <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Manual entry key</label>
          <div style={{
            ...inputStyle,
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            fontSize: 13, letterSpacing: '0.08em', wordBreak: 'break-all',
            userSelect: 'all', cursor: 'text',
          }}>
            {setup.secret}
          </div>
        </div>

        <div>
          <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Verification code</label>
          <input
            ref={codeRef}
            type="text"
            inputMode="numeric"
            value={verifyCode}
            onChange={e => setVerifyCode(e.target.value)}
            placeholder="000000"
            maxLength={6}
            autoComplete="one-time-code"
            style={{
              ...inputStyle,
              fontSize: 20, letterSpacing: '0.2em', textAlign: 'center',
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            }}
          />
        </div>

        <div>
          <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Confirm password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter your password"
            style={inputStyle}
          />
        </div>

        {error && <p style={{ color: '#D97757', fontSize: 13, margin: 0 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={() => { setState('disabled'); setSetup(null); setVerifyCode(''); setPassword(''); setError(''); }}
            style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}
          >
            Cancel
          </button>
          <button
            onClick={confirmSetup}
            disabled={saving || verifyCode.length < 6 || !password}
            style={{ ...btnPrimary, opacity: saving || verifyCode.length < 6 || !password ? 0.5 : 1 }}
          >
            {saving ? 'Verifying...' : 'Verify & Enable'}
          </button>
        </div>
      </div>
    );
  }

  // ── Backup codes display ────────────────────────────────────────────────
  if (state === 'show-backup-codes') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <p style={{ fontSize: 14, color: '#EDF0F4', margin: '0 0 8px' }}>Save your backup codes</p>
          <p style={{ fontSize: 13, color: '#D97757', margin: 0, lineHeight: 1.6 }}>
            Save these codes in a safe place. Each code can only be used once.
            If you lose access to your authenticator app, these are the only way to log in.
          </p>
        </div>

        <div style={{
          background: 'rgba(20,24,30,0.78)',
          border: '1px solid rgba(230,235,242,0.14)',
          borderRadius: 8, padding: 20,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 24px',
        }}>
          {backupCodes.map((code, i) => (
            <div key={i} style={{
              fontFamily: "'JetBrains Mono', ui-monospace, monospace",
              fontSize: 14, color: '#EDF0F4', letterSpacing: '0.08em',
            }}>
              {code}
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <button onClick={copyBackupCodes} style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}>
            Copy all
          </button>
          <button onClick={downloadBackupCodes} style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}>
            Download .txt
          </button>
        </div>

        <button onClick={() => { loadStatus(); setBackupCodes([]); }} style={btnPrimary}>
          I've saved my codes
        </button>
      </div>
    );
  }

  // ── Enabled state ───────────────────────────────────────────────────────
  if (state === 'enabled') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>Two-factor authentication</p>
            <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>
              {status?.backup_code_count ?? 0} backup codes remaining
              {status?.trusted_device_count ? ` · ${status.trusted_device_count} trusted device${status.trusted_device_count > 1 ? 's' : ''}` : ''}
            </p>
          </div>
          <div style={{
            fontSize: 11, fontWeight: 600,
            padding: '4px 10px', borderRadius: 12,
            background: 'rgba(76,175,80,0.15)', color: '#66BB6A',
            fontFamily: "'Inter Tight', system-ui, sans-serif",
          }}>
            Enabled
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <button
            onClick={() => setState('regenerating')}
            style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}
          >
            Regenerate backup codes
          </button>
          <button
            onClick={() => setState('disabling')}
            style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#D97757' }}
          >
            Disable two-factor authentication
          </button>
        </div>
      </div>
    );
  }

  // ── Disable confirmation ────────────────────────────────────────────────
  if (state === 'disabling') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <p style={{ fontSize: 14, color: '#EDF0F4', margin: '0 0 8px' }}>Disable two-factor authentication</p>
          <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.52)', margin: 0, lineHeight: 1.6 }}>
            Enter your password to confirm. This will also revoke all trusted devices.
          </p>
        </div>

        <div>
          <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter your password"
            autoFocus
            style={inputStyle}
          />
        </div>

        {error && <p style={{ color: '#D97757', fontSize: 13, margin: 0 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={() => { setState('enabled'); setPassword(''); setError(''); }}
            style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}
          >
            Cancel
          </button>
          <button onClick={disable2fa} disabled={saving || !password} style={{ ...btnDanger, opacity: saving || !password ? 0.5 : 1 }}>
            {saving ? 'Disabling...' : 'Disable 2FA'}
          </button>
        </div>
      </div>
    );
  }

  // ── Regenerate backup codes ─────────────────────────────────────────────
  if (state === 'regenerating') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div>
          <p style={{ fontSize: 14, color: '#EDF0F4', margin: '0 0 8px' }}>Regenerate backup codes</p>
          <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.52)', margin: 0, lineHeight: 1.6 }}>
            This will replace your existing backup codes. Enter your password to confirm.
          </p>
        </div>

        <div>
          <label style={{ ...mono(9), display: 'block', marginBottom: 6 }}>Password</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter your password"
            autoFocus
            style={inputStyle}
          />
        </div>

        {error && <p style={{ color: '#D97757', fontSize: 13, margin: 0 }}>{error}</p>}

        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={() => { setState('enabled'); setPassword(''); setError(''); }}
            style={{ ...btnPrimary, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: '#EDF0F4' }}
          >
            Cancel
          </button>
          <button onClick={regenerateCodes} disabled={saving || !password} style={{ ...btnPrimary, opacity: saving || !password ? 0.5 : 1 }}>
            {saving ? 'Regenerating...' : 'Regenerate codes'}
          </button>
        </div>
      </div>
    );
  }

  return null;
}
