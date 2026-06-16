/**
 * Chatty — "Printing Press" integrations subsection.
 *
 * Lists installed CLIs (build status, auth status) with manage actions, and
 * opens the library catalog to install more. Installing a CLI gives every agent
 * its commands automatically (Chatty's global-integration convention).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../core/api/client';
import { CliCatalogModal } from './CliCatalogModal';
import { CliAuthModal } from './CliAuthModal';

interface InstalledCli {
  slug: string;
  category: string;
  api_name: string;
  description: string;
  tool_count: number;
  enabled: boolean;
  tool_mode: string;
  build_status: string;
  build_error: string | null;
  auth_type: string | null;
  needs_auth: boolean;
}

const ink = 'var(--color-ch-ink, #EDF0F4)';
const inkSoft = 'rgba(237,240,244,0.50)';
const inkDim = 'rgba(237,240,244,0.38)';

function StatusBadge({ cli }: { cli: InstalledCli }) {
  if (cli.build_status === 'building' || cli.build_status === 'pending') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: inkSoft }}>
        <span style={{ width: 10, height: 10, border: '2px solid var(--color-ch-accent, #C8D1D9)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
        Building…
      </span>
    );
  }
  if (cli.build_status === 'error') {
    return <span title={cli.build_error ?? ''} style={{ fontSize: 11, color: '#D97757', background: 'rgba(217,119,87,0.08)', padding: '2px 8px', borderRadius: 4 }}>Build failed</span>;
  }
  if (cli.needs_auth) {
    return <span style={{ fontSize: 11, color: '#D9A757', background: 'rgba(217,167,87,0.1)', padding: '2px 8px', borderRadius: 4 }}>Needs auth</span>;
  }
  return <span style={{ fontSize: 11, color: '#8EA589', background: 'rgba(142,165,137,0.1)', padding: '2px 8px', borderRadius: 4 }}>Ready</span>;
}

export function PrintingPressSection() {
  const [installed, setInstalled] = useState<InstalledCli[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showCatalog, setShowCatalog] = useState(false);
  const [authCli, setAuthCli] = useState<InstalledCli | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await api<{ installed: InstalledCli[] }>('/api/printing-press/installed');
      setInstalled(d.installed);
    } catch {
      /* leave previous list */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Poll while any install is still building (e.g. page reloaded mid-build).
  useEffect(() => {
    const building = installed.some((c) => c.build_status === 'building' || c.build_status === 'pending');
    if (building && !pollRef.current) {
      pollRef.current = setInterval(refresh, 2000);
    } else if (!building && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [installed, refresh]);

  async function setMode(slug: string, mode: string) {
    await api(`/api/printing-press/${slug}/mode`, { method: 'POST', body: JSON.stringify({ tool_mode: mode }) });
    refresh();
  }
  async function toggle(cli: InstalledCli) {
    await api(`/api/printing-press/${cli.slug}/${cli.enabled ? 'disable' : 'enable'}`, { method: 'POST' });
    refresh();
  }
  async function uninstall(slug: string) {
    if (!window.confirm(`Uninstall ${slug}? This removes its commands from all agents.`)) return;
    await api(`/api/printing-press/${slug}`, { method: 'DELETE' });
    refresh();
  }

  const installedSlugs = new Set(installed.map((c) => c.slug));

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div>
          <h3 style={{ color: ink, fontSize: 14, fontWeight: 600, margin: 0 }}>Printing Press</h3>
          <p style={{ color: inkDim, fontSize: 12, margin: '2px 0 0' }}>Install ready-made API CLIs — your agents can use them right away.</p>
        </div>
        <button
          onClick={() => setShowCatalog(true)}
          style={{ padding: '6px 14px', fontSize: 12, borderRadius: 5, fontWeight: 500, background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013', border: 'none', cursor: 'pointer' }}
        >
          Browse library
        </button>
      </div>

      {loaded && installed.length === 0 && (
        <div style={{ background: 'rgba(20,24,30,0.78)', borderRadius: 6, padding: 16, border: '1px dashed rgba(230,235,242,0.14)' }}>
          <p style={{ color: inkSoft, fontSize: 13, margin: 0 }}>No CLIs installed yet. Browse the library to add one.</p>
        </div>
      )}

      {installed.map((cli) => (
        <div key={cli.slug} style={{ background: 'rgba(20,24,30,0.78)', borderRadius: 6, padding: 14, marginBottom: 8, border: '1px solid rgba(230,235,242,0.07)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ color: ink, fontSize: 14, fontWeight: 600 }}>{cli.api_name}</span>
                <span style={{ color: inkDim, fontSize: 11 }}>{cli.tool_count} commands</span>
                <StatusBadge cli={cli} />
              </div>
              <p style={{ color: inkSoft, fontSize: 12, margin: '4px 0 0', lineHeight: 1.45 }}>{cli.description}</p>
            </div>
            <button
              onClick={() => toggle(cli)}
              disabled={cli.build_status !== 'ready'}
              title={cli.enabled ? 'Disable' : 'Enable'}
              style={{ flexShrink: 0, position: 'relative', width: 44, height: 24, borderRadius: 12, border: 'none', cursor: cli.build_status === 'ready' ? 'pointer' : 'default', background: cli.enabled && cli.build_status === 'ready' ? '#8EA589' : 'rgba(230,235,242,0.14)', opacity: cli.build_status === 'ready' ? 1 : 0.5 }}
            >
              <span style={{ position: 'absolute', top: 3, left: cli.enabled ? 23 : 3, width: 18, height: 18, borderRadius: '50%', background: '#fff', transition: 'left 0.15s' }} />
            </button>
          </div>

          {cli.build_status === 'ready' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
              <label style={{ color: inkDim, fontSize: 11 }}>
                Permission:{' '}
                <select
                  value={cli.tool_mode}
                  onChange={(e) => setMode(cli.slug, e.target.value)}
                  style={{ background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)', color: ink, fontSize: 11, borderRadius: 4, padding: '2px 4px' }}
                >
                  <option value="read-only">Read-only</option>
                  <option value="normal">Confirm writes</option>
                  <option value="power">Auto-run writes</option>
                </select>
              </label>
              {cli.auth_type && cli.auth_type !== 'none' && (
                <button onClick={() => setAuthCli(cli)} style={{ background: 'none', border: 'none', color: cli.needs_auth ? '#D9A757' : 'var(--color-ch-accent, #C8D1D9)', fontSize: 11, cursor: 'pointer', padding: 0 }}>
                  {cli.needs_auth ? 'Set up auth' : 'Re-connect'}
                </button>
              )}
              <button onClick={() => uninstall(cli.slug)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: inkDim, fontSize: 11, cursor: 'pointer', padding: 0 }}>Uninstall</button>
            </div>
          )}
          {cli.build_status === 'error' && (
            <div style={{ display: 'flex', gap: 12, marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
              <span style={{ color: '#D97757', fontSize: 11 }}>{cli.build_error?.split('\n')[0] ?? 'Build failed'}</span>
              <button onClick={() => uninstall(cli.slug)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: inkDim, fontSize: 11, cursor: 'pointer', padding: 0 }}>Remove</button>
            </div>
          )}
        </div>
      ))}

      {showCatalog && (
        <CliCatalogModal
          installedSlugs={installedSlugs}
          onClose={() => { setShowCatalog(false); refresh(); }}
          onInstalled={refresh}
        />
      )}

      {authCli && (
        <CliAuthModal
          slug={authCli.slug}
          apiName={authCli.api_name}
          onClose={() => setAuthCli(null)}
          onSaved={() => { setAuthCli(null); refresh(); }}
        />
      )}
    </div>
  );
}
