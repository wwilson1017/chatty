import { useState, useEffect } from 'react';
import { api } from '../core/api/client';
import { isPushSupported, subscribeToPush, unsubscribeFromPush } from '../core/notifications/pushSubscription';

export function NotificationSettings() {
  const [webPush, setWebPush] = useState(false);
  const [telegram, setTelegram] = useState(true);
  const [whatsapp, setWhatsapp] = useState(true);
  const [pushPermission, setPushPermission] = useState<string>('default');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const settings = await api<Record<string, unknown>>('/api/setup/admin-settings');
        setWebPush(Boolean(settings.notifications_web_push));
        setTelegram(Boolean(settings.notifications_telegram));
        setWhatsapp(Boolean(settings.notifications_whatsapp));
      } catch { /* ignore */ }

      if (isPushSupported()) {
        setPushPermission(Notification.permission);
      } else {
        setPushPermission('unsupported');
      }
      setLoading(false);
    })();
  }, []);

  const toggleWebPush = async () => {
    const next = !webPush;
    setWebPush(next);
    await api('/api/setup/admin-settings', {
      method: 'PUT',
      body: JSON.stringify({ notifications_web_push: next }),
    });
    if (next) {
      const success = await subscribeToPush();
      if (isPushSupported()) setPushPermission(Notification.permission);
      if (!success) setWebPush(false);
    } else {
      await unsubscribeFromPush();
    }
  };

  const toggleTelegram = async () => {
    const next = !telegram;
    setTelegram(next);
    await api('/api/setup/admin-settings', {
      method: 'PUT',
      body: JSON.stringify({ notifications_telegram: next }),
    });
  };

  const toggleWhatsapp = async () => {
    const next = !whatsapp;
    setWhatsapp(next);
    await api('/api/setup/admin-settings', {
      method: 'PUT',
      body: JSON.stringify({ notifications_whatsapp: next }),
    });
  };

  if (loading) return null;

  const pushBlocked = pushPermission === 'denied';
  const pushUnsupported = pushPermission === 'unsupported';

  return (
    <div style={{ marginTop: 24 }}>
      <h3 style={{
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase',
        color: 'rgba(237,240,244,0.38)', marginBottom: 12,
      }}>Notifications</h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <ChannelToggle
          label="Web Push"
          description={
            pushBlocked ? 'Blocked — update in browser site settings' :
            pushUnsupported ? 'Not supported in this browser' :
            'Push notifications to this browser'
          }
          on={webPush && !pushBlocked && !pushUnsupported}
          disabled={pushBlocked || pushUnsupported}
          onChange={toggleWebPush}
        />
        <ChannelToggle
          label="Telegram"
          description="Send via connected Telegram bots"
          on={telegram}
          onChange={toggleTelegram}
        />
        <ChannelToggle
          label="WhatsApp"
          description="Send via connected WhatsApp sessions"
          on={whatsapp}
          onChange={toggleWhatsapp}
        />
      </div>
    </div>
  );
}

function ChannelToggle({ label, description, on, disabled, onChange }: {
  label: string;
  description: string;
  on: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      opacity: disabled ? 0.5 : 1,
    }}>
      <div>
        <p style={{ fontSize: 14, color: '#EDF0F4', margin: 0 }}>{label}</p>
        <p style={{ fontSize: 12, color: 'rgba(237,240,244,0.38)', marginTop: 2 }}>{description}</p>
      </div>
      <button
        onClick={disabled ? undefined : onChange}
        disabled={disabled}
        style={{
          position: 'relative', width: 44, height: 24, borderRadius: 12,
          background: on ? 'var(--color-ch-accent, #C8D1D9)' : 'rgba(230,235,242,0.14)',
          border: 'none', cursor: disabled ? 'not-allowed' : 'pointer', transition: 'background 0.2s',
        }}
      >
        <div style={{
          position: 'absolute', top: 3, left: on ? 23 : 3,
          width: 18, height: 18, borderRadius: '50%',
          background: on ? '#0A0C0F' : '#EDF0F4',
          transition: 'left 0.2s',
        }} />
      </button>
    </div>
  );
}
