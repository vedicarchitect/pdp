import { useEffect, useRef, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/Toast";

export interface SystemEvent {
  id: string;
  event_type: string;
  severity: "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  security_id: string;
  underlying: string | null;
  timeframe: string | null;
  title: string;
  message: string;
  payload: Record<string, any>;
  ts: string;
}

// ── module-level unread store (useSyncExternalStore) ──────────────────────────
let _unread = 0;
const _unreadListeners = new Set<() => void>();

export const unreadEventsStore = {
  get: () => _unread,
  increment: () => { _unread++; _unreadListeners.forEach((f) => f()); },
  clear: () => { if (_unread === 0) return; _unread = 0; _unreadListeners.forEach((f) => f()); },
  subscribe: (fn: () => void) => { _unreadListeners.add(fn); return () => _unreadListeners.delete(fn); },
};

export function useUnreadEvents() {
  return useSyncExternalStore(unreadEventsStore.subscribe, unreadEventsStore.get);
}

// ── WebSocket hook (call once globally from __root.tsx) ───────────────────────
export function useEventsWS() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/events`;

    const connect = () => {
      ws.current = new WebSocket(wsUrl);

      ws.current.onmessage = (msg) => {
        try {
          const newEvent: SystemEvent = JSON.parse(msg.data);

          // Prepend to query cache
          queryClient.setQueryData<SystemEvent[]>(["events"], (old) => {
            if (!old) return [newEvent];
            return [newEvent, ...old].slice(0, 500);
          });

          // Increment unread badge counter
          unreadEventsStore.increment();

          // Toast for WARNING / ERROR / CRITICAL
          if (newEvent.severity === "WARNING") {
            toast({ title: newEvent.title, description: newEvent.message, variant: "warning" });
          } else if (newEvent.severity === "ERROR" || newEvent.severity === "CRITICAL") {
            toast({ title: newEvent.title, description: newEvent.message, variant: "error" });
          }
        } catch (err) {
          console.error("Failed to parse events ws message", err);
        }
      };

      ws.current.onclose = () => setTimeout(connect, 3000);
    };

    connect();

    return () => {
      if (ws.current) {
        ws.current.onclose = null;
        ws.current.close();
      }
    };
  }, [queryClient, toast]);
}
