import { useState, useEffect } from 'react';
import { api } from '../../core/api/client';
import { useIsMobile } from '../../shared/useIsMobile';

interface ContextFile {
  name: string;
  size_bytes: number;
  modified: number;
}

interface Observation {
  id: number;
  observation: string;
  created_at: string;
  reference_count: number;
}

interface Props {
  agentId: string;
}

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

export function AgentContextEditor({ agentId }: Props) {
  const [files, setFiles] = useState<ContextFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [obsExpanded, setObsExpanded] = useState(true);
  const isMobile = useIsMobile();

  const apiBase = `/api/agents/${agentId}`;

  useEffect(() => {
    api<{ files: ContextFile[] }>(`${apiBase}/context`)
      .then(data => setFiles(data.files))
      .catch(console.error);
    api<{ observations: Observation[] }>(`${apiBase}/observations`)
      .then(data => setObservations(data.observations))
      .catch(() => {});
  }, [agentId, apiBase]);

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

  function handleBack() {
    if (dirty && !confirm('Unsaved changes — discard?')) return;
    setSelectedFile(null);
    setContent('');
    setDirty(false);
  }

  async function deleteObservation(id: number) {
    if (!confirm('Delete this observation?')) return;
    try {
      await api(`${apiBase}/observations/${id}`, { method: 'DELETE' });
      setObservations(prev => prev.filter(o => o.id !== id));
    } catch { /* ignore */ }
  }

  function formatSize(bytes: number) {
    if (bytes < 1024) return `${bytes}B`;
    return `${(bytes / 1024).toFixed(1)}KB`;
  }

  const observationsSection = (
    <div style={{ borderBottom: '1px solid rgba(230,235,242,0.07)' }}>
      <div
        onClick={() => setObsExpanded(!obsExpanded)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <p style={{ ...mono(10, 'rgba(237,240,244,0.62)'), margin: 0 }}>What I've Learned</p>
          {observations.length > 0 && (
            <span style={{
              ...mono(9, 'rgba(237,240,244,0.38)'),
              background: 'rgba(230,235,242,0.08)',
              borderRadius: 8, padding: '1px 6px',
            }}>{observations.length}</span>
          )}
        </div>
        <span style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, transition: 'transform 0.2s', transform: obsExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>&rsaquo;</span>
      </div>
      {obsExpanded && (
        <div style={{ padding: '0 16px 12px' }}>
          {observations.length === 0 ? (
            <p style={{ color: 'rgba(237,240,244,0.28)', fontSize: 12, margin: 0 }}>
              No observations yet — these appear automatically after conversations
            </p>
          ) : (
            observations.map(o => (
              <div key={o.id} className="group" style={{
                display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                padding: '6px 0', gap: 8,
              }}>
                <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.72)', margin: 0, lineHeight: 1.4 }}>
                  {o.observation}
                </p>
                <button
                  onClick={() => deleteObservation(o.id)}
                  className={isMobile ? '' : 'opacity-0 group-hover:opacity-100 transition'}
                  style={{
                    background: 'none', border: 'none', flexShrink: 0,
                    color: 'rgba(237,240,244,0.38)', fontSize: 14,
                    cursor: 'pointer', padding: '0 4px',
                  }}
                >&times;</button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );

  // Mobile: show file list OR editor, not both
  if (isMobile) {
    if (selectedFile) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', overflow: 'hidden' }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px',
            borderBottom: '1px solid rgba(230,235,242,0.07)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button onClick={handleBack} style={{
                background: 'none', border: 'none', color: 'rgba(237,240,244,0.62)',
                fontSize: 16, cursor: 'pointer', padding: '0 4px',
              }}>&larr;</button>
              <span style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 12, color: '#EDF0F4',
              }}>{selectedFile}</span>
            </div>
            {dirty && (
              <button
                onClick={saveFile}
                disabled={saving}
                style={{
                  fontSize: 12, fontWeight: 500,
                  background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
                  border: 'none', borderRadius: 4,
                  padding: '5px 14px', cursor: 'pointer',
                  opacity: saving ? 0.5 : 1,
                }}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            )}
          </div>
          {loading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="w-5 h-5 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <textarea
              value={content}
              onChange={e => { setContent(e.target.value); setDirty(true); }}
              spellCheck={false}
              style={{
                flex: 1, width: '100%', boxSizing: 'border-box',
                background: 'transparent', color: '#EDF0F4',
                fontSize: 13, lineHeight: 1.6,
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                padding: 16, resize: 'none', border: 'none', outline: 'none',
              }}
            />
          )}
        </div>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', overflow: 'hidden' }}>
        {observationsSection}
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid rgba(230,235,242,0.07)',
        }}>
          <p style={{ ...mono(10, 'rgba(237,240,244,0.62)'), margin: 0 }}>Knowledge Files</p>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {files.length === 0 ? (
            <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, textAlign: 'center', padding: '16px 12px' }}>
              No knowledge files yet
            </p>
          ) : (
            files.map(f => (
              <div
                key={f.name}
                onClick={() => selectFile(f.name)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px', cursor: 'pointer',
                  borderBottom: '1px solid rgba(230,235,242,0.07)',
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <p style={{
                    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                    fontSize: 13, color: '#EDF0F4',
                    margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{f.name}</p>
                  <p style={{ fontSize: 11, color: 'rgba(237,240,244,0.38)', margin: '2px 0 0' }}>
                    {formatSize(f.size_bytes)}
                  </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={e => { e.stopPropagation(); deleteFile(f.name); }}
                    style={{
                      background: 'none', border: 'none',
                      color: 'rgba(237,240,244,0.38)', fontSize: 16,
                      cursor: 'pointer', padding: '2px 6px',
                    }}
                  >&times;</button>
                  <span style={{ color: 'rgba(237,240,244,0.38)', fontSize: 14 }}>&rsaquo;</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  // Desktop: side-by-side layout
  return (
    <div style={{ display: 'flex', flex: 1, height: '100%', width: '100%', overflow: 'hidden' }}>
      {/* File list */}
      <div style={{
        width: 224, flexShrink: 0,
        borderRight: '1px solid rgba(230,235,242,0.07)',
        display: 'flex', flexDirection: 'column',
      }}>
        {observationsSection}
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid rgba(230,235,242,0.07)',
        }}>
          <p style={{ ...mono(10, 'rgba(237,240,244,0.62)'), margin: 0 }}>Knowledge Files</p>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {files.length === 0 ? (
            <p style={{ color: 'rgba(237,240,244,0.38)', fontSize: 12, textAlign: 'center', padding: '16px 12px' }}>
              No knowledge files yet
            </p>
          ) : (
            files.map(f => (
              <div
                key={f.name}
                onClick={() => selectFile(f.name)}
                className="group"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '8px 12px', cursor: 'pointer',
                  background: selectedFile === f.name ? 'rgba(200,209,217,0.12)' : 'transparent',
                  borderLeft: selectedFile === f.name ? '2px solid var(--color-ch-accent, #C8D1D9)' : '2px solid transparent',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <p style={{
                    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                    fontSize: 12, color: selectedFile === f.name ? '#EDF0F4' : 'rgba(237,240,244,0.62)',
                    margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{f.name}</p>
                  <p style={{ fontSize: 11, color: 'rgba(237,240,244,0.38)', margin: '2px 0 0' }}>
                    {formatSize(f.size_bytes)}
                  </p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); deleteFile(f.name); }}
                  className="opacity-0 group-hover:opacity-100 transition"
                  style={{
                    background: 'none', border: 'none',
                    color: 'rgba(237,240,244,0.38)', fontSize: 14,
                    cursor: 'pointer', marginLeft: 4, padding: '2px 4px',
                  }}
                >&times;</button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Editor */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {selectedFile ? (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '10px 20px',
              borderBottom: '1px solid rgba(230,235,242,0.07)',
            }}>
              <span style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 13, color: 'rgba(237,240,244,0.62)',
              }}>{selectedFile}</span>
              {dirty && (
                <button
                  onClick={saveFile}
                  disabled={saving}
                  style={{
                    fontSize: 12, fontWeight: 500,
                    background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
                    border: 'none', borderRadius: 4,
                    padding: '5px 14px', cursor: 'pointer',
                    opacity: saving ? 0.5 : 1,
                  }}
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              )}
            </div>
            {loading ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div className="w-5 h-5 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
              </div>
            ) : (
              <textarea
                value={content}
                onChange={e => { setContent(e.target.value); setDirty(true); }}
                spellCheck={false}
                style={{
                  flex: 1, width: '100%', boxSizing: 'border-box',
                  background: 'transparent', color: '#EDF0F4',
                  fontSize: 13, lineHeight: 1.6,
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  padding: 20, resize: 'none', border: 'none', outline: 'none',
                }}
              />
            )}
          </>
        ) : (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'rgba(237,240,244,0.38)', fontSize: 14,
          }}>
            Select a file to edit
          </div>
        )}
      </div>
    </div>
  );
}
