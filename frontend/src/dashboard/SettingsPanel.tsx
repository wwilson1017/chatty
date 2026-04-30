import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import type { Agent, BrandingConfig } from '../core/types';
import { ProviderSetup } from '../setup/ProviderSetup';
import { IntegrationsTab } from './IntegrationsTab';
import { DataTab } from './DataTab';
import { SecurityTab } from './SecurityTab';
import { DeleteAgentModal } from './DeleteAgentModal';
import { AgentMark } from '../shared/AgentMark';

interface Props {
  branding: BrandingConfig | null;
  onBrandingUpdate: (b: BrandingConfig) => void;
  onClose: () => void;
}

type Tab = 'providers' | 'branding' | 'integrations' | 'chat' | 'data' | 'security' | 'danger';

export function SettingsPanel({ branding, onBrandingUpdate, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('providers');
  const [deleteAgent, setDeleteAgent] = useState<Agent | null>(null);
  const [dangerAgents, setDangerAgents] = useState<Agent[]>([]);
  const [crmConfirm, setCrmConfirm] = useState('');
  const [crmClearing, setCrmClearing] = useState(false);
  const [crmCleared, setCrmCleared] = useState(false);
  const [crmError, setCrmError] = useState('');

  useEffect(() => {
    if (tab === 'danger') {
      api<{ agents: Agent[] }>('/api/agents').then(d => setDangerAgents(d.agents)).catch(() => {});
    }
  }, [tab]);
  const [companyName, setCompanyName] = useState(branding?.company_name || '');
  const [accentColor, setAccentColor] = useState(branding?.accent_color || '#C8D1D9');
  const [saving, setSaving] = useState(false);
  const [showToolCalls, setShowToolCalls] = useState(() =>
    localStorage.getItem('chatty_show_tool_calls') === 'true'
  );
  const [alwaysPowerMode, setAlwaysPowerMode] = useState(false);

  useEffect(() => {
    if (tab === 'chat') {
      api<{ always_power_mode: boolean }>('/api/setup/admin-settings')
        .then(s => setAlwaysPowerMode(s.always_power_mode))
        .catch(() => {});
    }
  }, [tab]);

  async function saveBranding() {
    setSaving(true);
    try {
      const updated = await api<BrandingConfig>('/api/branding', {
        method: 'PUT',
        body: JSON.stringify({ company_name: companyName, accent_color: accentColor }),
      });
      onBrandingUpdate(updated);
      document.documentElement.style.setProperty('--brand-color', updated.accent_color);
    } finally {
      setSaving(false);
    }
  }

  async function uploadLogo(file: File) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/branding/logo', {
      method: 'POST',
      headers: { Authorization: `Bearer ${sessionStorage.getItem('chatty_token')}` },
      body: form,
    });
    if (!res.ok) throw new Error('Upload failed');
    onBrandingUpdate({ ...branding!, has_logo: true });
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'providers', label: 'Providers' },
    { id: 'branding', label: 'Branding' },
    { id: 'integrations', label: 'Integrations' },
    { id: 'chat', label: 'Chat' },
    { id: 'data', label: 'Data' },
    { id: 'security', label: 'Security' },
    { id: 'danger', label: 'Danger' },
  ];

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', justifyContent: 'flex-end', zIndex: 50,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: '#11141A', borderLeft: '1px solid rgba(230,235,242,0.07)',
        width: '100%', maxWidth: 520, height: '100%',
        display: 'flex', flexDirection: 'column',
        boxShadow: '-8px 0 40px rgba(0,0,0,0.5)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '0 24px', height: 48,
          borderBottom: '1px solid rgba(230,235,242,0.07)',
        }}>
          <h2 style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 16, fontWeight: 400, letterSpacing: '-0.01em',
            color: '#EDF0F4', margin: 0,
          }}>Settings</h2>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: 'rgba(237,240,244,0.62)',
            fontSize: 20, cursor: 'pointer', padding: 4,
          }}>×</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0 }}>
          {tabs.map(t => {
            const active = tab === t.id;
            return (
              <div
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{
                  flex: 1, padding: '10px 0', textAlign: 'center',
                  fontSize: 12,
                  fontFamily: "'Inter Tight', system-ui, sans-serif",
                  color: t.id === 'danger'
                    ? (active ? '#D97757' : 'rgba(217,119,87,0.6)')
                    : (active ? '#EDF0F4' : 'rgba(237,240,244,0.62)'),
                  borderBottom: active
                    ? (t.id === 'danger' ? '1px solid #D97757' : '1px solid #D4A85A')
                    : '1px solid rgba(230,235,242,0.07)',
                  cursor: 'pointer',
                }}
              >
                {t.label}
              </div>
            );
          })}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {tab === 'providers' && <ProviderSetup />}

          {tab === 'branding' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <div>
                <label style={{
                  display: 'block',
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
                  color: 'rgba(237,240,244,0.38)', marginBottom: 6,
                }}>Company name</label>
                <input
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    background: 'rgba(20,24,30,0.78)',
                    border: '1px solid rgba(230,235,242,0.14)',
                    color: '#EDF0F4', borderRadius: 4,
                    padding: '10px 14px', fontSize: 14, outline: 'none',
                  }}
                />
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
                  color: 'rgba(237,240,244,0.38)', marginBottom: 6,
                }}>Accent color</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <input
                    type="color"
                    value={accentColor}
                    onChange={e => setAccentColor(e.target.value)}
                    style={{ width: 48, height: 48, borderRadius: 4, border: 'none', cursor: 'pointer', background: 'transparent' }}
                  />
                  <span style={{
                    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                    fontSize: 13, color: 'rgba(237,240,244,0.62)',
                  }}>{accentColor}</span>
                </div>
              </div>

              <div>
                <label style={{
                  display: 'block',
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
                  color: 'rgba(237,240,244,0.38)', marginBottom: 6,
                }}>Logo</label>
                {branding?.has_logo && (
                  <div style={{ marginBottom: 12 }}>
                    <img src="/api/branding/logo" alt="Logo" style={{ height: 48, borderRadius: 4 }} />
                  </div>
                )}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                  onChange={e => {
                    const file = e.target.files?.[0];
                    if (file) uploadLogo(file).catch(console.error);
                  }}
                  style={{ fontSize: 13, color: 'rgba(237,240,244,0.62)' }}
                />
              </div>

              <button
                onClick={saveBranding}
                disabled={saving}
                style={{
                  width: '100%', padding: '10px 16px',
                  background: 'var(--color-ch-accent, #C8D1D9)', color: '#0E1013',
                  border: 'none', borderRadius: 4, fontSize: 14, fontWeight: 500,
                  cursor: 'pointer', opacity: saving ? 0.5 : 1,
                }}
              >
                {saving ? 'Saving...' : 'Save Branding'}
              </button>
            </div>
          )}

          {tab === 'integrations' && <IntegrationsTab />}

          {tab === 'chat' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>Show tool calls</p>
                  <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>Display tool call details in chat</p>
                </div>
                <button
                  onClick={() => {
                    const next = !showToolCalls;
                    setShowToolCalls(next);
                    localStorage.setItem('chatty_show_tool_calls', String(next));
                  }}
                  style={{
                    position: 'relative', width: 44, height: 24, borderRadius: 12,
                    background: showToolCalls ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.14)',
                    border: 'none', cursor: 'pointer', transition: 'background 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 2, width: 20, height: 20,
                    borderRadius: '50%', background: '#fff',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                    transition: 'left 0.2s',
                    left: showToolCalls ? 22 : 2,
                  }} />
                </button>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>Always power mode</p>
                  <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>Skip write-tool confirmations for all agents</p>
                </div>
                <button
                  onClick={async () => {
                    const next = !alwaysPowerMode;
                    setAlwaysPowerMode(next);
                    await api('/api/setup/admin-settings', {
                      method: 'PUT',
                      body: JSON.stringify({ always_power_mode: next }),
                    });
                  }}
                  style={{
                    position: 'relative', width: 44, height: 24, borderRadius: 12,
                    background: alwaysPowerMode ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.14)',
                    border: 'none', cursor: 'pointer', transition: 'background 0.2s',
                  }}
                >
                  <span style={{
                    position: 'absolute', top: 2, width: 20, height: 20,
                    borderRadius: '50%', background: '#fff',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                    transition: 'left 0.2s',
                    left: alwaysPowerMode ? 22 : 2,
                  }} />
                </button>
              </div>
            </div>
          )}

          {tab === 'data' && <DataTab />}

          {tab === 'security' && <SecurityTab />}

          {tab === 'danger' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              <div style={{
                background: 'rgba(217,119,87,0.06)',
                border: '1px solid rgba(217,119,87,0.15)',
                borderRadius: 6, padding: '14px 16px',
              }}>
                <p style={{ fontSize: 13, color: '#D97757', margin: 0, lineHeight: 1.5 }}>
                  Actions here are permanent and cannot be undone. Deleted agents lose all knowledge, conversations, and memory.
                </p>
              </div>

              <div>
                <h3 style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
                  color: 'rgba(237,240,244,0.38)', marginBottom: 12,
                }}>Delete agents</h3>

                {dangerAgents.length === 0 ? (
                  <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.38)' }}>No agents to delete.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {dangerAgents.map(agent => (
                      <div key={agent.id} style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '10px 14px', borderRadius: 6,
                        background: 'rgba(20,24,30,0.78)',
                        border: '1px solid rgba(230,235,242,0.07)',
                      }}>
                        <AgentMark
                          letter={agent.agent_name.charAt(0)}
                          size={28}
                          avatarUrl={agent.avatar_url
                            ? `${agent.avatar_url}${agent.avatar_url.includes('?') ? '&' : '?'}token=${sessionStorage.getItem('chatty_token') || ''}`
                            : undefined}
                        />
                        <span style={{
                          flex: 1, fontSize: 14, color: '#EDF0F4',
                          fontFamily: "'Inter Tight', system-ui, sans-serif",
                        }}>{agent.agent_name}</span>
                        <button
                          onClick={() => setDeleteAgent(agent)}
                          style={{
                            background: 'transparent',
                            border: '1px solid rgba(217,119,87,0.3)',
                            color: '#D97757', borderRadius: 4,
                            padding: '5px 12px', fontSize: 12,
                            cursor: 'pointer',
                            fontFamily: "'Inter Tight', system-ui, sans-serif",
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Clear CRM data */}
              <div style={{ borderTop: '1px solid rgba(230,235,242,0.07)', paddingTop: 24 }}>
                <h3 style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
                  color: 'rgba(237,240,244,0.38)', marginBottom: 12,
                }}>Clear CRM data</h3>

                {crmCleared ? (
                  <p style={{ fontSize: 13, color: 'rgba(142,165,137,0.9)', margin: 0 }}>
                    All CRM data has been cleared.
                  </p>
                ) : (
                  <>
                    <p style={{ fontSize: 13, color: 'rgba(237,240,244,0.52)', margin: '0 0 12px', lineHeight: 1.5 }}>
                      Delete all contacts, deals, tasks, and activity from the CRM. This cannot be undone.
                    </p>
                    <div style={{
                      background: 'rgba(217,119,87,0.08)',
                      border: '1px solid rgba(217,119,87,0.2)',
                      borderRadius: 6, padding: '10px 14px', marginBottom: 12,
                    }}>
                      <p style={{ fontSize: 12, color: '#D97757', margin: 0, lineHeight: 1.5 }}>
                        Type <strong style={{
                          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                          background: 'rgba(217,119,87,0.12)',
                          padding: '1px 6px', borderRadius: 3,
                        }}>clear crm</strong> to confirm.
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input
                        type="text"
                        value={crmConfirm}
                        onChange={e => setCrmConfirm(e.target.value)}
                        placeholder="clear crm"
                        autoComplete="off"
                        style={{
                          flex: 1, boxSizing: 'border-box',
                          background: 'rgba(20,24,30,0.78)',
                          border: '1px solid rgba(230,235,242,0.14)',
                          color: '#EDF0F4', borderRadius: 4,
                          padding: '8px 14px', fontSize: 13, outline: 'none',
                          fontFamily: "'Inter Tight', system-ui, sans-serif",
                        }}
                      />
                      <button
                        disabled={crmClearing || crmConfirm.toLowerCase() !== 'clear crm'}
                        onClick={async () => {
                          setCrmClearing(true);
                          setCrmError('');
                          try {
                            await api('/api/crm/clear-all', {
                              method: 'POST',
                              body: JSON.stringify({ confirmation: 'clear crm' }),
                            });
                            setCrmCleared(true);
                            setTimeout(() => window.location.reload(), 1500);
                          } catch (err: unknown) {
                            setCrmError(err instanceof Error ? err.message : 'Failed to clear CRM data');
                          } finally {
                            setCrmClearing(false);
                          }
                        }}
                        style={{
                          padding: '8px 16px', borderRadius: 4,
                          background: crmConfirm.toLowerCase() === 'clear crm' ? '#D97757' : 'rgba(217,119,87,0.3)',
                          color: crmConfirm.toLowerCase() === 'clear crm' ? '#0E1013' : 'rgba(14,16,19,0.5)',
                          border: 'none', fontWeight: 500, fontSize: 13,
                          cursor: crmConfirm.toLowerCase() === 'clear crm' ? 'pointer' : 'default',
                          fontFamily: "'Inter Tight', system-ui, sans-serif",
                          transition: 'background 0.15s, color 0.15s',
                          whiteSpace: 'nowrap',
                        }}
                      >{crmClearing ? 'Clearing...' : 'Clear all'}</button>
                    </div>
                    {crmError && <p style={{ color: '#D97757', fontSize: 13, marginTop: 8 }}>{crmError}</p>}
                  </>
                )}
              </div>
            </div>
          )}

          {deleteAgent && (
            <DeleteAgentModal
              agent={deleteAgent}
              onClose={() => setDeleteAgent(null)}
              onDeleted={id => {
                setDangerAgents(prev => prev.filter(a => a.id !== id));
                setDeleteAgent(null);
                window.location.reload();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
