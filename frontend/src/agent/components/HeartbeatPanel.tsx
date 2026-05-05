import { useHeartbeat } from '../hooks/useHeartbeat';
import { HeartbeatStatusBar } from './heartbeat/HeartbeatStatusBar';
import { HeartbeatChecklist } from './heartbeat/HeartbeatChecklist';
import { HeartbeatHistory } from './heartbeat/HeartbeatHistory';
import { HeartbeatConfig } from './heartbeat/HeartbeatConfig';
import { FONT_SANS, INK_DIM, LINE_STRONG } from '../../shared/styles';

interface Props {
  agentSlug: string;
  apiPrefix: string;
}

export default function HeartbeatPanel({ agentSlug, apiPrefix }: Props) {
  const hb = useHeartbeat(agentSlug, apiPrefix);

  if (hb.loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '48px 0' }}>
        <div className="animate-spin w-5 h-5 border-2 border-ch-accent border-t-transparent rounded-full" />
        <span style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK_DIM }}>Loading heartbeat...</span>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', width: '100%' }}>
      <HeartbeatStatusBar
        action={hb.action}
        countdown={hb.countdown}
        running={hb.running}
        actionError={hb.actionError}
        onRunNow={hb.runNow}
        onToggleEnabled={hb.toggleEnabled}
      />

      <div style={{ borderBottom: `1px solid ${LINE_STRONG}` }}>
        <HeartbeatChecklist
          parsedLines={hb.parsedLines}
          canEditCards={hb.canEditCards}
          rawMarkdown={hb.rawMarkdown}
          onSave={hb.saveChecklist}
          onSaveRaw={hb.saveRawChecklist}
        />
      </div>

      <div style={{ borderBottom: `1px solid ${LINE_STRONG}` }}>
        <HeartbeatHistory history={hb.history} />
      </div>

      {hb.action && (
        <HeartbeatConfig
          action={hb.action}
          onUpdateConfig={hb.updateConfig}
        />
      )}
    </div>
  );
}
