import { useState, useRef } from 'react';

interface ParsedContact {
  name: string;
  email: string;
  phone: string;
  company: string;
  title: string;
  source: string;
  tags: string;
  notes: string;
}

interface ParseResult {
  contacts: ParsedContact[];
  ai_used: boolean;
  warnings: string[];
}

interface ImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

interface Props {
  onClose: () => void;
  onImported: () => void;
}

type Step = 'upload' | 'parsing' | 'preview' | 'result';

export function SmartImportModal({ onClose, onImported }: Props) {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleParse() {
    if (!file) return;
    setStep('parsing');
    setError('');

    try {
      const formData = new FormData();
      formData.append('file', file);

      const token = sessionStorage.getItem('chatty_token');
      const resp = await fetch('/api/crm/smart-import/parse', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `Parse failed (${resp.status})`);
      }

      const data: ParseResult = await resp.json();
      setParseResult(data);

      if (data.contacts.length > 0) {
        setSelected(new Set(data.contacts.map((_, i) => i)));
        setStep('preview');
      } else {
        setStep('upload');
        setError(data.warnings.join(' ') || 'No contacts found in file');
      }
    } catch (err: unknown) {
      setStep('upload');
      setError(err instanceof Error ? err.message : 'Parse failed');
    }
  }

  async function handleImport() {
    if (!parseResult) return;
    setError('');

    const contacts = parseResult.contacts.filter((_, i) => selected.has(i));
    if (contacts.length === 0) {
      setError('No contacts selected');
      return;
    }

    try {
      const token = sessionStorage.getItem('chatty_token');
      const resp = await fetch('/api/crm/smart-import/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ contacts }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || `Import failed (${resp.status})`);
      }

      const data: ImportResult = await resp.json();
      setImportResult(data);
      setStep('result');

      if (data.imported > 0) {
        setTimeout(onImported, 1500);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed');
    }
  }

  function toggleAll() {
    if (!parseResult) return;
    if (selected.size === parseResult.contacts.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(parseResult.contacts.map((_, i) => i)));
    }
  }

  function toggleOne(idx: number) {
    const next = new Set(selected);
    if (next.has(idx)) next.delete(idx);
    else next.add(idx);
    setSelected(next);
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        className={`bg-gray-900 rounded-2xl border border-gray-700 p-6 w-full ${
          step === 'preview' ? 'max-w-3xl' : 'max-w-md'
        }`}
      >
        <h2 className="text-white font-bold text-lg mb-2">Import Contacts</h2>

        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}

        {/* Step: Upload */}
        {step === 'upload' && (
          <>
            <p className="text-gray-400 text-xs mb-4">
              Drop any file — CSV, vCard (.vcf), JSON, or plain text. AI will extract contacts from any format.
            </p>
            <div
              onClick={() => inputRef.current?.click()}
              className="border-2 border-dashed border-gray-700 rounded-xl p-8 text-center cursor-pointer hover:border-gray-600 transition mb-4"
            >
              <input
                ref={inputRef}
                type="file"
                accept=".csv,.vcf,.json,.txt,.tsv,.xls,.xlsx"
                className="hidden"
                onChange={e => setFile(e.target.files?.[0] ?? null)}
              />
              {file ? (
                <p className="text-white text-sm">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
              ) : (
                <p className="text-gray-500 text-sm">Click to select a file</p>
              )}
            </div>
            <div className="flex gap-2">
              <button onClick={onClose} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">
                Cancel
              </button>
              <button
                onClick={handleParse}
                disabled={!file}
                className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50"
              >
                Parse Contacts
              </button>
            </div>
          </>
        )}

        {/* Step: Parsing */}
        {step === 'parsing' && (
          <div className="py-8 text-center">
            <div className="animate-spin h-8 w-8 border-2 border-gray-600 border-t-brand rounded-full mx-auto mb-4" />
            <p className="text-gray-400 text-sm">Analyzing contacts...</p>
          </div>
        )}

        {/* Step: Preview */}
        {step === 'preview' && parseResult && (
          <>
            {parseResult.ai_used && (
              <p className="text-amber-400 text-xs mb-2">
                Parsed with AI — please verify the results before importing.
              </p>
            )}
            {parseResult.warnings.map((w, i) => (
              <p key={i} className="text-amber-400 text-xs mb-1">{w}</p>
            ))}

            <div className="flex items-center justify-between mb-2 mt-3">
              <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selected.size === parseResult.contacts.length}
                  onChange={toggleAll}
                  className="accent-brand"
                />
                Select all ({parseResult.contacts.length})
              </label>
              <span className="text-xs text-gray-500">{selected.size} selected</span>
            </div>

            <div className="max-h-80 overflow-y-auto border border-gray-800 rounded-xl mb-4">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-gray-800 text-gray-400">
                  <tr>
                    <th className="p-2 w-8" />
                    <th className="p-2 text-left">Name</th>
                    <th className="p-2 text-left">Email</th>
                    <th className="p-2 text-left">Phone</th>
                    <th className="p-2 text-left">Company</th>
                  </tr>
                </thead>
                <tbody className="text-gray-300">
                  {parseResult.contacts.map((c, i) => (
                    <tr
                      key={i}
                      className={`border-t border-gray-800 cursor-pointer hover:bg-gray-800/50 ${
                        !selected.has(i) ? 'opacity-40' : ''
                      }`}
                      onClick={() => toggleOne(i)}
                    >
                      <td className="p-2 text-center">
                        <input
                          type="checkbox"
                          checked={selected.has(i)}
                          onChange={() => toggleOne(i)}
                          className="accent-brand"
                          onClick={e => e.stopPropagation()}
                        />
                      </td>
                      <td className="p-2">
                        <span className="text-white font-medium">{c.name || '—'}</span>
                        {c.title && <span className="text-gray-500 ml-1">({c.title})</span>}
                      </td>
                      <td className="p-2">{c.email || '—'}</td>
                      <td className="p-2">{c.phone || '—'}</td>
                      <td className="p-2">{c.company || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex gap-2">
              <button onClick={onClose} className="flex-1 py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">
                Cancel
              </button>
              <button
                onClick={handleImport}
                disabled={selected.size === 0}
                className="flex-1 py-2 text-sm rounded-lg bg-brand text-white font-medium disabled:opacity-50"
              >
                Import Selected ({selected.size})
              </button>
            </div>
          </>
        )}

        {/* Step: Result */}
        {step === 'result' && importResult && (
          <>
            <div className="bg-gray-800 rounded-xl p-4 mb-4">
              <p className="text-green-400 text-sm font-medium">{importResult.imported} contacts imported</p>
              {importResult.skipped > 0 && <p className="text-gray-400 text-xs mt-1">{importResult.skipped} skipped (no name)</p>}
              {importResult.errors.length > 0 && (
                <div className="mt-2">
                  <p className="text-red-400 text-xs">{importResult.errors.length} errors:</p>
                  {importResult.errors.slice(0, 5).map((e, i) => <p key={i} className="text-gray-500 text-xs">{e}</p>)}
                </div>
              )}
            </div>
            <button onClick={onClose} className="w-full py-2 text-sm rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-800 transition">
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
}
