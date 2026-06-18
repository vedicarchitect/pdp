import {
  Activity,
  AlertTriangle,
  ArrowRightLeft,
  BarChart2,
  Bell,
  BookOpen,
  BriefcaseBusiness,
  Flame,
  GitMerge,
  Hash,
  Layers,
  LineChart,
  Radio,
  ShieldAlert,
  ShieldOff,
  Sigma,
  Target,
  TrendingDown,
  TrendingUp,
  Waves,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import type { SystemEvent } from "@/hooks/useEventsWS";

// Map event_type prefix → lucide icon
const _TYPE_ICONS: Record<string, React.FC<{ className?: string }>> = {
  SUPERTREND_FLIP: TrendingUp,
  EMA_CROSS: ArrowRightLeft,
  PRICE_EMA_CROSS: ArrowRightLeft,
  PSAR_FLIP: Waves,
  MACD_CROSS: LineChart,
  ELDER_IMPULSE_CHANGE: Flame,
  ELLIOTT_WAVE: GitMerge,
  ML_SIGNAL_FLIP: BookOpen,
  RSI_EXTREME: Sigma,
  PRICE_LEVEL_CROSS: Hash,
  LEVEL_PROXIMITY: Hash,
  CAMARILLA_TOUCH: Hash,
  CONFLUENCE_ZONE: Layers,
  LEVEL_BREAK: BarChart2,
  CUSTOM_RANGE_BREAK: Target,
  VOLUME_SPIKE: Activity,
  VOLUME_SR: Activity,
  GAP_OPEN: Zap,
  OI_WALL: Radio,
  OI_BUILDUP: BarChart2,
  OI_VOLUME_SPIKE: Activity,
  PCR_SHIFT: Sigma,
  GEX_WALL: Radio,
  MAX_PAIN_PIN: Target,
  IV_SHIFT: Waves,
  DELTA_NEUTRAL_DRIFT: ArrowRightLeft,
  BREAKEVEN_BREACH: AlertTriangle,
  EXPIRY_COUNTDOWN: Bell,
  MTM_SWING: LineChart,
  OTM_DISTANCE: Target,
  SAFE_TO_EXIT_TRAIL: ShieldAlert,
  SAFE_TO_EXIT_MOMENTUM: ShieldAlert,
  LEG_STOP_PROXIMITY: AlertTriangle,
  DIRECTIONAL_JUNCTION: GitMerge,
  PORTFOLIO_STATS: BriefcaseBusiness,
  POSITION_CHANGE: ArrowRightLeft,
  ORDER_FILL: Activity,
  SL_HIT: TrendingDown,
  TARGET_HIT: Target,
  KILL_SWITCH_TRIGGERED: ShieldOff,
  MARGIN_WARNING: AlertTriangle,
  STRATEGY_SIGNAL: Zap,
};

function relativeIST(isoTs: string): string {
  const now = Date.now();
  const ts = new Date(isoTs).getTime();
  const diffMs = now - ts;
  if (diffMs < 60_000) return "just now";
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}h ago`;
  return new Date(isoTs).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fullIST(isoTs: string): string {
  return new Date(isoTs).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

interface EventCardProps {
  event: SystemEvent;
  actionHref?: string;
  actionLabel?: string;
}

export function EventCard({ event, actionHref, actionLabel }: EventCardProps) {
  const Icon = _TYPE_ICONS[event.event_type] ?? Bell;

  const severityVariant = (
    {
      INFO: "info",
      WARNING: "warning",
      ERROR: "danger",
      CRITICAL: "danger",
    } as Record<string, "info" | "warning" | "danger">
  )[event.severity] ?? "info";

  return (
    <div className="flex gap-3 p-3 rounded-lg bg-surface border border-surface-border hover:bg-surface-hover transition-colors">
      {/* icon */}
      <div className="mt-0.5 shrink-0">
        <Icon className="w-4 h-4 text-text-muted" />
      </div>

      {/* body */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={severityVariant} size="sm">
              {event.severity}
              {event.severity === "CRITICAL" && (
                <span className="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
              )}
            </Badge>
            <span className="font-medium text-sm text-text-main truncate">{event.title}</span>
          </div>
          <span
            className="text-xs text-text-subtle whitespace-nowrap shrink-0 cursor-default"
            title={fullIST(event.ts)}
          >
            {relativeIST(event.ts)}
          </span>
        </div>

        <p className="text-xs text-text-muted mt-0.5 truncate" title={event.message}>
          {event.message}
        </p>

        {/* meta row */}
        <div className="flex items-center gap-2 mt-1 text-[11px] text-text-subtle">
          {(event.underlying || event.security_id) && (
            <span className="font-mono">{event.underlying ?? event.security_id}</span>
          )}
          {event.timeframe && <span>{event.timeframe}</span>}
          {actionHref && (
            <a
              href={actionHref}
              className="ml-auto text-primary hover:underline"
            >
              {actionLabel ?? "View"}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
