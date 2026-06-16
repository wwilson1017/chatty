/**
 * Chatty — set up authentication for an installed CLI.
 *
 * Paste is the always-available path (api_key / bearer / PAT): values are
 * encrypted at rest and injected as env vars when the CLI runs. CLIs that
 * support device-code login also get a "Connect" panel (the CLI owns its token).
 */

import { useEffect, useState } from 'react';
import { api } from '../core/api/client';
import { useDeviceFlow } from '../core/hooks/useDeviceFlow';

interface EnvVar { name: string; description: string; sensitive: boolean }
interface AuthInfo {
  auth_type: string | null;
  env_vars: EnvVar[];
  key_url: string;
  has_credentials: boolean;
  supports_device: boolean;
}

interface Props {
  slug: string;
  apiName: string;
  onClose: () => void;
  onSaved: () => void;
}

const ink = 'var(--color-ch-ink, #EDF0F4)';
const inkSoft = 'rgba(237,240,244,0.50)';
const inkDim = 'rgba(237,240,244,0.38)';
const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '8px 12px', fontSize: 13, borderRadius: 5,
  background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)', color: ink, marginTop: 4,
};

export function CliAuthModal({ slug, apiName, onClose, onSaved }: Props) {
  const [info, setInfo] = useState<AuthInfo | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const device = useDeviceFlow(slug);

  useEffect(() => {
    api<AuthInfo>(`/api/printing-press/${slug}/auth`)
      .then(setInfo)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load auth info'));
  }, [slug]);

  useEffect(() => {
    if (device.status === 'authorized') onSaved();
  }, [device.status, onSaved]);

  async function savePaste() {
    setSaving(true);
    setError(null);
    try {
      await api(`/api/printing-press/${slug}/auth`, { method: 'POST', body: JSON.stringify({ env: values }) });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save credentials');
    } finally {
      setSaving(false);
    }
  }

  const canSave = info?.env_vars.some((v) => (values[v.name] ?? '').trim());

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--color-ch-bg-elev, #11141A)', borderRadius: 8, border: '1px solid rgba(230,235,242,0.14)', width: 'min(460px, 92vw)', padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ color: ink, fontSize: 15, fontWeight: 600, margin: 0 }}>Connect {apiName}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: inkSoft, fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>×</button>
        </div>

        {error && <p style={{ color: '#D97757', fontSize: 12 }}>{error}</p>}
        {!info && !error && <p style={{ color: inkSoft, fontSize: 13 }}>Loading…</p>}

        {info && (
          <>
            {info.key_url && (
              <p style={{ fontSize: 12, color: inkSoft, marginTop: 0 }}>
                Need a key? <a href={info.key_url} target="_blank" rel="noreferrer" style={{ color: 'var(--color-ch-accent, #C8D1D9)' }}>Get one here →</a>
              </p>
            )}

            {info.env_vars.map((v) => (
              <label key={v.name} style={{ display: 'block', marginBottom: 10 }}>
                <span style={{ color: inkDim, fontSize: 11 }}>{v.name}</span>
                {v.description && <span style={{ color: inkDim, fontSize: 11, display: 'block' }}>{v.description}</span>}
                <input
                  type={v.sensitive ? 'password' : 'text'}
                  value={values[v.name] ?? ''}
                  onChange={(e) => setValues((p) => ({ ...p, [v.name]: e.target.value }))}
                  style={inputStyle}
                  autoComplete="off"
                />
              </label>
            ))}

            {info.env_vars.length > 0 && (
              <button
                onClick={savePaste}
                disabled={saving || !canSave}
                style={{ width: '100%', padding: '9px 16px', fontSize: 13, borderRadius: 5, background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013', border: 'none', cursor: saving || !canSave ? 'default' : 'pointer', fontWeight: 500, opacity: saving || !canSave ? 0.5 : 1 }}
              >
                {saving ? 'Saving…' : info.has_credentials ? 'Update credentials' : 'Save credentials'}
              </button>
            )}

            {info.supports_device && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
                {device.status === 'idle' && (
                  <button onClick={device.start} style={{ width: '100%', padding: '9px 16px', fontSize: 13, borderRadius: 5, background: 'transparent', color: ink, border: '1px solid rgba(230,235,242,0.14)', cursor: 'pointer' }}>
                    Connect with device login
                  </button>
                )}
                {device.status === 'pending' && device.flow && (
                  <div style={{ textAlign: 'center' }}>
                    <p style={{ color: inkSoft, fontSize: 12, margin: 0 }}>Go to</p>
                    <a href={device.flow.verification_uri} target="_blank" rel="noreferrer" style={{ color: 'var(--color-ch-accent, #C8D1D9)', fontSize: 13 }}>{device.flow.verification_uri}</a>
                    <p style={{ color: inkSoft, fontSize: 12, margin: '8px 0 2px' }}>and enter code</p>
                    <div style={{ color: ink, fontSize: 22, fontWeight: 700, letterSpacing: 2, fontFamily: 'monospace' }}>{device.flow.user_code}</div>
                    <p style={{ color: inkDim, fontSize: 11, marginTop: 8 }}>Waiting for authorization…</p>
                  </div>
                )}
                {device.status === 'error' && <p style={{ color: '#D97757', fontSize: 12 }}>{device.error || 'Device login failed.'}</p>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
