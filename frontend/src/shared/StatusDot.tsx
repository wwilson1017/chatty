const statusMap = {
  live: { color: 'var(--color-ch-accent, #C8D1D9)', label: 'Live', glow: true },
  idle: { color: '#8EA589', label: 'Ready', glow: false },
  off:  { color: 'rgba(237,240,244,0.38)', label: 'Asleep', glow: false },
} as const;

interface StatusDotProps {
  status: 'live' | 'idle' | 'off';
  showLabel?: boolean;
}

export function StatusDot({ status, showLabel = true }: StatusDotProps) {
  const s = statusMap[status] ?? statusMap.idle;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        width: 6, height: 6, borderRadius: '50%',
        background: s.color,
        boxShadow: s.glow ? `0 0 10px ${s.color}` : 'none',
      }} />
      {showLabel && (
        <span style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          fontSize: 10, letterSpacing: '0.16em',
          textTransform: 'uppercase',
          color: 'rgba(237,240,244,0.62)',
        }}>{s.label}</span>
      )}
    </div>
  );
}
