import { useState, useEffect } from 'react';
import type { ScheduledAction } from '../../hooks/useHeartbeat';
import { FONT_SANS, FONT_MONO, INK, INK_DIM, ACCENT, ACCENT_INK, BG_RAISED, LINE_STRONG, SAGE } from '../../../shared/styles';
import { labelStyle, inputStyle } from '../../../shared/styles';

interface Props {
  action: ScheduledAction;
  onUpdateConfig: (fields: Record<string, unknown>) => Promise<void>;
}

export function HeartbeatConfig({ action, onUpdateConfig }: Props) {
  const [interval, setInterval_] = useState(action.interval_minutes || 30);
  const [triage, setTriage] = useState(action.triage_enabled);
  const [alwaysOn, setAlwaysOn] = useState(action.always_on);
  const [hoursStart, setHoursStart] = useState(action.active_hours_start || '06:00');
  const [hoursEnd, setHoursEnd] = useState(action.active_hours_end || '20:00');
  const [modelOverride, setModelOverride] = useState(action.model_override || '');
  const [maxIterations, setMaxIterations] = useState(action.max_tool_iterations || 10);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setInterval_(action.interval_minutes || 30);
    setTriage(action.triage_enabled);
    setAlwaysOn(action.always_on);
    setHoursStart(action.active_hours_start || '06:00');
    setHoursEnd(action.active_hours_end || '20:00');
    setModelOverride(action.model_override || '');
    setMaxIterations(action.max_tool_iterations || 10);
    setDirty(false);
  }, [action]);

  function markDirty() { setDirty(true); }

  async function handleSave() {
    setSaving(true);
    try {
      const fields: Record<string, unknown> = {
        interval_minutes: interval,
        triage_enabled: triage,
        always_on: alwaysOn,
        active_hours_start: hoursStart,
        active_hours_end: hoursEnd,
        max_tool_iterations: maxIterations,
      };
      fields.model_override = modelOverride.trim() || '';
      await onUpdateConfig(fields);
      setDirty(false);
    } catch {
      // Backend rejected values — keep dirty so user can correct
    } finally { setSaving(false); }
  }

  function Toggle({ on, onChange, label: lbl }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0' }}>
        <span style={{ fontFamily: FONT_SANS, fontSize: 13, color: INK }}>{lbl}</span>
        <button
          onClick={() => { onChange(!on); markDirty(); }}
          style={{
            width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
            background: on ? SAGE : BG_RAISED, position: 'relative', transition: 'background 0.2s',
          }}
        >
          <div style={{
            width: 14, height: 14, borderRadius: '50%', background: '#fff',
            position: 'absolute', top: 3, left: on ? 19 : 3, transition: 'left 0.2s',
          }} />
        </button>
      </div>
    );
  }

  return (
    <div style={{ padding: '16px 24px' }}>
      <span style={{ ...labelStyle, marginBottom: 16, display: 'block' }}>CONFIGURATION</span>

      {/* Essential fields */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <label style={labelStyle}>Interval (minutes)</label>
          <input
            type="number" min={5} max={1440} value={interval}
            onChange={e => { setInterval_(Math.max(5, Math.min(1440, Number(e.target.value) || 5))); markDirty(); }}
            style={{ ...inputStyle, width: 120 }}
          />
        </div>

        <Toggle on={triage} onChange={setTriage} label="Triage (quick check before full run)" />
      </div>

      {/* Advanced disclosure */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        style={{
          marginTop: 16, fontFamily: FONT_MONO, fontSize: 10, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: INK_DIM,
          background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 6,
        }}
      >
        <svg
          width="10" height="10" viewBox="0 0 10 10" fill="none"
          stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
          style={{ transition: 'transform 0.2s', transform: showAdvanced ? 'rotate(90deg)' : 'none' }}
        >
          <path d="M3 1l4 4-4 4" />
        </svg>
        Advanced
      </button>

      {showAdvanced && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12, paddingLeft: 16, borderLeft: `1px solid ${LINE_STRONG}` }}>
          <Toggle on={alwaysOn} onChange={setAlwaysOn} label="Always On (ignore active hours)" />

          {!alwaysOn && (
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <div>
                <label style={labelStyle}>Active Start</label>
                <input
                  type="time" value={hoursStart}
                  onChange={e => { setHoursStart(e.target.value); markDirty(); }}
                  style={{ ...inputStyle, width: 120 }}
                />
              </div>
              <div>
                <label style={labelStyle}>Active End</label>
                <input
                  type="time" value={hoursEnd}
                  onChange={e => { setHoursEnd(e.target.value); markDirty(); }}
                  style={{ ...inputStyle, width: 120 }}
                />
              </div>
              <span style={{ fontFamily: FONT_SANS, fontSize: 11, color: INK_DIM, marginTop: 16 }}>
                {action.active_hours_tz}
              </span>
            </div>
          )}

          <div>
            <label style={labelStyle}>Model Override</label>
            <input
              value={modelOverride}
              onChange={e => { setModelOverride(e.target.value); markDirty(); }}
              placeholder="Default"
              style={{ ...inputStyle, width: 200 }}
            />
          </div>

          <div>
            <label style={labelStyle}>Max Tool Iterations</label>
            <input
              type="number" min={1} max={10} value={maxIterations}
              onChange={e => { setMaxIterations(Math.max(1, Math.min(10, Number(e.target.value) || 1))); markDirty(); }}
              style={{ ...inputStyle, width: 80 }}
            />
          </div>
        </div>
      )}

      {/* Save button */}
      {dirty && (
        <button
          onClick={handleSave} disabled={saving}
          style={{
            marginTop: 16, fontFamily: FONT_SANS, fontSize: 12, fontWeight: 500,
            padding: '6px 16px', borderRadius: 4, cursor: 'pointer',
            background: ACCENT, color: ACCENT_INK, border: 'none',
            opacity: saving ? 0.5 : 1,
          }}
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      )}
    </div>
  );
}
