/**
 * Chatty — "What I learned" feed: autonomous playbook/memory writes from the
 * background review, each revertible with one click.
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '../../core/api/client';
import { confirmDialog } from '../../shared/confirm';
import { toast } from '../../shared/toast';
import { LoadError } from '../../shared/LoadError';
import { IconBook, IconBrain, IconLock } from '../../shared/icons';
import { INK_MUTE, INK_DIM, LINE, BG_CARD, CORAL, SAGE, FONT_SANS, mono } from '../../shared/styles';
import { timeAgo } from '../utils/dateFormat';
import type { LearningEvent } from './types';

const PAGE_SIZE = 50;

const KIND_LABELS: Record<LearningEvent['event_type'], string> = {
  playbook_created: 'New playbook',
  playbook_updated: 'Playbook updated',
  playbook_archived: 'Playbook archived',
  fact_added: 'Memory updated',
  blocked_injection: 'Blocked unsafe learning',
};

function kindIcon(kind: LearningEvent['event_type']) {
  if (kind === 'fact_added') return <IconBrain size={14} strokeWidth={1.75} />;
  if (kind === 'blocked_injection') return <IconLock size={14} strokeWidth={1.75} />;
  return <IconBook size={14} strokeWidth={1.75} />;
}

interface Props {
  apiPrefix: string;
  agentName: string;
  onAfterRevert: () => void;
}

export function LearningFeed({ apiPrefix, agentName, onAfterRevert }: Props) {
  const [events, setEvents] = useState<LearningEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [reverting, setReverting] = useState<number | null>(null);

  const load = useCallback(async (offset: number) => {
    try {
      const data = await api<{ events: LearningEvent[] }>(
        `${apiPrefix}/learning-events?limit=${PAGE_SIZE}&offset=${offset}`,
      );
      setEvents(prev => (offset === 0 ? data.events : [...prev, ...data.events]));
      setHasMore(data.events.length === PAGE_SIZE);
      setLoadFailed(false);
    } catch {
      if (offset === 0) setLoadFailed(true);
      else toast.error('Failed to load more events.');
    } finally {
      setLoading(false);
    }
  }, [apiPrefix]);

  useEffect(() => {
    setLoading(true);
    setEvents([]);
    load(0);
  }, [load]);

  async function handleRevert(ev: LearningEvent) {
    const ok = await confirmDialog({
      title: 'Revert this change?',
      message: `“${ev.title}” will be restored to how it was before ${agentName} changed it.`,
      confirmLabel: 'Revert',
      danger: true,
    });
    if (!ok) return;
    setReverting(ev.id);
    try {
      await api(`${apiPrefix}/learning-events/${ev.id}/revert`, { method: 'POST' });
      setEvents(prev => prev.map(e =>
        e.id === ev.id ? { ...e, reverted_at: new Date().toISOString() } : e,
      ));
      toast.success('Reverted.');
      onAfterRevert();
    } catch {
      toast.error('Failed to revert.');
    } finally {
      setReverting(null);
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '24px 0', textAlign: 'center', fontSize: 13, color: INK_DIM, fontFamily: FONT_SANS }}>
        Loading…
      </div>
    );
  }

  if (loadFailed) {
    return <LoadError label="Couldn't load learning events" compact onRetry={() => { setLoading(true); load(0); }} />;
  }

  if (events.length === 0) {
    return (
      <div style={{ padding: '20px 4px', fontSize: 13, color: INK_DIM, fontFamily: FONT_SANS, lineHeight: 1.5 }}>
        Nothing learned yet. As {agentName} works with you, new playbooks and memory
        updates will appear here — and you can undo any of them with one click.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {events.map(ev => {
        const reverted = !!ev.reverted_at;
        const revertible = !reverted
          && ev.event_type !== 'blocked_injection'
          && !(ev.event_type === 'playbook_updated' && !ev.before_preview);
        return (
          <div
            key={ev.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 14px', background: BG_CARD,
              border: `1px solid ${LINE}`, borderRadius: 6,
              opacity: reverted ? 0.5 : 1,
            }}
          >
            <span style={{ color: INK_DIM, flexShrink: 0, display: 'flex' }}>
              {kindIcon(ev.event_type)}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                <span style={mono(9, ev.event_type === 'blocked_injection' ? CORAL : SAGE)}>
                  {KIND_LABELS[ev.event_type]}
                </span>
                <span style={{ fontSize: 11, color: INK_DIM, fontFamily: FONT_SANS }}>
                  {timeAgo(ev.created_at)}
                </span>
              </div>
              <div style={{
                fontSize: 13, color: INK_MUTE, fontFamily: FONT_SANS,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                textDecoration: reverted ? 'line-through' : 'none',
              }}>
                {ev.title}
              </div>
            </div>
            {reverted ? (
              <span style={{ ...mono(9, INK_DIM), flexShrink: 0 }}>Reverted</span>
            ) : revertible ? (
              <button
                onClick={() => handleRevert(ev)}
                disabled={reverting === ev.id}
                onMouseEnter={e => { (e.target as HTMLElement).style.color = '#D97757'; }}
                onMouseLeave={e => { (e.target as HTMLElement).style.color = 'rgba(237,240,244,0.62)'; }}
                style={{
                  background: 'none', border: 'none', color: INK_MUTE,
                  fontSize: 12, cursor: 'pointer', fontFamily: FONT_SANS,
                  flexShrink: 0, padding: '2px 6px',
                  opacity: reverting === ev.id ? 0.5 : 1,
                }}
              >Revert</button>
            ) : null}
          </div>
        );
      })}
      {hasMore && (
        <button
          onClick={() => load(events.length)}
          style={{
            background: 'none', border: `1px solid ${LINE}`, color: INK_MUTE,
            borderRadius: 4, padding: '6px 0', fontSize: 12, cursor: 'pointer',
            fontFamily: FONT_SANS,
          }}
        >Show more</button>
      )}
    </div>
  );
}
