import { api } from '../api/client';

export function isPushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

export async function getPushPermissionState(): Promise<NotificationPermission | 'unsupported'> {
  if (!isPushSupported()) return 'unsupported';
  return Notification.permission;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export async function subscribeToPush(): Promise<boolean> {
  if (!isPushSupported()) return false;

  try {
    const registration = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;

    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return false;

    const { public_key } = await api<{ public_key: string }>('/api/notifications/push/vapid-public-key');
    const applicationServerKey = urlBase64ToUint8Array(public_key);

    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: applicationServerKey.buffer as ArrayBuffer,
    });

    const sub = subscription.toJSON();
    await api('/api/notifications/push/subscribe', {
      method: 'POST',
      body: JSON.stringify({
        endpoint: sub.endpoint,
        keys: sub.keys,
        user_agent: navigator.userAgent,
      }),
    });

    return true;
  } catch (err) {
    console.error('Push subscription failed:', err);
    return false;
  }
}

export async function unsubscribeFromPush(): Promise<boolean> {
  if (!isPushSupported()) return false;

  try {
    const registration = await navigator.serviceWorker.getRegistration('/sw.js');
    if (!registration) return true;

    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) return true;

    const endpoint = subscription.endpoint;
    await subscription.unsubscribe();

    await api('/api/notifications/push/unsubscribe', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint }),
    });

    return true;
  } catch (err) {
    console.error('Push unsubscribe failed:', err);
    return false;
  }
}
