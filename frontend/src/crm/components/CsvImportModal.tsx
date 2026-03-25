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

      const token = localStorage.getItem('chatty_token');
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

      if (data.imported > 0) {
        setTimeout(onImported, 1500);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed');
    }
    setUploading(false);
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-gray-900 rounded-2xl border border-gray-700 p-6 w-full max-w-md">
        <h2 className="text-white font-bold text-lg mb-2">Import Contacts</h2>
        <p className="text-gray-400 text-xs mb-4">
          Upload a CSV with columns: name, email, phone, company, title, source, tags, notes.
          Only "name" is required.
        </p>

        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        {result ? (
          <div className="bg-gray-800 rounded-xl p-4 mb-4">
            <p className="text-green-400 text-sm font-medium">{result.imported} contacts imported</p>
            {result.skipped > 0 && <p className="text-gray-400 text-xs mt-1">{result.skipped} rows skipped (no name)</p>}
            {result.errors.length > 0 && (
              <div className="mt-2">
                <p className="text-red-400 text-xs">{result.errors.length} errors:</p>
                {result.errors.slice(0, 5).map((e, i) => <p key={i} className="text-gray-500 text-xs">{e}</p>)}
              </div>
            )}
          </div>
        ) : (
          <div
            onClick={() => inputRef.current?.click()}
            className="border-2 border-dashed border-gray-700 rounded-xl p-8 text-center cursor-pointer hover:border-gray-600 transition mb-4"
          >
            <input ref={inputRef} type="file" accept=".csv" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} />
            {file ? (
              <p className="text-white text-sm">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
            ) : (
              <p className="text-gray-500 text-sm">Click to select a CSV file</p>
            )}
          </div>
        )}

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50"
            >
              {uploading ? 'Importing...' : 'Import'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
