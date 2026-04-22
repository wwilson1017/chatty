import { IconCheck, IconArrowRight } from '../../shared/icons';

interface Props {
  onComplete: () => void;
  onSkip: () => void;
}

const mono = (size: number, color = 'rgba(237,240,244,0.38)') => ({
  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
  fontSize: size, letterSpacing: '0.16em',
  textTransform: 'uppercase' as const, color,
});

const FEATURES = [
  { label: 'Contacts', desc: 'store and search your contacts' },
  { label: 'Deals', desc: 'track opportunities and pipeline stages' },
  { label: 'Tasks', desc: 'manage follow-ups and to-dos' },
  { label: 'Activity log', desc: 'automatic tracking of interactions' },
];

export function CrmLiteSetupStep({ onComplete, onSkip }: Props) {
  return (
    <div>
      <div style={mono(10)}>Built-in CRM</div>
      <h1 style={{
        fontFamily: "'Fraunces', Georgia, serif",
        fontSize: 32, fontWeight: 400, letterSpacing: '-0.025em',
        lineHeight: 1.1, margin: '14px 0 12px', color: '#EDF0F4',
      }}>
        Your own <span style={{ fontStyle: 'italic', color: '#D4A85A' }}>sales pipeline</span>
      </h1>
      <p style={{ fontSize: 15, color: 'rgba(237,240,244,0.62)', lineHeight: 1.5, marginBottom: 28, maxWidth: 560 }}>
        Chatty includes a built-in CRM that's always available — no setup required.
        Your agents can manage contacts, deals, tasks, and your sales pipeline.
        You can hide it from the sidebar if you don't need it.
      </p>

      <div style={{
        background: 'rgba(20,24,30,0.78)',
        border: '1px solid rgba(230,235,242,0.07)',
        borderRadius: 6, padding: 20, marginBottom: 24,
      }}>
        <div style={mono(9)}>What's included</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 14 }}>
          {FEATURES.map(f => (
            <div key={f.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <IconCheck size={14} style={{ color: '#D4A85A', marginTop: 2 }} strokeWidth={2.5} />
              <div style={{ fontSize: 14 }}>
                <span style={{ color: '#EDF0F4' }}>{f.label}</span>
                <span style={{ color: 'rgba(237,240,244,0.62)' }}> — {f.desc}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <button onClick={onSkip} style={{
          padding: '9px 20px', borderRadius: 4, fontSize: 14, fontWeight: 500,
          background: 'transparent', color: 'rgba(237,240,244,0.62)',
          border: '1px solid rgba(230,235,242,0.14)', cursor: 'pointer',
        }}>
          Hide CRM
        </button>
        <button onClick={onComplete} style={{
          padding: '9px 20px', borderRadius: 4, fontSize: 14, fontWeight: 500,
          background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
          border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          Show CRM <IconArrowRight size={15} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
