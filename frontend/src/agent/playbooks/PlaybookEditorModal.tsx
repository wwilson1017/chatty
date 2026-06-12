/**
 * Chatty — Playbook create/edit modal.
 * Simple by design (non-technical audience): name, description, plain-language
 * steps textarea, quick-action checkbox. Required integrations are agent/file
 * territory and round-trip unchanged.
 */

import { useState } from 'react';
import { confirmDialog } from '../../shared/confirm';
import {
  INK, INK_MUTE, INK_DIM, LINE_STRONG, BG_ELEV, ACCENT, ACCENT_INK, CORAL,
  FONT_SANS, labelStyle, inputStyle,
} from '../../shared/styles';
import { useIsMobile } from '../../shared/useIsMobile';
import type { PlaybookDetail, PlaybookWrite } from './types';

// Must match backend slugify (core/agents/playbooks/service.py) — used only for
// collision preview; the backend re-derives the slug authoritatively.
function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
}

interface Props {
  mode: 'create' | 'edit';
  initial?: PlaybookDetail;
  existingSlugs: string[];
  onSave: (slug: string, data: Partial<PlaybookWrite>) => Promise<void>;
  onClose: () => void;
}

export function PlaybookEditorModal({ mode, initial, existingSlugs, onSave, onClose }: Props) {
  const [name, setName] = useState(initial?.meta.name || '');
  const [description, setDescription] = useState(initial?.meta.description || '');
  const [body, setBody] = useState(initial?.body || '');
  const [chip, setChip] = useState(initial?.meta.chip ?? false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isMobile = useIsMobile();

  const dirty = mode === 'create'
    ? !!(name || description || body)
    : name !== initial?.meta.name || description !== initial?.meta.description
      || body !== initial?.body || chip !== (initial?.meta.chip ?? false);

  const slug = mode === 'edit' ? initial!.slug : slugify(name);
  const slugCollision = mode === 'create' && !!slug && existingSlugs.includes(slug);
  const valid = !!name.trim() && !!description.trim() && !!body.trim() && !slugCollision;

  async function handleClose() {
    if (dirty && !saving) {
      const ok = await confirmDialog({
        title: 'Discard changes',
        message: 'Your edits to this playbook will be lost.',
        confirmLabel: 'Discard',
        danger: true,
      });
      if (!ok) return;
    }
    onClose();
  }

  async function handleSave() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(slug, {
        name: name.trim(),
        description: description.trim(),
        content: body,
        chip,
        ...(mode === 'create' ? { integrations: [] } : {}),
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save playbook.');
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 50,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={handleClose}
    >
      <div
        style={{
          background: BG_ELEV, border: `1px solid ${LINE_STRONG}`,
          borderRadius: 6, boxShadow: '0 12px 60px rgba(0,0,0,0.6)',
          width: '100%', maxWidth: 640,
          margin: isMobile ? '0 16px' : 0,
          maxHeight: '85vh', display: 'flex', flexDirection: 'column',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px', borderBottom: `1px solid ${LINE_STRONG}`,
        }}>
          <h3 style={{ margin: 0, fontSize: 16, color: INK, fontWeight: 500, fontFamily: FONT_SANS }}>
            {mode === 'create' ? 'New playbook' : 'Edit playbook'}
          </h3>
          <button
            onClick={handleClose}
            style={{ background: 'none', border: 'none', color: INK_DIM, fontSize: 20, cursor: 'pointer', lineHeight: 1 }}
          >&times;</button>
        </div>

        <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
          <label style={labelStyle}>Name</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            maxLength={80}
            autoFocus
            placeholder="e.g. Chase overdue invoices"
            style={{ ...inputStyle, marginBottom: slugCollision ? 4 : 16 }}
          />
          {slugCollision && (
            <div style={{ fontSize: 12, color: CORAL, marginBottom: 12, fontFamily: FONT_SANS }}>
              A playbook with this name already exists.
            </div>
          )}

          <label style={labelStyle}>Description</label>
          <input
            value={description}
            onChange={e => setDescription(e.target.value)}
            maxLength={200}
            placeholder="One sentence: when does this apply?"
            style={{ ...inputStyle, marginBottom: 4 }}
          />
          <div style={{ fontSize: 11, color: INK_DIM, marginBottom: 16, fontFamily: FONT_SANS }}>
            Shown in the / menu and on quick-action chips.
          </div>

          <label style={labelStyle}>Steps</label>
          <textarea
            value={body}
            onChange={e => setBody(e.target.value)}
            placeholder={'Write the steps in plain language, one per line. e.g.\n1. Search Gmail for unpaid invoices\n2. Draft a friendly reminder for each…'}
            style={{
              ...inputStyle,
              minHeight: 240, resize: 'vertical', lineHeight: 1.5,
              marginBottom: 16,
            }}
          />

          <label style={{
            display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
            fontSize: 13, color: INK_MUTE, fontFamily: FONT_SANS,
          }}>
            <input
              type="checkbox"
              checked={chip}
              onChange={e => setChip(e.target.checked)}
              style={{ accentColor: '#C8D1D9' }}
            />
            Show as a quick action above chat
          </label>

          {error && (
            <div style={{ fontSize: 12, color: CORAL, marginTop: 12, fontFamily: FONT_SANS }}>
              {error}
            </div>
          )}
        </div>

        <div style={{
          display: 'flex', justifyContent: 'flex-end', gap: 10,
          padding: '14px 20px', borderTop: `1px solid ${LINE_STRONG}`,
        }}>
          <button
            onClick={handleClose}
            style={{
              background: 'transparent', border: `1px solid ${LINE_STRONG}`,
              color: INK_MUTE, borderRadius: 4, padding: '7px 16px',
              fontSize: 13, cursor: 'pointer', fontFamily: FONT_SANS,
            }}
          >Cancel</button>
          <button
            onClick={handleSave}
            disabled={!valid || saving}
            style={{
              background: ACCENT, border: 'none', color: ACCENT_INK,
              borderRadius: 4, padding: '7px 16px', fontSize: 13,
              cursor: !valid || saving ? 'default' : 'pointer',
              opacity: !valid || saving ? 0.5 : 1, fontFamily: FONT_SANS,
            }}
          >{saving ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}</button>
        </div>
      </div>
    </div>
  );
}
