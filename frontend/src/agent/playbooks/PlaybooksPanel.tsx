/**
 * Chatty — Playbooks tab: per-agent procedure library with CRUD, chip toggles,
 * an archived section, and the "What I learned" feed.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { confirmDialog } from '../../shared/confirm';
import { toast } from '../../shared/toast';
import { LoadError } from '../../shared/LoadError';
import MarkdownContent from '../components/MarkdownContent';
import { IconChevron, IconZap } from '../../shared/icons';
import {
  INK, INK_MUTE, INK_DIM, LINE, LINE_STRONG, BG_CARD, BG_RAISED,
  ACCENT, ACCENT_INK, CORAL, SAGE, FONT_SANS, mono,
} from '../../shared/styles';
import type { PlaybookSummary, PlaybookDetail, PlaybookWrite } from './types';
import { integrationLabel } from './types';
import { PlaybookEditorModal } from './PlaybookEditorModal';
import { LearningFeed } from './LearningFeed';

interface Props {
  apiPrefix: string;
  agentName: string;
  playbooks: PlaybookSummary[];
  loading: boolean;
  loadFailed: boolean;
  onReload: () => void;
  onGetDetail: (slug: string) => Promise<PlaybookDetail>;
  onSave: (slug: string, data: Partial<PlaybookWrite>) => Promise<void>;
  onDelete: (slug: string) => Promise<void>;
  onToggleChip: (slug: string, chip: boolean) => Promise<void>;
  onRestore: (slug: string) => Promise<void>;
}

export function PlaybooksPanel({
  apiPrefix, agentName, playbooks, loading, loadFailed,
  onReload, onGetDetail, onSave, onDelete, onToggleChip, onRestore,
}: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlaybookDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; initial?: PlaybookDetail } | null>(null);
  const [feedCollapsed, setFeedCollapsed] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const expandSeqRef = useRef(0);

  // Pick up agent-created playbooks on every tab visit.
  useEffect(() => { onReload(); }, [onReload]);

  const active = playbooks.filter(p => !p.archived);
  const archived = playbooks.filter(p => p.archived);

  const handleExpand = useCallback(async (slug: string) => {
    if (expanded === slug) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    const seq = ++expandSeqRef.current;
    setExpanded(slug);
    setDetail(null);
    setDetailLoading(true);
    try {
      const d = await onGetDetail(slug);
      if (seq === expandSeqRef.current) setDetail(d);
    } catch {
      if (seq === expandSeqRef.current) {
        setExpanded(null);
        toast.error('Failed to load playbook.');
      }
    } finally {
      if (seq === expandSeqRef.current) setDetailLoading(false);
    }
  }, [expanded, onGetDetail]);

  async function handleEdit(slug: string) {
    try {
      const d = await onGetDetail(slug);
      setEditor({ mode: 'edit', initial: d });
    } catch {
      toast.error('Failed to load playbook.');
    }
  }

  async function handleDelete(pb: PlaybookSummary) {
    const ok = await confirmDialog({
      title: 'Delete playbook',
      message: `“${pb.name}” will be permanently deleted.`,
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await onDelete(pb.slug);
      if (expanded === pb.slug) { setExpanded(null); setDetail(null); }
      toast.success('Playbook deleted.');
    } catch {
      toast.error('Failed to delete playbook.');
    }
  }

  async function handleChipToggle(pb: PlaybookSummary) {
    try {
      await onToggleChip(pb.slug, !pb.chip);
    } catch {
      toast.error('Failed to update quick action.');
    }
  }

  async function handleRestore(pb: PlaybookSummary) {
    try {
      await onRestore(pb.slug);
      toast.success('Playbook restored.');
    } catch {
      toast.error('Failed to restore playbook.');
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '48px 0', textAlign: 'center', fontSize: 13, color: INK_DIM, fontFamily: FONT_SANS }}>
        Loading playbooks...
      </div>
    );
  }

  if (loadFailed && playbooks.length === 0) {
    return <LoadError label="Couldn't load playbooks" onRetry={onReload} />;
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 20px 60px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={mono(10)}>Playbooks ({active.length})</span>
        <button
          onClick={() => setEditor({ mode: 'create' })}
          style={{
            background: ACCENT, border: 'none', color: ACCENT_INK,
            borderRadius: 4, padding: '7px 14px', fontSize: 13,
            cursor: 'pointer', fontFamily: FONT_SANS,
          }}
        >New playbook</button>
      </div>

      {/* Empty state */}
      {active.length === 0 && (
        <div style={{
          padding: '40px 20px', textAlign: 'center',
          border: `1px dashed ${LINE_STRONG}`, borderRadius: 8,
          marginBottom: 24,
        }}>
          <div style={{ fontSize: 14, color: INK_MUTE, fontFamily: FONT_SANS, marginBottom: 6 }}>
            No playbooks yet.
          </div>
          <div style={{ fontSize: 13, color: INK_DIM, fontFamily: FONT_SANS, lineHeight: 1.5, maxWidth: 440, margin: '0 auto' }}>
            Playbooks are step-by-step procedures {agentName} can run on demand.
            Create one, or {agentName} will write its own as it learns your routines.
          </div>
        </div>
      )}

      {/* Active playbook rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 32 }}>
        {active.map(pb => (
          <div
            key={pb.slug}
            style={{
              background: BG_CARD, border: `1px solid ${LINE_STRONG}`,
              borderRadius: 8, overflow: 'hidden',
            }}
          >
            <div
              onClick={() => handleExpand(pb.slug)}
              style={{ padding: '12px 16px', cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{
                  color: INK_DIM, display: 'flex',
                  transform: expanded === pb.slug ? 'rotate(0deg)' : 'rotate(-90deg)',
                  transition: 'transform 0.15s',
                }}>
                  <IconChevron size={14} strokeWidth={2} />
                </span>
                <span style={{ fontSize: 14, color: INK, fontFamily: FONT_SANS }}>{pb.name}</span>
                <span style={{
                  ...mono(9, pb.created_by === 'user' ? INK_DIM : SAGE),
                  padding: '2px 7px', borderRadius: 999,
                  background: pb.created_by === 'user' ? BG_RAISED : 'rgba(142,165,137,0.12)',
                }}>
                  {pb.created_by === 'user' ? 'You' : agentName}
                </span>
                {pb.missing_integrations.map(mi => (
                  <span key={mi} style={{
                    ...mono(9, CORAL), padding: '2px 7px', borderRadius: 999,
                    background: 'rgba(217,119,87,0.1)',
                  }}>
                    Needs {integrationLabel(mi)}
                  </span>
                ))}
                <span style={{ flex: 1 }} />
                {pb.use_count > 0 && (
                  <span style={mono(9, INK_DIM)}>
                    {pb.use_count} {pb.use_count === 1 ? 'run' : 'runs'}
                  </span>
                )}
              </div>
              <div style={{
                fontSize: 12, color: INK_MUTE, fontFamily: FONT_SANS,
                marginTop: 4, marginLeft: 22,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {pb.description}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8, marginLeft: 22 }}>
                <button
                  onClick={e => { e.stopPropagation(); handleChipToggle(pb); }}
                  title="Show as a quick-action button above the chat input"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    background: pb.chip ? ACCENT : 'transparent',
                    color: pb.chip ? ACCENT_INK : INK_MUTE,
                    border: `1px solid ${pb.chip ? ACCENT : LINE_STRONG}`,
                    borderRadius: 999, padding: '3px 10px',
                    fontSize: 11, cursor: 'pointer', fontFamily: FONT_SANS,
                  }}
                >
                  <IconZap size={11} strokeWidth={2} />
                  Quick action
                </button>
                <span style={{ flex: 1 }} />
                <button
                  onClick={e => { e.stopPropagation(); handleEdit(pb.slug); }}
                  style={{
                    background: 'none', border: 'none', color: INK_MUTE,
                    fontSize: 12, cursor: 'pointer', fontFamily: FONT_SANS,
                  }}
                >Edit</button>
                <button
                  onClick={e => { e.stopPropagation(); handleDelete(pb); }}
                  onMouseEnter={e => { (e.target as HTMLElement).style.color = '#D97757'; }}
                  onMouseLeave={e => { (e.target as HTMLElement).style.color = 'rgba(237,240,244,0.62)'; }}
                  style={{
                    background: 'none', border: 'none', color: INK_MUTE,
                    fontSize: 12, cursor: 'pointer', fontFamily: FONT_SANS,
                  }}
                >Delete</button>
              </div>
            </div>
            {expanded === pb.slug && (
              <div style={{ borderTop: `1px solid ${LINE}`, padding: '14px 16px 16px 38px' }}>
                {detailLoading ? (
                  <div style={{ fontSize: 12, color: INK_DIM, fontFamily: FONT_SANS }}>Loading…</div>
                ) : detail ? (
                  <MarkdownContent content={detail.body} />
                ) : null}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Archived section */}
      {archived.length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <button
            onClick={() => setShowArchived(s => !s)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: 'none', border: 'none', cursor: 'pointer',
              padding: 0, marginBottom: 10,
            }}
          >
            <span style={{
              color: INK_DIM, display: 'flex',
              transform: showArchived ? 'rotate(0deg)' : 'rotate(-90deg)',
              transition: 'transform 0.15s',
            }}>
              <IconChevron size={12} strokeWidth={2} />
            </span>
            <span style={mono(10)}>Archived ({archived.length})</span>
          </button>
          {showArchived && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {archived.map(pb => (
                <div
                  key={pb.slug}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', background: BG_CARD,
                    border: `1px solid ${LINE}`, borderRadius: 6, opacity: 0.7,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 13, color: INK_MUTE, fontFamily: FONT_SANS }}>{pb.name}</span>
                    <span style={{ fontSize: 12, color: INK_DIM, fontFamily: FONT_SANS, marginLeft: 10 }}>
                      {pb.description}
                    </span>
                  </div>
                  <button
                    onClick={() => handleRestore(pb)}
                    style={{
                      background: 'none', border: `1px solid ${LINE_STRONG}`, color: INK_MUTE,
                      borderRadius: 4, padding: '3px 10px', fontSize: 11,
                      cursor: 'pointer', fontFamily: FONT_SANS, flexShrink: 0,
                    }}
                  >Restore</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* What I learned */}
      <div>
        <button
          onClick={() => setFeedCollapsed(c => !c)}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', cursor: 'pointer',
            padding: 0, marginBottom: 10,
          }}
        >
          <span style={{
            color: INK_DIM, display: 'flex',
            transform: feedCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.15s',
          }}>
            <IconChevron size={12} strokeWidth={2} />
          </span>
          <span style={mono(10)}>What {agentName} learned</span>
        </button>
        {!feedCollapsed && (
          <LearningFeed apiPrefix={apiPrefix} agentName={agentName} onAfterRevert={onReload} />
        )}
      </div>

      {/* Editor modal */}
      {editor && (
        <PlaybookEditorModal
          mode={editor.mode}
          initial={editor.initial}
          existingSlugs={playbooks.map(p => p.slug)}
          onSave={async (slug, data) => {
            await onSave(slug, data);
            toast.success(editor.mode === 'create' ? 'Playbook created.' : 'Playbook saved.');
            if (expanded === slug) { setExpanded(null); setDetail(null); }
          }}
          onClose={() => setEditor(null)}
        />
      )}
    </div>
  );
}
