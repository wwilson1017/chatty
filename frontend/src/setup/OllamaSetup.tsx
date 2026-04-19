import { useState, useEffect } from 'react';
import { api } from '../core/api/client';

interface Props {
  onConnected: () => void;
}

interface OllamaStatus {
  reachable: boolean;
  models: string[];
}

const RECOMMENDED_MODELS = [
  { name: 'qwen3.5:4b', desc: 'Lightweight (3.4 GB) — works on any computer' },
  { name: 'qwen3.5:9b', desc: 'Balanced (6 GB) — best quality for the size' },
  { name: 'llama3.1:8b', desc: 'Quality (5 GB) — needs 16 GB RAM' },
];

export function OllamaSetup({ onConnected }: Props) {
  const [status, setStatus] = useState<OllamaStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customUrl, setCustomUrl] = useState('http://localhost:11434');

  useEffect(() => {
    checkStatus();
  }, []);

  async function checkStatus() {
    setChecking(true);
    try {
      const data = await api<OllamaStatus>('/api/providers/ollama/status');
      setStatus(data);
      if (data.models.length > 0) {
        setSelectedModel(data.models[0]);
      }
    } catch {
      setStatus({ reachable: false, models: [] });
    } finally {
      setChecking(false);
    }
  }

  async function connect() {
    setConnecting(true);
    setError('');
    try {
      await api('/api/providers/ollama/connect', {
        method: 'POST',
        body: JSON.stringify({ base_url: customUrl, model: selectedModel }),
      });
      onConnected();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to connect to Ollama');
    } finally {
      setConnecting(false);
    }
  }

  if (checking) {
    return (
      <div className="flex items-center gap-2 py-4">
        <div className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-sm text-gray-400">Detecting Ollama...</span>
      </div>
    );
  }

  // Ollama detected with models installed
  if (status?.reachable && status.models.length > 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-green-400 rounded-full" />
          <span className="text-sm text-green-400">Ollama detected</span>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1.5">Select a model</label>
          <select
            value={selectedModel}
            onChange={e => setSelectedModel(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
          >
            {status.models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>

        {error && <p className="text-red-400 text-xs">{error}</p>}

        <button
          onClick={connect}
          disabled={connecting || !selectedModel}
          className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
        >
          {connecting ? 'Connecting...' : 'Connect'}
        </button>
      </div>
    );
  }

  // Ollama detected but no models
  if (status?.reachable && status.models.length === 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-yellow-400 rounded-full" />
          <span className="text-sm text-yellow-400">Ollama is running but no models are installed</span>
        </div>

        <p className="text-xs text-gray-400">
          Pull a model in your terminal, then click "Refresh":
        </p>

        <div className="space-y-2">
          {RECOMMENDED_MODELS.map(m => (
            <div key={m.name} className="bg-gray-700/50 rounded-lg px-3 py-2">
              <code className="text-xs text-indigo-400">ollama pull {m.name}</code>
              <p className="text-xs text-gray-500 mt-0.5">{m.desc}</p>
            </div>
          ))}
        </div>

        <button
          onClick={checkStatus}
          className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition"
        >
          Refresh
        </button>
      </div>
    );
  }

  // Ollama not detected
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 bg-red-400 rounded-full" />
        <span className="text-sm text-red-400">Ollama not detected</span>
      </div>

      <div className="bg-gray-700/50 rounded-lg px-4 py-3 space-y-2">
        <p className="text-sm text-gray-300">Run AI models locally for free:</p>
        <ol className="text-xs text-gray-400 space-y-1 list-decimal list-inside">
          <li>
            Install Ollama from{' '}
            <a href="https://ollama.com" target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300">
              ollama.com
            </a>
          </li>
          <li>Run <code className="text-indigo-400">ollama pull qwen3.5:4b</code> in your terminal</li>
          <li>Come back here and click "Refresh"</li>
        </ol>
      </div>

      <button
        onClick={checkStatus}
        className="w-full py-2 text-sm rounded-lg border border-indigo-500/50 text-indigo-400 hover:bg-indigo-500/10 transition"
      >
        Refresh
      </button>

      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="w-full text-xs text-gray-500 hover:text-gray-400 transition"
      >
        {showAdvanced ? 'Hide' : 'Advanced'}: Custom Ollama URL
      </button>

      {showAdvanced && (
        <div className="space-y-2">
          <input
            type="text"
            value={customUrl}
            onChange={e => setCustomUrl(e.target.value)}
            placeholder="http://localhost:11434"
            className="w-full bg-gray-700 border border-gray-600 text-white rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-indigo-500"
          />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            onClick={connect}
            disabled={connecting || !customUrl.trim()}
            className="w-full py-2.5 bg-brand text-white text-sm font-semibold rounded-lg hover:opacity-90 transition disabled:opacity-50"
          >
            {connecting ? 'Connecting...' : 'Connect'}
          </button>
        </div>
      )}
    </div>
  );
}
