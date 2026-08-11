import { useCopyToClipboard } from '../../shared/useCopyToClipboard';
import { IconCheck, IconCopy } from '../../shared/icons';
import { INK_SOFT, LINE_STRONG, SAGE } from '../../shared/styles';

interface Props {
  /** Built lazily — the sheet copies live form state, not the saved row. */
  text: () => string;
  /** What this copies, for screen readers ("Copy the whole todo"). */
  label: string;
}

/**
 * The Copy affordance used twice in the edit sheet: once beside the heading for
 * the whole todo, once beside the next-action label for just that line.
 *
 * Sized for a thumb (36px tall) rather than for the 13px label it sits next to —
 * this is the one control on the sheet a phone user reaches for without meaning
 * to focus a field, so it must not be a mis-tap away from the input beside it.
 */
export function CopyButton({ text, label }: Props) {
  const { copied, copy } = useCopyToClipboard();

  return (
    <button
      type="button"
      onClick={() => copy(text())}
      aria-label={label}
      title={label}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        minHeight: 36, padding: '0 10px', borderRadius: 4,
        background: 'transparent',
        border: `1px solid ${copied ? SAGE : LINE_STRONG}`,
        color: copied ? SAGE : INK_SOFT,
        fontSize: 13, cursor: 'pointer', flexShrink: 0,
        // The label above it is uppercase-tracked; this reads as a control.
        letterSpacing: 0, textTransform: 'none',
      }}
    >
      {copied ? <IconCheck size={13} strokeWidth={2.5} /> : <IconCopy size={13} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
