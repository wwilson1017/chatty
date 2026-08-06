import { useCallback, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { todoApi } from '../api';
import { toast } from '../../shared/toast';
import { BG_RAISED, INK, SAGE } from '../../shared/styles';

interface Props {
  todoId: number;
  title: string;
  /** Typography of the static text — the editor mirrors it so nothing jumps. */
  style: CSSProperties;
  /** Called after a successful rename. */
  onSaved: () => void;
  /** Wrapping editor for headings; single-line input otherwise. */
  multiline?: boolean;
}

// The click target and the editor share this box so swapping between them
// leaves the surrounding layout exactly where it was.
const BOX: CSSProperties = {
  padding: '1px 5px', margin: '-1px -5px',
  borderRadius: 3, border: '1px solid transparent',
};

/**
 * Click-to-rename title. Editing happens in place — Enter or clicking away
 * saves, Escape reverts. The full editor stays available elsewhere for the
 * fields that don't fit on a row.
 */
export function InlineTitle({ todoId, title, style, onSaved, multiline = false }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [saving, setSaving] = useState(false);
  // Escape and Enter both close the editor, and closing blurs it — this keeps
  // the trailing blur from re-running (or undoing) the decision already made.
  const closed = useRef(false);

  // Stable identity, so React only runs this on mount — a per-render callback
  // would re-place the caret on every keystroke.
  const focusEnd = useCallback((el: HTMLInputElement | HTMLTextAreaElement | null) => {
    if (!el) return;
    el.focus();
    // Caret at the end — clicking in to amend a title is the common case.
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  function start(e: React.MouseEvent) {
    e.stopPropagation();
    if (saving) return;
    setDraft(title);
    closed.current = false;
    setEditing(true);
  }

  function finish(commit: boolean) {
    if (closed.current) return;
    closed.current = true;
    setEditing(false);
    const next = draft.trim();
    // An emptied title is a slip, not a request — the API rejects it anyway.
    if (commit && next && next !== title) save(next);
  }

  async function save(next: string) {
    setSaving(true);
    try {
      await todoApi(`/api/todo/todos/${todoId}`, {
        method: 'PUT', body: JSON.stringify({ title: next }),
      });
      onSaved();
    } catch {
      toast.error('Failed to rename todo.');
    }
    setSaving(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    // Shift+Enter is the newline escape hatch in the wrapping editor.
    else if (e.key === 'Enter' && !(multiline && e.shiftKey)) { e.preventDefault(); finish(true); }
  }

  if (editing) {
    const editorProps = {
      value: draft,
      'aria-label': 'Todo title',
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft(e.target.value),
      onKeyDown,
      onBlur: () => finish(true),
      onClick: (e: React.MouseEvent) => e.stopPropagation(),
      style: {
        ...style, ...BOX,
        background: BG_RAISED, borderColor: SAGE, color: INK,
        outline: 'none', textDecoration: 'none', textOverflow: 'clip',
        width: '100%', boxSizing: 'border-box' as const,
      },
    };
    return multiline
      ? <textarea ref={focusEnd} rows={2} {...editorProps} style={{ ...editorProps.style, resize: 'vertical' }} />
      : <input ref={focusEnd} type="text" {...editorProps} />;
  }

  return (
    <span
      role="button"
      tabIndex={0}
      title="Click to rename"
      onClick={start}
      onKeyDown={e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        start(e as unknown as React.MouseEvent);
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = SAGE; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'transparent'; }}
      style={{
        ...style, ...BOX, cursor: 'text', opacity: saving ? 0.5 : 1,
        // Hug the text: the blank space beside a title belongs to the row, so
        // clicking there still opens the full editor.
        display: 'inline-block', maxWidth: '100%', verticalAlign: 'bottom',
      }}
    >{title}</span>
  );
}
