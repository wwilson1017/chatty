import type { CrmDeal } from '../../core/types';
import { STAGE_COLORS } from '../constants';

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

interface DealDetailSheetProps {
  deal: CrmDeal;
  isMobile: boolean;
  onClose: () => void;
  onEdit: (deal: CrmDeal) => void;
  onStageChange: (deal: CrmDeal, stage: string) => void;
}

export function DealDetailSheet({ deal, isMobile, onClose, onEdit, onStageChange }: DealDetailSheetProps) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        zIndex: 50, display: 'flex',
        alignItems: isMobile ? 'flex-end' : 'center',
        justifyContent: 'center',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#11141A',
          borderRadius: isMobile ? '12px 12px 0 0' : 8,
          border: '1px solid rgba(230,235,242,0.14)',
          borderBottom: isMobile ? 'none' : undefined,
          padding: isMobile ? '20px 20px 28px' : 28,
          width: '100%', maxWidth: 480, margin: isMobile ? 0 : '0 16px',
          boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
        }}
      >
        {isMobile && (
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(230,235,242,0.14)' }} />
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
          <h3 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 20, fontWeight: 400, letterSpacing: '-0.01em',
            color: '#EDF0F4', margin: 0, flex: 1,
          }}>{deal.title}</h3>
          <span style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 20, color: '#D4A85A', flexShrink: 0, marginLeft: 12,
          }}>${deal.value.toLocaleString()}</span>
        </div>

        <div style={{
          fontSize: 12, color: 'rgba(237,240,244,0.62)', marginBottom: 16,
          textTransform: 'capitalize',
        }}>
          Stage: <span style={{ color: STAGE_COLORS[deal.stage]?.color || '#EDF0F4' }}>{deal.stage}</span>
        </div>

        {deal.notes && (
          <p style={{ fontSize: 14, color: 'rgba(237,240,244,0.62)', marginBottom: 16, lineHeight: 1.5 }}>
            {deal.notes}
          </p>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
          {deal.contact_name && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Contact</span>
              <span style={{ fontSize: 13, color: '#EDF0F4' }}>{deal.contact_name}</span>
            </div>
          )}
          {deal.probability > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Probability</span>
              <span style={{ fontSize: 13, color: '#EDF0F4' }}>{deal.probability}%</span>
            </div>
          )}
          {deal.expected_close_date && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ ...mono(9), color: 'rgba(237,240,244,0.38)' }}>Expected Close</span>
              <span style={{ fontSize: 13, color: '#EDF0F4' }}>{deal.expected_close_date}</span>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onClose} style={{
            padding: '10px 16px', borderRadius: 6,
            border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
            color: 'rgba(237,240,244,0.62)', fontSize: 13, cursor: 'pointer',
          }}>Close</button>
          <button onClick={() => onEdit(deal)} style={{
            padding: '10px 16px', borderRadius: 6,
            border: '1px solid rgba(230,235,242,0.14)', background: 'transparent',
            color: '#EDF0F4', fontSize: 13, cursor: 'pointer',
          }}>Edit</button>
          {deal.stage !== 'won' && deal.stage !== 'lost' && (
            <>
              <button onClick={() => onStageChange(deal, 'won')} style={{
                padding: '10px 16px', borderRadius: 6,
                background: '#8EA589', color: '#0E1013',
                border: 'none', fontWeight: 500, fontSize: 13, cursor: 'pointer',
                flex: 1,
              }}>Mark Won</button>
              <button onClick={() => onStageChange(deal, 'lost')} style={{
                padding: '10px 16px', borderRadius: 6,
                background: 'rgba(217,119,87,0.1)', color: '#D97757',
                border: '1px solid rgba(217,119,87,0.2)',
                fontSize: 13, cursor: 'pointer',
              }}>Mark Lost</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
