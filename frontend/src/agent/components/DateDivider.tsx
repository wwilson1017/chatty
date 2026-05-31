import { formatDateDivider } from '../utils/dateFormat';

export function DateDivider({ timestamp }: { timestamp: number }) {
  const label = formatDateDivider(timestamp);
  if (!label) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '8px 0' }}>
      <span style={{
        padding: '2px 12px',
        fontSize: 11,
        fontFamily: "'Inter Tight', system-ui, sans-serif",
        fontWeight: 500,
        color: 'rgba(237,240,244,0.38)',
        background: 'rgba(34,40,48,0.55)',
        borderRadius: 99,
      }}>
        {label}
      </span>
    </div>
  );
}
