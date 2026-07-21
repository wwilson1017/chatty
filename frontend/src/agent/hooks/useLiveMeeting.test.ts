import { describe, expect, it } from 'vitest';
import { backoffDelay, extForMime, formatElapsed, pickAudioMime } from './useLiveMeeting';
import { insertMessage, type ChatMessage } from './useAgentChat';

describe('pickAudioMime', () => {
  it('picks webm/opus on Chrome-like browsers', () => {
    expect(pickAudioMime(t => t.startsWith('audio/webm'))).toBe('audio/webm;codecs=opus');
  });
  it('picks mp4 on Safari-like browsers', () => {
    expect(pickAudioMime(t => t === 'audio/mp4')).toBe('audio/mp4');
  });
  it('returns undefined when nothing is supported (browser default)', () => {
    expect(pickAudioMime(() => false)).toBeUndefined();
  });
});

describe('extForMime', () => {
  it.each([
    ['audio/webm;codecs=opus', 'webm'],
    ['audio/mp4', 'mp4'],
    ['audio/ogg;codecs=opus', 'ogg'],
    ['audio/wav', 'wav'],
    ['', 'webm'],
  ])('%s → %s', (mime, ext) => {
    expect(extForMime(mime)).toBe(ext);
  });
});

describe('backoffDelay', () => {
  it('doubles from 1s and caps at 15s', () => {
    expect([0, 1, 2, 3, 4, 10].map(backoffDelay))
      .toEqual([1000, 2000, 4000, 8000, 15000, 15000]);
  });
});

describe('formatElapsed', () => {
  it.each([
    [0, '0:00'],
    [65, '1:05'],
    [605, '10:05'],
    [3661, '1:01:01'],
  ])('%d s → %s', (sec, out) => {
    expect(formatElapsed(sec)).toBe(out);
  });
});

describe('insertMessage', () => {
  const msg = (id: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    id, role: 'assistant', content: `c-${id}`, timestamp: 1, ...extra,
  });

  it('appends when the tail is not streaming', () => {
    const list = [msg('a'), msg('b')];
    const out = insertMessage(list, msg('coach'));
    expect(out.map(m => m.id)).toEqual(['a', 'b', 'coach']);
  });

  it('inserts before a streaming tail (never corrupts the in-flight reply)', () => {
    const list = [msg('a'), msg('b', { isStreaming: true })];
    const out = insertMessage(list, msg('coach'));
    expect(out.map(m => m.id)).toEqual(['a', 'coach', 'b']);
    expect(out[2].isStreaming).toBe(true);
  });

  it('drops duplicates by id (SSE replay × history reload overlap)', () => {
    const list = [msg('a'), msg('coach')];
    expect(insertMessage(list, msg('coach'))).toBe(list);
  });

  it('appends to an empty list', () => {
    expect(insertMessage([], msg('coach')).map(m => m.id)).toEqual(['coach']);
  });
});
