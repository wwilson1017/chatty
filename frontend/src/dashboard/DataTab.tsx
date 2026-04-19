import { useState, useRef } from 'react';
import { IconFile } from '../shared/icons';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function DataTab() {
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleDownload() {
    setDownloading(true);
    setMessage(null);
    try {
      const token = localStorage.getItem('chatty_token');
      const res = await fetch('/api/backup/download', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `chatty-backup-${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage({ type: 'success', text: 'Backup downloaded.' });
    } catch {
      setMessage({ type: 'error', text: 'Failed to download backup.' });
    } finally {
      setDownloading(false);
    }
  }

  async function handleRestore() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    if (!window.confirm('Are you sure? This will replace ALL current data and cannot be undone.')) return;

    setRestoring(true);
    setMessage(null);
    try {
      const token = localStorage.getItem('chatty_token');
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/backup/restore', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || 'Restore failed');
      }
      setMessage({ type: 'success', text: 'Restore complete. Reloading...' });
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : 'Restore failed.' });
    } finally {
      setRestoring(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
      {/* Backup */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 4,
            background: 'rgba(245,239,227,0.06)', border: '1px solid rgba(230,235,242,0.07)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(237,240,244,0.62)',
          }}>
            <IconFile size={14} strokeWidth={1.75} />
          </div>
          <h3 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 16, fontWeight: 400, letterSpacing: '-0.01em',
            color: '#EDF0F4', margin: 0,
          }}>Download Backup</h3>
        </div>
        <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', marginBottom: 16, lineHeight: 1.5 }}>
          Download a ZIP containing all your agents, conversations, settings, and integrations data.
        </p>
        <button onClick={handleDownload} disabled={downloading} style={{
          width: '100%', padding: '10px 16px',
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', borderRadius: 4, fontSize: 14, fontWeight: 500,
          cursor: 'pointer', opacity: downloading ? 0.5 : 1,
        }}>
          {downloading ? 'Downloading...' : 'Download Backup'}
        </button>
      </div>

      <div style={{ height: 1, background: 'rgba(230,235,242,0.07)' }} />

      {/* Restore */}
      <div>
        <h3 style={{
          fontFamily: "'Fraunces', Georgia, serif",
          fontSize: 16, fontWeight: 400, letterSpacing: '-0.01em',
          color: '#EDF0F4', margin: '0 0 8px',
        }}>Restore from Backup</h3>
        <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', marginBottom: 12, lineHeight: 1.5 }}>
          Upload a previously downloaded backup ZIP to restore all your data.
        </p>

        <div style={{
          background: 'rgba(212,168,90,0.06)', border: '1px solid rgba(212,168,90,0.15)',
          borderRadius: 6, padding: '10px 16px', marginBottom: 16,
        }}>
          <p style={{ fontSize: 13, color: '#D4A85A', margin: 0 }}>
            This will replace all current data and cannot be undone.
          </p>
        </div>

        <input ref={fileRef} type="file" accept=".zip"
          style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)', display: 'block', marginBottom: 16, width: '100%' }}
        />
        <button onClick={handleRestore} disabled={restoring} style={{
          width: '100%', padding: '10px 16px',
          background: 'transparent', color: '#D97757',
          border: '1px solid rgba(217,119,87,0.25)', borderRadius: 4, fontSize: 14, fontWeight: 500,
          cursor: 'pointer', opacity: restoring ? 0.5 : 1,
        }}>
          {restoring ? 'Restoring...' : 'Restore Backup'}
        </button>
      </div>

      {/* Status message */}
      {message && (
        <div style={{
          borderRadius: 6, padding: '10px 16px', fontSize: 13,
          background: message.type === 'success' ? 'rgba(142,165,137,0.06)' : 'rgba(217,119,87,0.08)',
          border: `1px solid ${message.type === 'success' ? 'rgba(142,165,137,0.15)' : 'rgba(217,119,87,0.2)'}`,
          color: message.type === 'success' ? '#8EA589' : '#D97757',
        }}>
          {message.text}
        </div>
      )}
    </div>
  );
}
