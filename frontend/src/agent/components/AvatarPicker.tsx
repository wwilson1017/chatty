/**
 * Chatty — Avatar picker for post-onboarding.
 *
 * Generates 3 DALL-E 3 avatar options (if OpenAI connected) or allows
 * manual upload. User can skip and set an avatar later.
 */

import { useState, useRef } from 'react';
import { api } from '../../core/api/client';

interface Props {
  agentId: string;
  agentName: string;
  openaiAvailable: boolean;
  onComplete: () => void;
  onSkip: () => void;
}

export function AvatarPicker({ agentId, agentName, openaiAvailable, onComplete, onSkip }: Props) {
  const [urls, setUrls] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setStarted(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 110_000);
    try {
      const data = await api<{ urls: string[]; partial?: boolean }>(
        `/api/agents/${agentId}/avatar/generate`,
        { method: 'POST', signal: controller.signal },
      );
      setUrls(data.urls);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setError('Generation timed out — try uploading your own instead');
      } else {
        setError(err instanceof Error ? err.message : 'Generation failed');
      }
    } finally {
      clearTimeout(timer);
      setGenerating(false);
    }
  };

  const handleSelect = async (index: number) => {
    setSelecting(true);
    try {
      await api(`/api/agents/${agentId}/avatar/select`, {
        method: 'POST',
        body: JSON.stringify({ index }),
      });
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save avatar');
      setSelecting(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
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
        if (res.status === 401) {
          window.location.href = '/login';
          return;
        }
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail || 'Upload failed');
      }
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="max-w-lg mx-auto px-6 py-16 text-center">
      <div className="w-16 h-16 bg-gradient-to-br from-brand to-brand-light rounded-full flex items-center justify-center mx-auto mb-6">
        <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0" />
        </svg>
      </div>

      <h2 className="text-xl font-bold text-white mb-2">
        Give {agentName} a face
      </h2>
      <p className="text-gray-400 text-sm mb-6">
        {openaiAvailable
          ? `We'll generate a few avatar options based on ${agentName}'s personality. Pick your favorite!`
          : `Upload an avatar image for ${agentName}, or skip for now.`}
      </p>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={handleUpload}
        className="hidden"
      />

      {!started && (
        <div className="flex flex-wrap gap-3 justify-center">
          {openaiAvailable && (
            <button
              onClick={handleGenerate}
              className="px-6 py-2.5 bg-brand text-white rounded-lg font-semibold hover:opacity-90 transition"
            >
              Generate avatars
            </button>
          )}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-6 py-2.5 border border-gray-600 text-white rounded-lg font-semibold hover:bg-gray-800 transition"
          >
            Upload your own
          </button>
          <button
            onClick={onSkip}
            className="px-6 py-2.5 text-gray-400 hover:text-white transition text-sm"
          >
            Skip for now
          </button>
        </div>
      )}

      {(generating || uploading) && (
        <div className="flex flex-col items-center gap-3 py-8">
          <div className="animate-spin w-8 h-8 border-2 border-brand border-t-transparent rounded-full" />
          <p className="text-sm text-gray-400">
            {uploading ? 'Uploading avatar...' : 'Generating avatars... this takes about 30 seconds'}
          </p>
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 text-red-400 text-sm rounded-lg p-4 mb-4">
          <p className="mb-2">{error}</p>
          <div className="flex gap-3 justify-center">
            {openaiAvailable && (
              <>
                <button onClick={handleGenerate} className="underline font-medium">Retry</button>
                <span className="text-red-600">or</span>
              </>
            )}
            <button onClick={() => fileInputRef.current?.click()} className="underline font-medium">
              upload your own
            </button>
          </div>
        </div>
      )}

      {urls.length > 0 && !selecting && (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            {urls.map((url, i) => (
              <button
                key={i}
                onClick={() => handleSelect(i)}
                className="group relative rounded-xl overflow-hidden border-2 border-transparent hover:border-brand transition-all shadow-sm hover:shadow-md"
              >
                <img
                  src={url}
                  alt={`Avatar option ${i + 1}`}
                  className="w-full aspect-square object-cover"
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors flex items-center justify-center">
                  <span className="opacity-0 group-hover:opacity-100 text-white text-sm font-semibold bg-brand/80 px-3 py-1 rounded-full transition-opacity">
                    Choose
                  </span>
                </div>
              </button>
            ))}
          </div>
          <button
            onClick={onSkip}
            className="text-sm text-gray-400 hover:text-white transition"
          >
            Skip for now
          </button>
        </div>
      )}

      {selecting && (
        <div className="flex flex-col items-center gap-3 py-8">
          <div className="animate-spin w-8 h-8 border-2 border-brand border-t-transparent rounded-full" />
          <p className="text-sm text-gray-400">Saving avatar...</p>
        </div>
      )}
    </div>
  );
}
