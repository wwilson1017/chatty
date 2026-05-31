import { useEffect, useRef, useState } from 'react';
import { api } from '../../core/api/client';

interface Props {
  agentId: string;
  hasAvatar: boolean;
  openaiAvailable: boolean;
  onGenerate: () => void;
  onAvatarChanged: () => void;
  onClose: () => void;
  anchorRect: DOMRect | null;
}

export function AvatarMenu({
  agentId, hasAvatar, openaiAvailable,
  onGenerate, onAvatarChanged, onClose, anchorRect,
}: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [onClose]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const token = sessionStorage.getItem('chatty_token');
      const res = await fetch(`/api/agents/${agentId}/avatar/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) {
        if (res.status === 401) { window.location.href = '/login'; return; }
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || 'Upload failed');
      }
      onAvatarChanged();
    } catch {
      setUploading(false);
    }
    if (fileRef.current) fileRef.current.value = '';
  }

  async function handleRemove() {
    setRemoving(true);
    try {
      await api(`/api/agents/${agentId}/avatar`, { method: 'DELETE' });
      onAvatarChanged();
    } catch {
      setRemoving(false);
    }
  }

  const top = anchorRect ? anchorRect.bottom + 6 : 0;
  const left = anchorRect ? anchorRect.left : 0;

  const itemStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '9px 14px', cursor: 'pointer',
    fontSize: 13, color: 'rgba(237,240,244,0.78)',
    fontFamily: "'Inter Tight', system-ui, sans-serif",
    borderRadius: 4,
    background: 'transparent',
    border: 'none', width: '100%', textAlign: 'left',
  };

  return (
    <div
      ref={menuRef}
      style={{
        position: 'fixed', top, left, zIndex: 100,
        background: '#181C22',
        border: '1px solid rgba(230,235,242,0.10)',
        borderRadius: 8, padding: '4px 0',
        minWidth: 180,
        boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
      }}
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={handleUpload}
        style={{ display: 'none' }}
      />

      <button
        style={itemStyle}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(230,235,242,0.06)'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
        onClick={() => fileRef.current?.click()}
        disabled={uploading}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        {uploading ? 'Uploading...' : 'Upload image'}
      </button>

      {openaiAvailable && (
        <button
          style={itemStyle}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(230,235,242,0.06)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
          onClick={() => { onClose(); onGenerate(); }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          Generate with AI
        </button>
      )}

      {hasAvatar && (
        <>
          <div style={{ height: 1, background: 'rgba(230,235,242,0.07)', margin: '4px 0' }} />
          <button
            style={{ ...itemStyle, color: 'rgba(217,119,87,0.85)' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(217,119,87,0.08)'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
            onClick={handleRemove}
            disabled={removing}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
            </svg>
            {removing ? 'Removing...' : 'Remove avatar'}
          </button>
        </>
      )}
    </div>
  );
}
