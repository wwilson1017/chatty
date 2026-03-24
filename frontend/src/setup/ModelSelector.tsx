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
      <label className="block text-xs text-gray-400 mb-1.5">Model</label>
      <select
        value={selected}
        onChange={e => save(e.target.value)}
        disabled={saving}
        className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
      >
        {models.map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}
