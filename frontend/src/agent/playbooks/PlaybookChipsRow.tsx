/**
 * Chatty — quick-action chips above the chat input. Integration-gated chips
 * are disabled (not hidden) so the user learns the dependency.
 */

import { toast } from '../../shared/toast';
import { IconZap } from '../../shared/icons';
import { BG_RAISED, LINE, INK_MUTE, FONT_SANS } from '../../shared/styles';
import { useIsMobile } from '../../shared/useIsMobile';
import type { PlaybookSummary } from './types';
import { integrationLabel } from './types';

const DESKTOP_CAP = 4;

interface Props {
  playbooks: PlaybookSummary[];   // pre-filtered to chip-enabled, active
  disabled: boolean;              // isStreaming
  onInvoke: (p: PlaybookSummary) => void;
  onOverflow: () => void;         // "+N more" → open the slash menu
}

export function PlaybookChipsRow({ playbooks, disabled, onInvoke, onOverflow }: Props) {
  const isMobile = useIsMobile();
  if (playbooks.length === 0) return null;

  const sorted = [...playbooks].sort((a, b) => {
    if (a.last_used_at && b.last_used_at) return b.last_used_at.localeCompare(a.last_used_at);
    if (a.last_used_at) return -1;
    if (b.last_used_at) return 1;
    return a.name.localeCompare(b.name);
  });

  const shown = isMobile ? sorted : sorted.slice(0, DESKTOP_CAP);
  const overflow = isMobile ? 0 : sorted.length - shown.length;

  function handleClick(p: PlaybookSummary) {
    if (disabled) return;
    if (!p.available) {
      const needs = p.missing_integrations.map(integrationLabel).join(', ');
      toast.info(`“${p.name}” needs ${needs} connected. Connect it in Settings → Integrations.`);
      return;
    }
    onInvoke(p);
  }

  return (
    <div style={{
      display: 'flex', gap: 6, marginBottom: 8, padding: '0 4px',
      opacity: disabled ? 0.5 : 1,
      ...(isMobile
        ? { overflowX: 'auto' as const, flexWrap: 'nowrap' as const, WebkitOverflowScrolling: 'touch' as const }
        : { flexWrap: 'wrap' as const }),
    }}>
      {shown.map(p => (
        <button
          key={p.slug}
          onClick={() => handleClick(p)}
          title={p.available ? p.description : `Needs ${p.missing_integrations.map(integrationLabel).join(', ')}`}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 12px', background: BG_RAISED,
            border: `1px solid ${LINE}`, borderRadius: 999,
            fontSize: 12, color: INK_MUTE, fontFamily: FONT_SANS,
            cursor: disabled ? 'default' : 'pointer',
            whiteSpace: 'nowrap', flexShrink: 0,
            opacity: p.available ? 1 : 0.45,
          }}
          onMouseEnter={e => { if (!disabled) (e.currentTarget as HTMLElement).style.borderColor = 'rgba(230,235,242,0.14)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'rgba(230,235,242,0.07)'; }}
        >
          <IconZap size={12} strokeWidth={2} />
          {p.name}
          {!p.available && <span aria-hidden>⚠</span>}
        </button>
      ))}
      {overflow > 0 && (
        <button
          onClick={() => !disabled && onOverflow()}
          style={{
            padding: '5px 12px', background: 'transparent',
            border: `1px dashed ${LINE}`, borderRadius: 999,
            fontSize: 12, color: INK_MUTE, fontFamily: FONT_SANS,
            cursor: disabled ? 'default' : 'pointer',
            whiteSpace: 'nowrap', flexShrink: 0,
          }}
        >+{overflow} more</button>
      )}
    </div>
  );
}
