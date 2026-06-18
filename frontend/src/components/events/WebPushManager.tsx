import { useState, useEffect } from "react";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { Bell, BellOff, Loader2 } from "lucide-react";

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding)
    .replace(/-/g, '+')
    .replace(/_/g, '/');

  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);

  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export function WebPushManager() {
  const [isSupported, setIsSupported] = useState(false);
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [isSubscribed, setIsSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    if ("serviceWorker" in navigator && "PushManager" in window) {
      setIsSupported(true);
      setPermission(Notification.permission);
      
      // Check if already subscribed
      navigator.serviceWorker.ready.then(reg => {
        reg.pushManager.getSubscription().then(sub => {
          if (sub) setIsSubscribed(true);
        });
      });
    }
  }, []);

  const subscribeUser = async () => {
    try {
      setLoading(true);

      const permResult = await Notification.requestPermission();
      setPermission(permResult);
      if (permResult !== "granted") {
        throw new Error("Permission not granted for Notification");
      }

      // Register SW if not already done
      const registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;

      // Fetch VAPID key
      const keyRes = await fetch("/api/v1/events/push/vapid-key");
      if (!keyRes.ok) throw new Error("Push notifications not configured on backend");
      const keyData = await keyRes.json();
      const applicationServerKey = urlBase64ToUint8Array(keyData.public_key);

      // Subscribe via PushManager
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });

      // Send to backend
      const subJson = subscription.toJSON();
      const sendRes = await fetch("/api/v1/events/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: subJson.endpoint,
          keys: subJson.keys,
        })
      });

      if (!sendRes.ok) throw new Error("Failed to store subscription on server");

      setIsSubscribed(true);
      toast({ title: "Subscribed!", description: "You will now receive desktop notifications for high-priority events.", variant: "success" });

    } catch (err: any) {
      console.error("Failed to subscribe to web push", err);
      toast({ title: "Subscription Failed", description: err.message || "An unknown error occurred", variant: "error" });
    } finally {
      setLoading(false);
    }
  };

  if (!isSupported) {
    return (
      <div className="text-sm text-text-muted flex items-center gap-2">
        <BellOff className="w-4 h-4" />
        Push notifications are not supported in this browser.
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4">
      {isSubscribed ? (
        <div className="flex items-center gap-2 text-sm text-bullish font-medium">
          <Bell className="w-4 h-4" />
          Receiving Notifications
        </div>
      ) : (
        <Button 
          variant={permission === "denied" ? "secondary" : "primary"} 
          onClick={subscribeUser}
          disabled={loading || permission === "denied"}
        >
          {loading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
          {!loading && <Bell className="w-4 h-4 mr-2" />}
          Enable Desktop Notifications
        </Button>
      )}
      
      {permission === "denied" && (
        <span className="text-xs text-bearish">Notifications blocked by browser. Enable in browser settings.</span>
      )}
    </div>
  );
}
