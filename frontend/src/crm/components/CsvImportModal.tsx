import { useState, useRef } from 'react';

interface Props {
  onClose: () => void;
  onImported: () => void;
}

export function CsvImportModal({ onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ imported: number; skipped: number; errors: string[] } | null>(null);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload() {
    if (!file) return;
    setUploading(true); setError(''); setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = sessionStorage.getItem('chatty_token');
      const resp = await fetch('/api/crm/import', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `Import failed (${resp.status})`);
      }
      const data = await resp.json();
      setResult(data);
      if (data.imported > 0) setTimeout(onImported, 1500);
    } catch (err: unknown) { setError(err instanceof Error ? err.message : 'Import failed'); }
    setUploading(false);
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        background: '#11141A', borderRadius: 6, border: '1px solid rgba(230,235,242,0.14)',
        padding: 24, width: '100%', maxWidth: 420, boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
      }}>
        <h2 style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 400, letterSpacing: '-0.02em', color: '#EDF0F4', marginBottom: 8 }}>
          Import Contacts
        </h2>
        <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', marginBottom: 16, lineHeight: 1.5 }}>
          Upload a CSV with columns: name, email, phone, company, title, source, tags, notes. Only "name" is required.
        </p>

        {error && <p style={{ color: '#D97757', fontSize: 12, marginBottom: 12 }}>{error}</p>}

        {result ? (
          <div style={{ background: 'rgba(34,40,48,0.55)', borderRadius: 6, padding: 16, marginBottom: 16 }}>
            <p style={{ color: '#8EA589', fontSize: 14, fontWeight: 500 }}>{result.imported} contacts imported</p>
            {result.skipped > 0 && <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, marginTop: 4 }}>{result.skipped} rows skipped (no name)</p>}
            {result.errors.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <p style={{ color: '#D97757', fontSize: 12 }}>{result.errors.length} errors:</p>
                {result.errors.slice(0, 5).map((e, i) => <p key={i} style={{ color: 'rgba(237,240,244,0.38)', fontSize: 11 }}>{e}</p>)}
              </div>
            )}
          </div>
        ) : (
          <div
            onClick={() => inputRef.current?.click()}
            style={{
              border: '2px dashed rgba(230,235,242,0.14)', borderRadius: 6,
              padding: 32, textAlign: 'center', cursor: 'pointer', marginBottom: 16,
            }}
          >
            <input ref={inputRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={e => setFile(e.target.files?.[0] ?? null)} />
            {file ? (
              <p style={{ color: '#EDF0F4', fontSize: 13 }}>{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
            ) : (
              <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 13 }}>Click to select a CSV file</p>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '9px 16px', borderRadius: 4,
            border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
            color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
          }}>{result ? 'Close' : 'Cancel'}</button>
          {!result && (
            <button onClick={handleUpload} disabled={!file || uploading} style={{
              flex: 1, padding: '9px 16px', borderRadius: 4,
              background: '#D4A85A', color: '#0E1013',
              border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
              opacity: (!file || uploading) ? 0.5 : 1,
            }}>{uploading ? 'Importing...' : 'Import'}</button>
          )}
        </div>
      </div>
    </div>
  );
}
