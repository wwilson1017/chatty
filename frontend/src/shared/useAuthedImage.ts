import { useEffect, useState } from 'react';
import { getToken } from '../core/auth/tokenUtils';

// <img> tags can't send Authorization headers, so authenticated images are
// fetched as blobs and rendered via object URLs — the session JWT never
// appears in a URL (where it would leak into history and server logs).
// Object URLs are cached by full request URL so list rerenders don't refetch.
const objectUrlCache = new Map<string, string>();
const inflight = new Map<string, Promise<string | null>>();

// A new cache-bust variant of the same path (e.g. after an avatar upload)
// supersedes older ones — revoke them so object URLs don't accumulate.
function evictStaleVariants(url: string) {
  const path = url.split('?')[0];
  for (const [key, objUrl] of objectUrlCache) {
    if (key !== url && key.split('?')[0] === path) {
      URL.revokeObjectURL(objUrl);
      objectUrlCache.delete(key);
    }
  }
}

async function fetchObjectUrl(url: string): Promise<string | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return null;
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    evictStaleVariants(url);
    objectUrlCache.set(url, objUrl);
    return objUrl;
  } catch {
    return null;
  }
}

/**
 * Resolve an authenticated image URL to a displayable object URL.
 * Returns undefined while loading or on failure (caller renders its fallback).
 */
export function useAuthedImage(url: string | undefined): string | undefined {
  const [, setLoaded] = useState('');

  useEffect(() => {
    if (!url || objectUrlCache.has(url)) return;
    let cancelled = false;
    let promise = inflight.get(url);
    if (!promise) {
      promise = fetchObjectUrl(url).finally(() => inflight.delete(url));
      inflight.set(url, promise);
    }
    promise.then(objUrl => {
      if (!cancelled && objUrl) setLoaded(url);
    });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return url ? objectUrlCache.get(url) : undefined;
}
