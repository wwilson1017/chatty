/**
 * Chatty — AgentContextEditor.
 * View and edit agent knowledge files.
 */

import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';

interface ContextFile {
  name: string;
  size_bytes: number;
  modified: number;
}

interface Props {
  agentId: string;
}

export function AgentContextEditor({ agentId }: Props) {
  const [files, setFiles] = useState<ContextFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  const apiBase = `/api/agents/${agentId}`;

  useEffect(() => {
    api<{ files: ContextFile[] }>(`${apiBase}/context`)
      .then(data => setFiles(data.files))
      .catch(console.error);
  }, [agentId]);

  async function selectFile(name: string) {
    if (dirty && !confirm('Unsaved changes — discard?')) return;
    setLoading(true);
    try {
      const data = await api<{ filename: string; content: string }>(`${apiBase}/context/${encodeURIComponent(name)}`);
      setSelectedFile(name);
      setContent(data.content);
      setDirty(false);
    } finally {
      setLoading(false);
    }
  }

  async function saveFile() {
    if (!selectedFile) return;
    setSaving(true);
    try {
      await api(`${apiBase}/context/${encodeURIComponent(selectedFile)}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      });
      setDirty(false);
      // Refresh file list
      const data = await api<{ files: ContextFile[] }>(`${apiBase}/context`);
      setFiles(data.files);
    } finally {
      setSaving(false);
    }
  }

  async function deleteFile(name: string) {
    if (!confirm(`Delete ${name}?`)) return;
    await api(`${apiBase}/context/${encodeURIComponent(name)}`, { method: 'DELETE' });
    setFiles(prev => prev.filter(f => f.name !== name));
    if (selectedFile === name) { setSelectedFile(null); setContent(''); setDirty(false); }
  }

  function formatSize(bytes: number) {
    if (bytes < 1024) return `${bytes}B`;
    return `${(bytes / 1024).toFixed(1)}KB`;
  }

  return (
    <div className="flex h-full">
      {/* File list */}
      <div className="w-56 border-r border-gray-800 flex flex-col">
        <div className="px-4 py-3 border-b border-gray-800">
          <p className="text-sm font-medium text-gray-300">Knowledge Files</p>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {files.length === 0 ? (
            <p className="text-gray-600 text-xs text-center py-4 px-3">No knowledge files yet</p>
          ) : (
            files.map(f => (
              <div
                key={f.name}
                onClick={() => selectFile(f.name)}
                className={`group flex items-center justify-between px-3 py-2 cursor-pointer transition ${
                  selectedFile === f.name ? 'bg-indigo-900/30 text-indigo-300' : 'hover:bg-gray-800/50 text-gray-300'
                }`}
              >
                <div className="min-w-0">
                  <p className="text-xs font-mono truncate">{f.name}</p>
                  <p className="text-xs text-gray-600">{formatSize(f.size_bytes)}</p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); deleteFile(f.name); }}
                  className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition text-sm ml-1"
                >×</button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col">
        {selectedFile ? (
          <>
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <span className="text-sm font-mono text-gray-300">{selectedFile}</span>
              {dirty && (
                <button
                  onClick={saveFile}
                  disabled={saving}
                  className="text-xs bg-brand text-white px-3 py-1.5 rounded-lg hover:opacity-90 transition disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              )}
            </div>
            {loading ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              <textarea
                value={content}
                onChange={e => { setContent(e.target.value); setDirty(true); }}
                className="flex-1 bg-transparent text-gray-200 text-sm font-mono p-4 resize-none focus:outline-none"
                spellCheck={false}
              />
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
            Select a file to edit
          </div>
        )}
      </div>
    </div>
  );
}
