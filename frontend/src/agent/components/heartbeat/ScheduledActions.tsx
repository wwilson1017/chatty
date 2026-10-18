import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../core/api/client';
import { toast } from '../../../shared/toast';
import { FONT_SANS, FONT_MONO, INK, INK_DIM, INK_MUTE, LINE_STRONG, labelStyle, inputStyle } from '../../../shared/styles';

/** The agent's cron scheduled actions (created from chat), each with the gates its computer tasks
 *  may cross without asking. Saved through PUT /preapproved — the only writer of that list. */

interface Preapproved { host: string; button_text: string }

interface CronAction {
  id: string;
  action_type: string;
  name: string;
  prompt: string;
  enabled: number | boolean;
  schedule_type: string;
  cron_expression: string | null;
  interval_minutes: number | null;
  run_at: string | null;
  preapproved: Preapproved[];
}

function schedule(a: CronAction): string {
  if (a.schedule_type === 'interval') return `every ${a.interval_minutes} min`;
  if (a.schedule_type === 'once') return a.run_at ? `once, ${a.run_at.replace('T', ' ')}` : 'once';
  return a.cron_expression || 'cron';
}

const smallBtn = {
  fontFamily: FONT_SANS, fontSize: 12, padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
  background: 'none', border: `1px solid ${LINE_STRONG}`, color: INK,
} as const;

function AllowedList({ action, onSaved }: { action: CronAction; onSaved: () => Promise<void> }) {
  const [host, setHost] = useState('');
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);

  async function save(items: Preapproved[]) {
    setSaving(true);
    try {
      await api(`/api/scheduled-actions/${action.id}/preapproved`, { method: 'PUT', body: JSON.stringify({ items }) });
      setHost(''); setText('');
      await onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save');
    } finally { setSaving(false); }
  }

  const canAdd = host.trim() !== '' && text.trim() !== '' && !saving;

  return (
    <div style={{ marginTop: 10 }}>
      <label style={labelStyle}>Allowed without asking</label>
      {action.preapproved.map((p, i) => (
        <div key={`${p.host}|${p.button_text}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontFamily: FONT_SANS, fontSize: 13, color: INK }}>
          <span style={{ fontFamily: FONT_MONO, fontSize: 12 }}>{p.host}</span>
          <span style={{ color: INK_DIM }}>·</span>
          <span>“{p.button_text}”</span>
          <button
            onClick={() => save(action.preapproved.filter((_, j) => j !== i))} disabled={saving}
            aria-label={`Remove ${p.button_text} on ${p.host}`} style={{ ...smallBtn, marginLeft: 'auto', color: INK_MUTE }}
          >
            Remove
          </button>
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
        <input value={host} onChange={e => setHost(e.target.value)} placeholder="site, e.g. time.example"
          aria-label="Site" style={{ ...inputStyle, fontSize: 13, padding: '6px 10px' }} />
        <input value={text} onChange={e => setText(e.target.value)} placeholder="button text, e.g. Submit timesheet"
          aria-label="Button text" style={{ ...inputStyle, fontSize: 13, padding: '6px 10px' }}
          onKeyDown={e => { if (e.key === 'Enter' && canAdd) save([...action.preapproved, { host, button_text: text }]); }} />
        <button onClick={() => save([...action.preapproved, { host, button_text: text }])} disabled={!canAdd}
          style={{ ...smallBtn, opacity: canAdd ? 1 : 0.5 }}>
          Add
        </button>
      </div>
      <p style={{ fontFamily: FONT_SANS, fontSize: 11, color: INK_DIM, margin: '6px 0 0', lineHeight: 1.5 }}>
        Computer tasks this action starts may press exactly these buttons on these sites without an approval card.
        Purchases always ask. Changing the action's prompt clears this list.
      </p>
    </div>
  );
}

export function ScheduledActions({ agentSlug }: { agentSlug: string }) {
  const [actions, setActions] = useState<CronAction[]>([]);

  const load = useCallback(() =>
    api<{ actions: CronAction[] }>(`/api/scheduled-actions/${agentSlug}`)
      .then(d => setActions(d.actions.filter(a => a.action_type === 'cron')))
      .catch(() => { /* the heartbeat tab already reports a failed fetch */ }), [agentSlug]);

  useEffect(() => { load(); }, [load]);

  if (actions.length === 0) return null;

  return (
    <div style={{ padding: '16px 24px' }}>
      <span style={{ ...labelStyle, marginBottom: 12 }}>SCHEDULED ACTIONS</span>
      {actions.map(a => (
        <div key={a.id} style={{ padding: '12px 0', borderTop: `1px solid ${LINE_STRONG}` }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <span style={{ fontFamily: FONT_SANS, fontSize: 14, color: INK, fontWeight: 500 }}>{a.name || 'Unnamed'}</span>
            <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: INK_DIM }}>{schedule(a)}{a.enabled ? '' : ' · paused'}</span>
          </div>
          <p style={{ fontFamily: FONT_SANS, fontSize: 12, color: INK_MUTE, margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>
            {a.prompt.length > 300 ? `${a.prompt.slice(0, 300)}…` : a.prompt}
          </p>
          <AllowedList action={a} onSaved={load} />
        </div>
      ))}
    </div>
  );
}
