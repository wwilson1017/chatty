import { useState } from 'react';
import { api } from '../../core/api/client';
import { toast } from '../../shared/toast';
import { inputStyle } from '../../shared/styles';
import { btnPrimary } from '../styles';

interface Props {
  onAdded: () => void;
  isMobile: boolean;
}

/** One-line capture box in the Todos header — always lands in the inbox. */
export function QuickAdd({ onAdded, isMobile }: Props) {
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);

  async function add() {
    const trimmed = title.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    try {
      await api('/api/todo/todos', {
        method: 'POST',
        body: JSON.stringify({ title: trimmed }),
      });
      setTitle('');
      onAdded();
    } catch {
      toast.error('Failed to add todo.');
    }
    setSaving(false);
  }

  return (
    <div style={{ display: 'flex', gap: 8, width: isMobile ? '100%' : 340 }}>
      <input
        value={title}
        onChange={e => setTitle(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') add(); }}
        placeholder="Add to inbox..."
        style={{ ...inputStyle, flex: 1, padding: '7px 12px', fontSize: 14 }}
      />
      <button
        onClick={add}
        disabled={saving || !title.trim()}
        style={{
          ...btnPrimary, padding: '7px 14px', fontSize: 13,
          opacity: saving || !title.trim() ? 0.5 : 1,
        }}
      >Add</button>
    </div>
  );
}
