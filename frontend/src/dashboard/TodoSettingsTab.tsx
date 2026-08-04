import { useEffect, useState } from 'react';
import { api } from '../core/api/client';
import { toast } from '../shared/toast';
import { confirmDialog } from '../shared/confirm';
import { inputStyle, FONT_MONO, INK, INK_DIM, INK_MUTE, ACCENT, ACCENT_INK, LINE_STRONG } from '../shared/styles';

interface AdminSettings {
  todo_capture_token: string;
  todo_web_enabled: boolean;
  todo_web_token: string;
  gtd_coaching_text: string;
  gtd_coaching_default: string;
  [key: string]: unknown;
}

function randomToken(): string {
  // 16 bytes → 32 hex chars. getRandomValues works on LAN http origins
  // where crypto.randomUUID (secure-context-only) does not.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

const label: React.CSSProperties = { fontSize: 14, color: INK, margin: 0 };
const hint: React.CSSProperties = { fontSize: 12, color: INK_DIM, marginTop: 2, lineHeight: 1.5 };
const sectionTitle: React.CSSProperties = {
  fontSize: 11, fontFamily: FONT_MONO, letterSpacing: '0.12em',
  color: INK_DIM, textTransform: 'uppercase',
  margin: '0 0 14px',
};
const primaryBtn: React.CSSProperties = {
  padding: '8px 16px', background: ACCENT, color: ACCENT_INK,
  border: 'none', borderRadius: 4, fontSize: 13, fontWeight: 500, cursor: 'pointer',
};
const ghostBtn: React.CSSProperties = {
  padding: '8px 16px', background: 'transparent', color: INK_MUTE,
  border: `1px solid ${LINE_STRONG}`, borderRadius: 4, fontSize: 13, cursor: 'pointer',
};

function Toggle({ on, busy, onClick, label }: {
  on: boolean; busy: boolean; onClick: () => void; label: string;
}) {
  return (
    <button
      disabled={busy}
      onClick={onClick}
      aria-label={label}
      aria-pressed={on}
      style={{
        position: 'relative', width: 44, height: 24, borderRadius: 12, flexShrink: 0,
        background: on ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.14)',
        border: 'none', cursor: 'pointer', transition: 'background 0.2s',
        opacity: busy ? 0.6 : 1,
      }}
    >
      <span style={{
        position: 'absolute', top: 2, width: 20, height: 20,
        borderRadius: '50%', background: '#fff',
        boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
        transition: 'left 0.2s',
        left: on ? 22 : 2,
      }} />
    </button>
  );
}

export function TodoSettingsTab() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [coaching, setCoaching] = useState('');
  const [savingCoaching, setSavingCoaching] = useState(false);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [webBusy, setWebBusy] = useState(false);

  useEffect(() => {
    api<AdminSettings>('/api/setup/admin-settings')
      .then(s => { setSettings(s); setCoaching(s.gtd_coaching_text); })
      .catch(() => toast.error('Failed to load todo settings.'));
  }, []);

  async function putSetting(patch: Record<string, unknown>): Promise<AdminSettings> {
    const updated = await api<AdminSettings>('/api/setup/admin-settings', {
      method: 'PUT', body: JSON.stringify(patch),
    });
    // PUT response has no gtd_coaching_default — keep the one from GET.
    setSettings(prev => ({ ...(prev as AdminSettings), ...updated }));
    return updated;
  }

  if (!settings) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
        <div className="w-6 h-6 border-2 border-ch-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const token = settings.todo_capture_token;
  const captureUrl = `${window.location.origin}/capture${token ? `/${token}` : ''}`;
  const webEnabled = !!settings.todo_web_enabled;
  const webToken = settings.todo_web_token;
  const webUrl = `${window.location.origin}/todo${webToken ? `/${webToken}` : ''}`;

  async function copyUrl(url: string, message: string) {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // http LAN origins lack navigator.clipboard — legacy fallback
      const el = document.createElement('textarea');
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      el.remove();
    }
    toast.success(message);
  }

  async function setToken(value: string) {
    setTokenBusy(true);
    try {
      await putSetting({ todo_capture_token: value });
    } catch {
      toast.error('Failed to update capture link.');
    }
    setTokenBusy(false);
  }

  async function regenerate() {
    const ok = await confirmDialog({
      title: 'Regenerate secret link',
      message: 'The old capture link will stop working — update your phone bookmark afterward.',
      confirmLabel: 'Regenerate',
    });
    if (ok) await setToken(randomToken());
  }

  async function setWeb(patch: Record<string, unknown>, failure: string) {
    setWebBusy(true);
    try {
      await putSetting(patch);
    } catch {
      toast.error(failure);
    }
    setWebBusy(false);
  }

  // Turning it on mints a secret by default: the tokenless URL hands the whole
  // todo list to anyone who knows the server address, so that stays opt-in.
  async function toggleWeb() {
    if (webEnabled) {
      await setWeb({ todo_web_enabled: false }, 'Failed to turn off the todo link.');
      return;
    }
    await setWeb(
      { todo_web_enabled: true, ...(webToken ? {} : { todo_web_token: randomToken() }) },
      'Failed to turn on the todo link.',
    );
  }

  async function regenerateWeb() {
    const ok = await confirmDialog({
      title: 'Regenerate todo link',
      message: 'The old todo link will stop working — update your bookmarks afterward.',
      confirmLabel: 'Regenerate',
    });
    if (ok) await setWeb({ todo_web_token: randomToken() }, 'Failed to update the todo link.');
  }

  async function toggleWebSecret() {
    if (!webToken) {
      await setWeb({ todo_web_token: randomToken() }, 'Failed to update the todo link.');
      return;
    }
    const ok = await confirmDialog({
      title: 'Make the todo link public?',
      message: 'Anyone who knows your server address will be able to read and edit your todos at /todo — no login, no secret.',
      confirmLabel: 'Make it public',
    });
    if (ok) await setWeb({ todo_web_token: '' }, 'Failed to update the todo link.');
  }

  async function saveCoaching() {
    setSavingCoaching(true);
    try {
      await putSetting({ gtd_coaching_text: coaching });
      toast.success(coaching.trim() ? 'Coaching saved.' : 'Coaching disabled (empty text).');
    } catch {
      toast.error('Failed to save coaching text.');
    }
    setSavingCoaching(false);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
      {/* ── Quick capture ─────────────────────────────────────────── */}
      <div>
        <p style={sectionTitle}>Quick Capture</p>
        <p style={label}>Capture page</p>
        <p style={hint}>
          A no-login page that logs whatever you type straight to your todo inbox.
          Bookmark it on your phone.
        </p>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <input
            readOnly
            value={captureUrl}
            onFocus={e => e.target.select()}
            style={{ ...inputStyle, flex: 1, fontFamily: FONT_MONO, fontSize: 12 }}
          />
          <button onClick={() => copyUrl(captureUrl, 'Capture link copied.')} style={primaryBtn}>Copy</button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 18 }}>
          <div style={{ paddingRight: 16 }}>
            <p style={label}>Secret link</p>
            <p style={hint}>
              {token
                ? 'The capture page only works at the secret URL above.'
                : 'Anyone who knows your server address can post to your inbox. Turn this on to move capture to an unguessable URL.'}
            </p>
          </div>
          <Toggle
            on={!!token}
            busy={tokenBusy}
            onClick={() => setToken(token ? '' : randomToken())}
            label="Secret capture link"
          />
        </div>
        {token && (
          <button onClick={regenerate} disabled={tokenBusy} style={{ ...ghostBtn, marginTop: 10 }}>
            Regenerate secret
          </button>
        )}
        <p style={{ ...hint, marginTop: 14 }}>
          Telegram works too: message any connected bot with <code style={{ fontFamily: FONT_MONO }}>/capture buy milk</code>{' '}
          (or just "capture buy milk") for an instant, AI-free capture.
        </p>
      </div>

      {/* ── Todo web app ──────────────────────────────────────────── */}
      <div>
        <p style={sectionTitle}>Todo Web App</p>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ paddingRight: 16 }}>
            <p style={label}>Todo link</p>
            <p style={hint}>
              Your whole todo app — inbox, projects, review — on its own no-login page.
              Bookmark it to reach your todos without signing in to Chatty.
            </p>
          </div>
          <Toggle on={webEnabled} busy={webBusy} onClick={toggleWeb} label="Todo web app" />
        </div>

        {webEnabled && (
          <>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <input
                readOnly
                value={webUrl}
                onFocus={e => e.target.select()}
                style={{ ...inputStyle, flex: 1, fontFamily: FONT_MONO, fontSize: 12 }}
              />
              <button onClick={() => copyUrl(webUrl, 'Todo link copied.')} style={primaryBtn}>Copy</button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 18 }}>
              <div style={{ paddingRight: 16 }}>
                <p style={label}>Secret link</p>
                <p style={hint}>
                  {webToken
                    ? 'The todo page only works at the secret URL above.'
                    : 'Off: anyone who knows your server address can read and edit your todos at /todo.'}
                </p>
              </div>
              <Toggle on={!!webToken} busy={webBusy} onClick={toggleWebSecret} label="Secret todo link" />
            </div>

            {webToken && (
              <button onClick={regenerateWeb} disabled={webBusy} style={{ ...ghostBtn, marginTop: 10 }}>
                Regenerate secret
              </button>
            )}
          </>
        )}
      </div>

      {/* ── GTD coaching ──────────────────────────────────────────── */}
      <div>
        <p style={sectionTitle}>GTD Coaching</p>
        <p style={label}>Agent coaching text</p>
        <p style={hint}>
          Standing instructions added to every agent's system prompt, teaching them to
          work your todo list GTD-style. Edit freely — or ask an agent to tune it for
          you (todo_update_gtd_coaching). Empty text disables the block.
        </p>
        <textarea
          value={coaching}
          onChange={e => setCoaching(e.target.value)}
          rows={12}
          style={{ ...inputStyle, marginTop: 10, resize: 'vertical', fontSize: 13, lineHeight: 1.5 }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button
            onClick={saveCoaching}
            disabled={savingCoaching || coaching === settings.gtd_coaching_text}
            style={{ ...primaryBtn, opacity: savingCoaching || coaching === settings.gtd_coaching_text ? 0.5 : 1 }}
          >
            {savingCoaching ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={() => setCoaching(settings.gtd_coaching_default)}
            disabled={coaching === settings.gtd_coaching_default}
            style={{ ...ghostBtn, opacity: coaching === settings.gtd_coaching_default ? 0.5 : 1 }}
          >
            Reset to default
          </button>
        </div>
      </div>
    </div>
  );
}
