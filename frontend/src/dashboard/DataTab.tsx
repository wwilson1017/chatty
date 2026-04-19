import { useState, useRef } from 'react';

export function DataTab() {
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleDownload() {
    setDownloading(true);
    setMessage(null);
    try {
      const token = sessionStorage.getItem('chatty_token');
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

    if (!window.confirm('Are you sure? This will replace ALL current data and cannot be undone.')) {
      return;
    }

    setRestoring(true);
    setMessage(null);
    try {
      const token = sessionStorage.getItem('chatty_token');
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
    <div className="space-y-8">
      {/* Backup */}
      <div>
        <h3 className="text-white font-semibold mb-2">Download Backup</h3>
        <p className="text-gray-400 text-sm mb-4">
          Download a ZIP file containing all your agents, conversations, settings, and integrations data.
        </p>
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="w-full py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-50"
        >
          {downloading ? 'Downloading...' : 'Download Backup'}
        </button>
      </div>

      {/* Divider */}
      <div className="border-t border-gray-800" />

      {/* Restore */}
      <div>
        <h3 className="text-white font-semibold mb-2">Restore from Backup</h3>
        <p className="text-gray-400 text-sm mb-3">
          Upload a previously downloaded backup ZIP to restore all your data.
        </p>
        <div className="bg-amber-900/30 border border-amber-700/50 rounded-lg px-4 py-3 mb-4">
          <p className="text-amber-300 text-sm">
            This will replace all current data and cannot be undone.
          </p>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          className="text-sm text-gray-400 mb-4 block w-full"
        />
        <button
          onClick={handleRestore}
          disabled={restoring}
          className="w-full py-3 bg-red-600 text-white font-semibold rounded-xl hover:bg-red-700 transition disabled:opacity-50"
        >
          {restoring ? 'Restoring...' : 'Restore Backup'}
        </button>
      </div>

      {/* Status message */}
      {message && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            message.type === 'success'
              ? 'bg-green-900/30 border border-green-700/50 text-green-300'
              : 'bg-red-900/30 border border-red-700/50 text-red-300'
          }`}
        >
          {message.text}
        </div>
      )}
    </div>
  );
}
