import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/Toast";
import { formatAlertTitle, formatAlertDescription } from "@/components/alerts/AlertNotification";

export function useAlertsWS() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Protocol relative websocket connection
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/alerts`;
    
    const connect = () => {
      ws.current = new WebSocket(wsUrl);

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          // Invalidate alerts list so status badges update in real-time
          queryClient.invalidateQueries({ queryKey: ["alerts"] });
          if (data.status === "TRIGGERED") {
            toast({
              title: formatAlertTitle(data.security_id),
              description: formatAlertDescription(data.condition, data.threshold),
              variant: "warning",
            });
          }
        } catch (err) {
          console.error("Failed to parse alerts ws message", err);
        }
      };

      ws.current.onclose = () => {
        setTimeout(connect, 3000);
      };
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
