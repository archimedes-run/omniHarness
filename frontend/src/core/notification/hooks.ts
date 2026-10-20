import { useState, useEffect, useCallback, useRef } from "react";

import { safeField } from "../display/safe";
import { useLocalSettings } from "../settings";

interface NotificationOptions {
  body?: string;
  icon?: string;
  badge?: string;
  tag?: string;
  data?: unknown;
  requireInteraction?: boolean;
  silent?: boolean;
}

interface UseNotificationReturn {
  permission: NotificationPermission;
  isSupported: boolean;
  requestPermission: () => Promise<NotificationPermission>;
  showNotification: (title: string, options?: NotificationOptions) => void;
}

export function useNotification(): UseNotificationReturn {
  const [permission, setPermission] =
    useState<NotificationPermission>("default");
  const [isSupported, setIsSupported] = useState(false);

  const lastNotificationTime = useRef<Date>(new Date());

  useEffect(() => {
    // Check if browser supports Notification API
    if ("Notification" in window) {
      setIsSupported(true);
      setPermission(Notification.permission);
    }
  }, []);

  const requestPermission =
    useCallback(async (): Promise<NotificationPermission> => {
      if (!isSupported) {
        console.warn("Notification API is not supported in this browser");
        return "denied";
      }

      const result = await Notification.requestPermission();
      setPermission(result);
      return result;
    }, [isSupported]);

  const [settings] = useLocalSettings();

  const showNotification = useCallback(
    (title: string, options?: NotificationOptions) => {
      if (!isSupported) {
        console.warn("Notification API is not supported");
        return;
      }

      if (!settings.notification.enabled) {
        console.warn("Notification is disabled");
        return;
      }

      if (
        new Date().getTime() - lastNotificationTime.current.getTime() <
        1000
      ) {
        console.warn("Notification sent too soon");
        return;
      }
      lastNotificationTime.current = new Date();

      if (permission !== "granted") {
        console.warn("Notification permission not granted");
        return;
      }

      // A chat's title and reply are agent-written: shown as safe text
      // (core/display/safe), whoever calls this.
      const notification = new Notification(safeField(title), {
        ...options,
        body: options?.body == null ? options?.body : safeField(options.body),
      });

      // Optional: Add event listeners
      notification.onclick = () => {
        window.focus();
        notification.close();
      };

      notification.onerror = (error) => {
        console.error("Notification error:", error);
      };
    },
    [isSupported, settings.notification.enabled, permission],
  );

  return {
    permission,
    isSupported,
    requestPermission,
    showNotification,
  };
}
