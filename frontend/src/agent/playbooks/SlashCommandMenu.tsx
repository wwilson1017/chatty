/**
 * Chatty — "/" slash-command dropdown listing playbooks. Pure presentational;
 * the open/filter/highlight state machine lives in AgentChatPanel.
 */

import { INK, INK_MUTE, INK_DIM, LINE_STRONG, BG_ELEV, ACCENT_SOFT, CORAL, FONT_SANS, mono } from '../../shared/styles';
import type { PlaybookSummary } from './types';
import { integrationLabel } from './types';

interface Props {
  matches: PlaybookSummary[];
  highlightIndex: number;
  onHighlight: (index: number) => void;
  onSelect: (p: PlaybookSummary) => void;
  onManage: () => void;
}

export function SlashCommandMenu({ matches, highlightIndex, onHighlight, onSelect, onManage }: Props) {
  return (
    <div style={{
      position: 'absolute', bottom: '100%', left: 0, right: 0, marginBottom: 8,
      maxHeight: 280, overflowY: 'auto',
      background: BG_ELEV, border: `1px solid ${LINE_STRONG}`,
      borderRadius: 6, boxShadow: '0 8px 40px rgba(0,0,0,0.5)', zIndex: 30,
    }}>
      <div style={{ ...mono(9, INK_DIM), padding: '8px 14px 4px' }}>Playbooks</div>
      {matches.length === 0 && (
        <div style={{ padding: '8px 14px', fontSize: 13, color: INK_DIM, fontFamily: FONT_SANS }}>
          No playbooks match
        </div>
      )}
      {matches.map((p, i) => (
        <div
          key={p.slug}
          onMouseEnter={() => onHighlight(i)}
          onMouseDown={e => { e.preventDefault(); onSelect(p); }}
          style={{
            padding: '8px 14px',
            background: i === highlightIndex ? ACCENT_SOFT : 'transparent',
            cursor: p.available ? 'pointer' : 'default',
            opacity: p.available ? 1 : 0.45,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 13, color: INK, fontFamily: FONT_SANS }}>{p.name}</span>
            {!p.available && (
              <span style={mono(9, CORAL)}>
                Needs {p.missing_integrations.map(integrationLabel).join(', ')}
              </span>
            )}
          </div>
          <div style={{
            fontSize: 11, color: INK_MUTE, fontFamily: FONT_SANS,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {p.description}
          </div>
        </div>
      ))}
      <div
        onMouseDown={e => { e.preventDefault(); onManage(); }}
        style={{
          padding: '8px 14px', borderTop: `1px solid rgba(230,235,242,0.07)`,
          fontSize: 12, color: INK_DIM, fontFamily: FONT_SANS, cursor: 'pointer',
        }}
      >
        Manage playbooks →
      </div>
    </div>
  );
}
