import { useState } from 'react';
import { api } from '../../core/api/client';

interface Props {
  onComplete: () => void;
  onSkip: () => void;
}

export function CrmLiteSetupStep({ onComplete, onSkip }: Props) {
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState('');

  async function enable() {
    setEnabling(true);
    setError('');
    try {
      await api('/api/integrations/crm_lite/setup', { method: 'POST' });
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Setup failed');
    } finally {
      setEnabling(false);
    }
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-2">Enable Built-in CRM</h2>
      <p className="text-gray-400 text-sm mb-6">
        Chatty includes a lightweight CRM — no external account needed. Your agents can manage contacts,
        deals, tasks, and your sales pipeline.
      </p>

      <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 mb-6">
        <h3 className="text-white font-medium mb-3">What you get</h3>
        <ul className="text-gray-400 text-sm space-y-2">
          <li className="flex items-start gap-2">
            <span className="text-indigo-400 mt-0.5">&#x2022;</span>
            <span><span className="text-gray-300">Contacts</span> — store and search your contacts</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-indigo-400 mt-0.5">&#x2022;</span>
            <span><span className="text-gray-300">Deals</span> — track opportunities and pipeline stages</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-indigo-400 mt-0.5">&#x2022;</span>
            <span><span className="text-gray-300">Tasks</span> — manage follow-ups and to-dos</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-indigo-400 mt-0.5">&#x2022;</span>
            <span><span className="text-gray-300">Activity log</span> — automatic tracking of interactions</span>
          </li>
        </ul>
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-900/20 rounded-lg px-4 py-3 mb-4">{error}</div>
      )}

      <div className="flex gap-3">
        <button
          onClick={onSkip}
          className="flex-1 py-3 rounded-xl border border-gray-700 text-gray-400 hover:bg-gray-800 transition font-medium"
        >
          Skip
        </button>
        <button
          onClick={enable}
          disabled={enabling}
          className="flex-1 py-3 bg-brand text-white font-semibold rounded-xl hover:opacity-90 transition disabled:opacity-50"
        >
          {enabling ? 'Enabling...' : 'Enable CRM'}
        </button>
      </div>
    </div>
  );
}
