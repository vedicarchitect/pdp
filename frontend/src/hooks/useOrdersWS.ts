import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/Toast";

export function useOrdersWS() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Protocol relative websocket connection
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/orders`;
    
    const connect = () => {
      ws.current = new WebSocket(wsUrl);

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === "ORDER_UPDATE") {
            queryClient.invalidateQueries({ queryKey: ["orders"] });
            
            if (data.status === "FILLED") {
              queryClient.invalidateQueries({ queryKey: ["trades"] });
              queryClient.invalidateQueries({ queryKey: ["positions"] });
              toast({
                title: "Order Filled",
                description: `Order for ${data.security_id} filled at ₹${data.fill_price}`,
                variant: "success"
              });
            } else if (data.status === "REJECTED") {
              toast({
                title: "Order Rejected",
                description: `Order for ${data.security_id} was rejected: ${data.reject_reason}`,
                variant: "error"
              });
            }
          }
        } catch (err) {
          console.error("Failed to parse order ws message", err);
        }
      };

      ws.current.onclose = () => {
        // Reconnect after 3s
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
