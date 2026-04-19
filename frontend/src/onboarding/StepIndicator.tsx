interface Step {
  id: string;
  title: string;
}

interface Props {
  steps: Step[];
  currentIndex: number;
}

export function StepIndicator({ steps, currentIndex }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, marginBottom: 32 }}>
      {steps.map((_, i) => (
        <div key={i} style={{
          width: 20, height: 2,
          background: i <= currentIndex ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.07)',
        }} />
      ))}
    </div>
  );
}
