interface WarmHaloProps {
  opacity?: number;
  className?: string;
}

export function WarmHalo({ opacity = 0.45, className }: WarmHaloProps) {
  return (
    <div className={className} style={{
      position: 'absolute', top: -260, left: '50%', transform: 'translateX(-50%)',
      width: 1100, height: 560, pointerEvents: 'none', opacity,
      background: 'radial-gradient(ellipse at center, rgba(200,209,217,0.18) 0%, rgba(107,155,181,0.06) 40%, transparent 70%)',
      filter: 'blur(80px)',
    }} />
  );
}
