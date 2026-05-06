import type { ScheduledAction } from '../../hooks/useHeartbeat';
import { FONT_MONO, FONT_SANS, INK_DIM, INK_MUTE, ACCENT, ACCENT_INK, BG_RAISED, LINE_STRONG, SAGE, GOLD, CORAL } from '../../../shared/styles';

const statusColors: Record<string, string> = {
  ok: SAGE,
  action_taken: GOLD,
  error: CORAL,
  skipped: INK_DIM,
};

const statusLabels: Record<string, string> = {
  ok: 'All clear',
  action_taken: 'Action taken',
  error: 'Error',
  skipped: 'Skipped',
};

interface Props {
  action: ScheduledAction | null;
  countdown: string;
  running: boolean;
  actionError: boolean;
  onRunNow: () => void;
  onToggleEnabled: () => void;
}

export function HeartbeatStatusBar({ action, countdown, running, actionError, onRunNow, onToggleEnabled }: Props) {
  if (!action) {
    return (
      <div style={{
        padding: '20px 24px', borderBottom: `1px solid ${LINE_STRONG}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
      }}>
        {actionError ? (
          <span style={{ fontFamily: FONT_SANS, fontSize: 13, color: CORAL }}>
            Could not load heartbeat configuration. Check that the backend is running.
          </span>
        ) : (
          <>
            <div className="animate-spin w-4 h-4 border-2 border-ch-accent border-t-transparent rounded-full" />
            <span style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK_DIM }}>Initializing heartbeat...</span>
          </>
        )}
      </div>
    );
  }

  const disabled = !action.enabled;
  const lastStatus = action.last_status || 'ok';
  const color = statusColors[lastStatus] || INK_DIM;
  const label = statusLabels[lastStatus] || lastStatus;

  const interval = action.interval_minutes
    ? action.interval_minutes >= 60
      ? `Every ${action.interval_minutes / 60}h`
      : `Every ${action.interval_minutes}m`
    : action.cron_expression || 'Custom';

  return (
    <div style={{ borderBottom: `1px solid ${LINE_STRONG}` }}>
      {/* Disabled banner */}
      {disabled && (
        <div style={{
          padding: '8px 24px', background: 'rgba(217,119,87,0.06)',
          borderBottom: `1px solid rgba(217,119,87,0.15)`,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 10, fontWeight: 600, letterSpacing: '0.16em', textTransform: 'uppercase', color: CORAL }}>
            PAUSED
          </span>
          <span style={{ fontSize: 12, color: INK_MUTE }}>
            {action.consecutive_errors >= 5
              ? 'Heartbeat paused due to repeated errors.'
              : 'Heartbeat is disabled.'}
          </span>
          <button
            onClick={onToggleEnabled}
            style={{
              marginLeft: 'auto', fontSize: 11, fontWeight: 500,
              color: CORAL, background: 'none', border: 'none', cursor: 'pointer',
            }}
          >Re-enable</button>
        </div>
      )}

      <div style={{ padding: '16px 24px' }}>
        {/* Countdown hero */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase', color: INK_DIM }}>
            NEXT RUN
          </span>
          <span style={{
            fontFamily: FONT_MONO, fontSize: 28, fontWeight: 300,
            letterSpacing: '0.05em', color: disabled ? INK_DIM : ACCENT,
            lineHeight: 1,
          }}>
            {running && (
              <span className="inline-block animate-spin w-5 h-5 border-2 border-ch-accent border-t-transparent rounded-full mr-2 align-middle" />
            )}
            {countdown}
          </span>
        </div>

        {/* Meta row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 11, letterSpacing: '0.08em', color: INK_MUTE }}>
            {interval}
          </span>

          {action.last_run && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
              <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: INK_MUTE }}>{label}</span>
            </div>
          )}

          {action.total_runs > 0 && (
            <span style={{ fontFamily: FONT_SANS, fontSize: 12, color: INK_DIM }}>
              {action.total_runs} total runs
            </span>
          )}

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              onClick={onRunNow}
              disabled={running || disabled}
              style={{
                fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500,
                padding: '6px 14px', borderRadius: 4, cursor: running || disabled ? 'default' : 'pointer',
                background: running || disabled ? BG_RAISED : ACCENT,
                color: running || disabled ? INK_DIM : ACCENT_INK,
                border: 'none', opacity: running || disabled ? 0.5 : 1,
              }}
            >
              {running ? 'Running...' : 'Run Now'}
            </button>

            {/* Enable/disable toggle */}
            <button
              onClick={onToggleEnabled}
              style={{
                width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
                background: action.enabled ? SAGE : BG_RAISED,
                position: 'relative', transition: 'background 0.2s',
              }}
              title={action.enabled ? 'Disable heartbeat' : 'Enable heartbeat'}
            >
              <div style={{
                width: 14, height: 14, borderRadius: '50%',
                background: '#fff', position: 'absolute', top: 3,
                left: action.enabled ? 19 : 3,
                transition: 'left 0.2s',
              }} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
