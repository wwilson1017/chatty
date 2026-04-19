const agentHues: Record<string, number> = {
  A: 210, B: 190, C: 140, D: 25, E: 170, F: 30, G: 155, H: 200,
  I: 220, J: 45, K: 175, L: 245, M: 160, N: 185, O: 50, P: 160,
  Q: 230, R: 40, S: 195, T: 10, U: 150, V: 35, W: 205, X: 215,
  Y: 55, Z: 180,
};

function hueForLetter(letter: string): number {
  return agentHues[letter.toUpperCase()] ?? 210;
}

interface AgentMarkProps {
  letter: string;
  size?: number;
  avatarUrl?: string;
  shape?: 'square' | 'round';
  className?: string;
}

export function AgentMark({ letter, size = 44, avatarUrl, shape = 'square', className }: AgentMarkProps) {
  const h = hueForLetter(letter);
  const radius = shape === 'round' ? '50%' : Math.max(6, size * 0.18);

  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt={letter}
        className={className}
        style={{
          width: size, height: size, borderRadius: radius,
          objectFit: 'cover', flexShrink: 0,
        }}
      />
    );
  }

  return (
    <div
      className={className}
      style={{
        width: size, height: size, borderRadius: radius,
        position: 'relative',
        background: `oklch(0.52 0.06 ${h})`,
        color: 'rgba(255,255,255,0.85)',
        fontFamily: "'Fraunces', Georgia, serif",
        fontWeight: 500,
        fontSize: size * 0.48,
        letterSpacing: '-0.025em',
        lineHeight: 1,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
        overflow: 'hidden',
      }}
    >
      <span>{letter.toUpperCase()}</span>
    </div>
  );
}
