import { useState, useEffect } from 'react';
import { api } from '../core/api/client';

interface Props {
  provider: string;
  currentModel: string;
  onChanged: () => void;
}

export function ModelSelector({ provider, currentModel, onChanged }: Props) {
  const [models, setModels] = useState<string[]>([]);
  const [selected, setSelected] = useState(currentModel);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ models: string[] }>(`/api/providers/${provider}/models`)
      .then(data => setModels(data.models))
      .catch(console.error);
  }, [provider]);

  async function save(model: string) {
    setSaving(true);
    try {
      await api('/api/providers/active', {
        method: 'PUT',
        body: JSON.stringify({ provider, model }),
      });
      setSelected(model);
      onChanged();
    } catch (err) {
      console.error('Failed to set model:', err);
    } finally {
      setSaving(false);
    }
  }

  if (!models.length) return null;

  return (
    <div>
      <label style={{
        display: 'block',
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
        color: 'rgba(237,240,244,0.38)', marginBottom: 6,
      }}>Model</label>
      <select
        value={selected}
        onChange={e => save(e.target.value)}
        disabled={saving}
        style={{
          width: '100%', boxSizing: 'border-box',
          background: 'rgba(34,40,48,0.55)', border: '1px solid rgba(230,235,242,0.14)',
          color: '#EDF0F4', borderRadius: 4, padding: '8px 12px', fontSize: 13,
          outline: 'none', opacity: saving ? 0.5 : 1,
        }}
      >
        {models.map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}
