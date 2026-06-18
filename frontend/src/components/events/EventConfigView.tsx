import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";

interface EventConfig {
  enabled: boolean;
  timeframes: string[];
  push_enabled: boolean;
  push_min_severity: string;
  event_type_push: Record<string, boolean>;
}

export function EventConfigView() {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);

  const { data: config, isLoading } = useQuery<EventConfig>({
    queryKey: ["events", "config"],
    queryFn: async () => {
      const res = await fetch("/api/v1/events/config");
      if (!res.ok) throw new Error("Failed to fetch event config");
      return res.json();
    },
  });

  const toggleType = async (eventType: string, current: boolean) => {
    setPending(eventType);
    try {
      await fetch("/api/v1/events/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: eventType, push_enabled: !current }),
      });
      queryClient.setQueryData<EventConfig>(["events", "config"], (old) => {
        if (!old) return old;
        return {
          ...old,
          event_type_push: { ...old.event_type_push, [eventType]: !current },
        };
      });
    } finally {
      setPending(null);
    }
  };

  if (isLoading) return <div className="text-sm text-text-muted animate-pulse">Loading config...</div>;
  if (!config) return <div className="text-sm text-text-muted">Config not available</div>;

  return (
    <div className="space-y-4">
      {/* Status summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div className="flex flex-col gap-1">
          <span className="text-text-muted">Status</span>
          <Badge variant={config.enabled ? "success" : "outline"}>
            {config.enabled ? "Active" : "Disabled"}
          </Badge>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-text-muted">Timeframes</span>
          <span className="font-medium">{config.timeframes?.join(", ") || "-"}</span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-text-muted">Push Notifications</span>
          <div className="flex items-center gap-2">
            <Badge variant={config.push_enabled ? "success" : "outline"}>
              {config.push_enabled ? "Enabled" : "Disabled"}
            </Badge>
            {config.push_enabled && (
              <span className="text-xs text-text-muted">≥ {config.push_min_severity}</span>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-text-muted">Monitored Levels</span>
          <span className="font-medium text-xs">
            {config.timeframes?.includes("1D") ? "PDH/PDL, PWH/PWL, PMH/PML" : "Pivot, Fibonacci, EMA"}
          </span>
        </div>
      </div>

      {/* Per-event-type push toggles */}
      {config.push_enabled && config.event_type_push && (
        <div>
          <h4 className="text-sm font-medium text-text-muted mb-2">
            Push notification per event type
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            {Object.entries(config.event_type_push).map(([et, enabled]) => (
              <label
                key={et}
                className="flex items-center gap-2 text-xs text-text-main cursor-pointer select-none"
              >
                <button
                  role="switch"
                  aria-checked={enabled}
                  disabled={pending === et}
                  onClick={() => toggleType(et, enabled)}
                  className={[
                    "relative inline-flex h-4 w-7 shrink-0 rounded-full border border-transparent transition-colors",
                    "focus:outline-none disabled:opacity-50",
                    enabled ? "bg-primary" : "bg-surface-border",
                  ].join(" ")}
                >
                  <span
                    className={[
                      "pointer-events-none inline-block h-3 w-3 rounded-full bg-white shadow transition-transform mt-[0.5px]",
                      enabled ? "translate-x-[14px]" : "translate-x-[1px]",
                    ].join(" ")}
                  />
                </button>
                <span className="font-mono truncate" title={et}>
                  {et.replace(/_/g, " ")}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
