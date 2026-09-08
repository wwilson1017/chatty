/**
 * Chatty — runtime badge + unresolved-turn banner.
 *
 * RuntimeBadge: which runtime the current conversation dispatches to, with
 * Hermes health when connected and a developer-only switch (HERMES_DEV_SWITCH).
 * UnresolvedTurnBanner: a previous Hermes turn whose outcome Chatty could not
 * settle on its own; the user retries reconciliation or marks it failed.
 */
import { useState } from 'react';
import { api } from '../../core/api/client';
import { toast } from '../../shared/toast';

import type { RuntimeStatus } from '../hooks/useRuntimeStatus';

export type { RuntimeStatus };


export function RuntimeBadge({ agentId, effectiveRuntime, status, onSwitched }: {
  agentId: string;
  effectiveRuntime: 'chatty' | 'hermes';
  status: RuntimeStatus | null;
  onSwitched: () => void;
}) {
  const [busy, setBusy] = useState(false);
  if (!status?.hermes?.connected && effectiveRuntime !== 'hermes') return null;
  const onHermes = effectiveRuntime === 'hermes';
  const healthy = status?.hermes?.healthy;
  const dot = onHermes ? (healthy ? '#8EA589' : '#D97757') : 'rgba(237,240,244,0.38)';
  const title = onHermes
    ? (healthy ? `Running on Hermes${status?.hermes?.model ? ` · ${status.hermes.model}` : ''}`
      : `Hermes unreachable${status?.hermes?.error ? `: ${status.hermes.error}` : ''}`)
    : 'Running on Chatty';

  async function devSwitch() {
    const target = onHermes ? 'chatty' : 'hermes';
    setBusy(true);
    try {
      await api(`/api/agents/${agentId}/runtime/dev-switch`, { method: 'POST', body: JSON.stringify({ runtime: target }) });
      onSwitched();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Switch failed');
    } finally { setBusy(false); }
  }

  return (
    <div title={title} style={{
      display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8,
      padding: '3px 10px', borderRadius: 4, fontSize: 11,
      border: '1px solid rgba(230,235,242,0.07)', color: 'rgba(237,240,244,0.62)',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot }} />
      <span>{onHermes ? 'Hermes' : 'Chatty'}</span>
      {status?.dev_switch && (
        <button onClick={devSwitch} disabled={busy} style={{
          marginLeft: 4, fontSize: 10, padding: '1px 6px', borderRadius: 3, cursor: 'pointer',
          background: 'transparent', color: 'rgba(237,240,244,0.5)',
          border: '1px solid rgba(230,235,242,0.14)', opacity: busy ? 0.5 : 1,
        }}>{onHermes ? 'to Chatty' : 'to Hermes'}</button>
      )}
    </div>
  );
}

export function UnresolvedTurnBanner({ agentId, conversationId, turn, onResolved }: {
  agentId: string;
  conversationId: string;
  turn: { turn_id: string; state: string; input: string };
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function act(action: 'retry_reconcile' | 'mark_failed') {
    setBusy(true);
    try {
      const r = await api<{ resolved: boolean; turn: { state: string } | null }>(
        `/api/agents/${agentId}/conversations/${conversationId}/resolve`,
        { method: 'POST', body: JSON.stringify({ action }) });
      if (r.resolved) toast.success('Turn resolved');
      else toast.error(`Still unresolved (${r.turn?.state})`);
      onResolved();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Resolve failed');
    } finally { setBusy(false); }
  }
  const explain: Record<string, string> = {
    ambiguous: 'A message may have reached Hermes without a recorded reply.',
    unknown: 'Hermes no longer reports this run, so its outcome is unknown.',
    stopping: 'Hermes was asked to stop the previous run and has not confirmed yet.',
    submitted: 'The previous run may still be executing on Hermes.',
  };
  return (
    <div style={{
      margin: '8px 16px 0', padding: '10px 12px', borderRadius: 6,
      border: '1px solid rgba(212,168,90,0.3)', background: 'rgba(212,168,90,0.08)',
      fontSize: 12, color: 'rgba(237,240,244,0.8)',
    }}>
      <div style={{ fontWeight: 600, marginBottom: 2 }}>Previous Hermes turn is unresolved ({turn.state})</div>
      <div style={{ color: 'rgba(237,240,244,0.62)' }}>{explain[turn.state] || ''} New messages are blocked until it is settled.</div>
      {turn.input && <div style={{ marginTop: 4, fontStyle: 'italic', color: 'rgba(237,240,244,0.5)' }}>“{turn.input.slice(0, 160)}”</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={() => act('retry_reconcile')} disabled={busy} style={btn('#8EA589')}>Check Hermes again</button>
        <button onClick={() => act('mark_failed')} disabled={busy} style={btn('#D97757')}>Mark as failed</button>
      </div>
    </div>
  );
}

function btn(color: string): React.CSSProperties {
  return {
    padding: '5px 12px', fontSize: 12, fontWeight: 500, borderRadius: 4,
    background: 'transparent', color, border: `1px solid ${color}55`, cursor: 'pointer',
  };
}
