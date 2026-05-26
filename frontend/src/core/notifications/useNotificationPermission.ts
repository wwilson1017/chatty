import { useState, useCallback } from 'react';
import { isPushSupported, subscribeToPush } from './pushSubscription';

export function useNotificationPermission() {
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(() => {
    if (!isPushSupported()) return 'unsupported';
    return Notification.permission;
  });

  const requestPermission = useCallback(async () => {
    if (!isPushSupported()) return false;
    const success = await subscribeToPush();
    setPermission(Notification.permission);
    return success;
  }, []);

  return { permission, requestPermission, isSupported: isPushSupported() };
}
