import { useState, useRef, useEffect } from 'react';
import type { ParsedLine } from '../../hooks/useHeartbeat';
import { FONT_SANS, FONT_MONO, INK, INK_DIM, INK_MUTE, BG_ELEV, BG_RAISED, LINE_STRONG, ACCENT, ACCENT_INK, SAGE } from '../../../shared/styles';

interface Props {
  parsedLines: ParsedLine[];
  canEditCards: boolean;
  rawMarkdown: string;
  onSave: (lines: ParsedLine[]) => Promise<void>;
  onSaveRaw: (raw: string) => Promise<void>;
}

export function HeartbeatChecklist({ parsedLines, canEditCards, rawMarkdown, onSave, onSaveRaw }: Props) {
  const [localLines, setLocalLines] = useState<ParsedLine[]>(parsedLines);
  const [rawText, setRawText] = useState(rawMarkdown);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [addingNew, setAddingNew] = useState(false);
  const [newText, setNewText] = useState('');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [rawDirty, setRawDirty] = useState(false);
  const newInputRef = useRef<HTMLInputElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setLocalLines(parsedLines); setDirty(false); }, [parsedLines]);
  useEffect(() => { setRawText(rawMarkdown); setRawDirty(false); }, [rawMarkdown]);
  useEffect(() => { if (addingNew) newInputRef.current?.focus(); }, [addingNew]);
  useEffect(() => { if (editingId) editInputRef.current?.focus(); }, [editingId]);

  const items = localLines.filter(l => l.type === 'list-item');

  function startEdit(item: ParsedLine) {
    setEditingId(item.id!);
    setEditText(item.text || '');
  }

  function commitEdit() {
    if (!editingId) return;
    const updated = localLines.map(l =>
      l.id === editingId ? { ...l, text: editText.trim() || l.text } : l,
    );
    setLocalLines(updated);
    setEditingId(null);
    setDirty(true);
  }

  function deleteItem(id: string) {
    setLocalLines(prev => prev.filter(l => l.id !== id));
    setDirty(true);
  }

  function addItem() {
    if (!newText.trim()) { setAddingNew(false); return; }
    const line: ParsedLine = {
      type: 'list-item', raw: `- ${newText.trim()}`,
      prefix: '- ', text: newText.trim(), id: crypto.randomUUID(),
    };
    setLocalLines(prev => [...prev, line]);
    setNewText('');
    setAddingNew(false);
    setDirty(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(localLines);
      setDirty(false);
    } finally { setSaving(false); }
  }

  async function handleSaveRaw() {
    setSaving(true);
    try {
      await onSaveRaw(rawText);
      setRawDirty(false);
    } finally { setSaving(false); }
  }

  // Raw markdown editor fallback
  if (!canEditCards && rawMarkdown) {
    return (
      <div style={{ padding: '16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase', color: INK_DIM }}>
            CHECKLIST
          </span>
          {rawDirty && (
            <button onClick={handleSaveRaw} disabled={saving} style={{
              fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500,
              padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
              background: ACCENT, color: ACCENT_INK, border: 'none',
              opacity: saving ? 0.5 : 1,
            }}>
              {saving ? 'Saving...' : 'Save'}
            </button>
          )}
        </div>
        <textarea
          value={rawText}
          onChange={e => { setRawText(e.target.value); setRawDirty(true); }}
          style={{
            width: '100%', minHeight: 200, boxSizing: 'border-box',
            fontFamily: FONT_SANS, fontSize: 13, lineHeight: 1.6,
            background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
            color: INK, borderRadius: 6, padding: 12, resize: 'vertical', outline: 'none',
          }}
        />
      </div>
    );
  }

  // Card editor
  return (
    <div style={{ padding: '16px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase', color: INK_DIM }}>
          CHECKLIST
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {dirty && (
            <button onClick={handleSave} disabled={saving} style={{
              fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500,
              padding: '4px 12px', borderRadius: 4, cursor: 'pointer',
              background: ACCENT, color: ACCENT_INK, border: 'none',
              opacity: saving ? 0.5 : 1,
            }}>
              {saving ? 'Saving...' : 'Save'}
            </button>
          )}
          {!addingNew && (
            <button onClick={() => setAddingNew(true)} style={{
              fontFamily: FONT_SANS, fontSize: 12, color: INK_MUTE,
              background: 'none', border: `1px solid ${LINE_STRONG}`,
              borderRadius: 4, padding: '4px 12px', cursor: 'pointer',
            }}>
              + Add Item
            </button>
          )}
        </div>
      </div>

      {items.length === 0 && !addingNew ? (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <p style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK_DIM }}>No checklist items yet.</p>
          <button
            onClick={() => setAddingNew(true)}
            style={{
              marginTop: 8, fontFamily: FONT_SANS, fontSize: 13, color: ACCENT,
              background: 'none', border: 'none', cursor: 'pointer',
            }}
          >Add your first task</button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map(item => (
            <div
              key={item.id}
              className="group"
              style={{
                background: BG_ELEV, border: `1px solid ${LINE_STRONG}`,
                borderRadius: 6, padding: '10px 14px',
                display: 'flex', alignItems: 'center', gap: 10,
              }}
            >
              {/* Checkbox dot */}
              <div
                onClick={() => {
                  if (item.checked === undefined) return;
                  const updated = localLines.map(l =>
                    l.id === item.id ? { ...l, checked: !l.checked } : l,
                  );
                  setLocalLines(updated);
                  setDirty(true);
                }}
                style={{
                  width: 16, height: 16, borderRadius: 3, flexShrink: 0,
                  border: `1.5px solid ${item.checked ? SAGE : LINE_STRONG}`,
                  background: item.checked ? SAGE : 'transparent',
                  cursor: item.checked !== undefined ? 'pointer' : 'default',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {item.checked && (
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M2 5l2.5 2.5L8 3" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>

              {/* Text or edit input */}
              {editingId === item.id ? (
                <input
                  ref={editInputRef}
                  value={editText}
                  onChange={e => setEditText(e.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={e => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditingId(null); }}
                  style={{
                    flex: 1, fontFamily: FONT_SANS, fontSize: 13, color: INK,
                    background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
                    borderRadius: 4, padding: '4px 8px', outline: 'none',
                  }}
                />
              ) : (
                <span
                  onDoubleClick={() => startEdit(item)}
                  style={{
                    flex: 1, fontFamily: FONT_SANS, fontSize: 13, color: INK,
                    textDecoration: item.checked ? 'line-through' : 'none',
                    opacity: item.checked ? 0.5 : 1,
                  }}
                >{item.text}</span>
              )}

              {/* Edit / delete actions */}
              <div className="opacity-0 group-hover:opacity-100 transition-opacity" style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                <button
                  onClick={() => startEdit(item)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: INK_DIM, padding: 2 }}
                  title="Edit"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                  </svg>
                </button>
                <button
                  onClick={() => deleteItem(item.id!)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: INK_DIM, padding: 2 }}
                  title="Delete"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add new item input */}
      {addingNew && (
        <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
          <input
            ref={newInputRef}
            value={newText}
            onChange={e => setNewText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addItem(); if (e.key === 'Escape') { setAddingNew(false); setNewText(''); } }}
            placeholder="Describe a task for the agent to check..."
            style={{
              flex: 1, fontFamily: FONT_SANS, fontSize: 13, color: INK,
              background: BG_RAISED, border: `1px solid ${LINE_STRONG}`,
              borderRadius: 4, padding: '8px 12px', outline: 'none',
            }}
          />
          <button onClick={addItem} style={{
            fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500,
            padding: '6px 14px', borderRadius: 4, cursor: 'pointer',
            background: ACCENT, color: ACCENT_INK, border: 'none',
          }}>Add</button>
        </div>
      )}
    </div>
  );
}
