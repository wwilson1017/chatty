/**
 * Chatty — browse the Printing Press public library and install a CLI.
 *
 * Lists the catalog, filters client-side, and installs one CLI at a time
 * (builds are serialized on the backend), streaming live build progress.
 */

import { useEffect, useMemo, useState } from 'react';
import { api } from '../core/api/client';
import { useBuildStream } from '../core/hooks/useBuildStream';

interface CatalogEntry {
  slug: string;
  category: string;
  api: string;
  description: string;
  tool_count: number | null;
  auth_type: string | null;
  env_vars: string[];
}

interface Props {
  installedSlugs: Set<string>;
  onClose: () => void;
  onInstalled: () => void;
}

const panel: React.CSSProperties = {
  background: 'var(--color-ch-bg-elev, #11141A)', borderRadius: 8,
  border: '1px solid rgba(230,235,242,0.14)', width: 'min(720px, 92vw)',
  maxHeight: '86vh', display: 'flex', flexDirection: 'column',
};
const ink = 'var(--color-ch-ink, #EDF0F4)';
const inkSoft = 'rgba(237,240,244,0.50)';
const inkDim = 'rgba(237,240,244,0.38)';

export function CliCatalogModal({ installedSlugs, onClose, onInstalled }: Props) {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [installing, setInstalling] = useState<string | null>(null);
  const { logs, status, error: buildError, start, reset } = useBuildStream();

  useEffect(() => {
    api<{ entries: CatalogEntry[] }>('/api/printing-press/catalog')
      .then((d) => setEntries(d.entries))
      .catch((e) => setLoadError(e instanceof Error ? e.message : 'Failed to load library'))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) =>
      [e.api, e.description, e.category, e.slug].some((f) => f?.toLowerCase().includes(q)),
    );
  }, [entries, query]);

  async function install(entry: CatalogEntry) {
    if (installing) return;
    setInstalling(entry.slug);
    reset();
    try {
      const { build_id } = await api<{ build_id: string }>('/api/printing-press/install', {
        method: 'POST',
        body: JSON.stringify({ slug: entry.slug, category: entry.category }),
      });
      const result = await start(build_id);
      if (result === 'success') onInstalled();
    } catch {
      /* surfaced via build stream / status */
    } finally {
      setInstalling(null);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 50,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
      }}
    >
      <div onClick={(e) => e.stopPropagation()} style={panel}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 18px', borderBottom: '1px solid rgba(230,235,242,0.07)' }}>
          <div>
            <h3 style={{ color: ink, fontSize: 15, fontWeight: 600, margin: 0 }}>Printing Press Library</h3>
            <p style={{ color: inkDim, fontSize: 12, margin: '2px 0 0' }}>Install a ready-made CLI to give your agents a new API.</p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: inkSoft, fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: '12px 18px' }}>
          <p style={{ color: inkDim, fontSize: 11, lineHeight: 1.5, margin: '0 0 10px' }}>
            CLIs come from the official Printing Press library, are built from source on your server, and run as
            isolated subprocesses with only the credentials you provide. Installing one makes its commands available
            to all of your agents.
          </p>
          <input
            placeholder="Search APIs…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: '100%', boxSizing: 'border-box', padding: '8px 12px', fontSize: 13, borderRadius: 5, background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)', color: ink }}
          />
        </div>

        <div style={{ overflowY: 'auto', padding: '0 18px 18px' }}>
          {loading && <p style={{ color: inkSoft, fontSize: 13 }}>Loading library…</p>}
          {loadError && <p style={{ color: '#D97757', fontSize: 13 }}>{loadError}</p>}
          {!loading && !loadError && filtered.length === 0 && (
            <p style={{ color: inkSoft, fontSize: 13 }}>No APIs match “{query}”.</p>
          )}
          {filtered.map((entry) => {
            const isInstalled = installedSlugs.has(entry.slug);
            const isThis = installing === entry.slug;
            return (
              <div key={entry.slug} style={{ background: 'rgba(20,24,30,0.78)', borderRadius: 6, padding: 14, marginBottom: 8, border: '1px solid rgba(230,235,242,0.07)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ color: ink, fontSize: 14, fontWeight: 600 }}>{entry.api}</span>
                      {entry.tool_count != null && (
                        <span style={{ color: inkDim, fontSize: 11 }}>{entry.tool_count} commands</span>
                      )}
                      {entry.auth_type && entry.auth_type !== 'none' && (
                        <span style={{ fontSize: 10, color: '#8EA589', background: 'rgba(142,165,137,0.1)', padding: '1px 6px', borderRadius: 4 }}>auth: {entry.auth_type}</span>
                      )}
                    </div>
                    <p style={{ color: inkSoft, fontSize: 12, margin: '4px 0 0', lineHeight: 1.45 }}>{entry.description}</p>
                  </div>
                  <button
                    onClick={() => install(entry)}
                    disabled={isInstalled || !!installing}
                    style={{
                      flexShrink: 0, padding: '6px 14px', fontSize: 12, borderRadius: 5, fontWeight: 500,
                      border: isInstalled ? '1px solid rgba(230,235,242,0.14)' : 'none',
                      background: isInstalled ? 'transparent' : 'var(--color-ch-accent, #C8D1D9)',
                      color: isInstalled ? inkDim : '#0E1013',
                      cursor: isInstalled || installing ? 'default' : 'pointer',
                      opacity: !isInstalled && installing && !isThis ? 0.4 : 1,
                    }}
                  >
                    {isInstalled ? 'Installed' : isThis ? 'Installing…' : 'Install'}
                  </button>
                </div>

                {isThis && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(230,235,242,0.07)' }}>
                    {logs.map((l, i) => (
                      <div key={i} style={{ color: l.phase === 'error' ? '#D97757' : inkSoft, fontSize: 11, fontFamily: 'monospace' }}>
                        <span style={{ color: inkDim }}>{l.phase}</span> · {l.msg}
                      </div>
                    ))}
                    {status === 'streaming' && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                        <div style={{ width: 12, height: 12, border: '2px solid var(--color-ch-accent, #C8D1D9)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                        <span style={{ color: inkDim, fontSize: 11 }}>Building… this can take a minute on the first install.</span>
                      </div>
                    )}
                    {buildError && <div style={{ color: '#D97757', fontSize: 11, marginTop: 4 }}>{buildError}</div>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
