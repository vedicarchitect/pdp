import { useState } from "react";

export type SeverityFilter = "ALL" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
export type DateRangeFilter = "today" | "7d" | "14d" | "all";

const ALL_EVENT_TYPES = [
  // trend / momentum
  "SUPERTREND_FLIP", "EMA_CROSS", "PRICE_EMA_CROSS", "PSAR_FLIP",
  "MACD_CROSS", "ELDER_IMPULSE_CHANGE", "ELLIOTT_WAVE", "ML_SIGNAL_FLIP", "RSI_EXTREME",
  // price levels & confluence
  "PRICE_LEVEL_CROSS", "LEVEL_PROXIMITY", "CAMARILLA_TOUCH", "CONFLUENCE_ZONE",
  // range / breakout / volume
  "LEVEL_BREAK", "CUSTOM_RANGE_BREAK", "VOLUME_SPIKE", "VOLUME_SR", "GAP_OPEN",
  // options / OI / greeks
  "OI_WALL", "OI_BUILDUP", "OI_VOLUME_SPIKE", "PCR_SHIFT", "GEX_WALL",
  "MAX_PAIN_PIN", "IV_SHIFT", "DELTA_NEUTRAL_DRIFT", "BREAKEVEN_BREACH", "EXPIRY_COUNTDOWN",
  // position / P&L
  "MTM_SWING", "OTM_DISTANCE", "SAFE_TO_EXIT_TRAIL", "SAFE_TO_EXIT_MOMENTUM",
  "LEG_STOP_PROXIMITY", "DIRECTIONAL_JUNCTION", "PORTFOLIO_STATS", "POSITION_CHANGE",
  // system / order
  "ORDER_FILL", "SL_HIT", "TARGET_HIT",
  "KILL_SWITCH_TRIGGERED", "MARGIN_WARNING", "STRATEGY_SIGNAL",
] as const;

export interface EventFiltersState {
  severity: SeverityFilter;
  types: Set<string>;
  dateRange: DateRangeFilter;
}

interface EventFiltersProps {
  value: EventFiltersState;
  onChange: (next: EventFiltersState) => void;
  totalCount: number;
}

export function defaultFilters(): EventFiltersState {
  return { severity: "ALL", types: new Set(), dateRange: "today" };
}

export function EventFilters({ value, onChange, totalCount }: EventFiltersProps) {
  const [typesOpen, setTypesOpen] = useState(false);

  const setSeverity = (s: SeverityFilter) => onChange({ ...value, severity: s });
  const setDateRange = (d: DateRangeFilter) => onChange({ ...value, dateRange: d });

  const toggleType = (t: string) => {
    const next = new Set(value.types);
    next.has(t) ? next.delete(t) : next.add(t);
    onChange({ ...value, types: next });
  };

  const clearTypes = () => onChange({ ...value, types: new Set() });

  const activeTypeLabel =
    value.types.size === 0
      ? "All Types"
      : value.types.size === 1
      ? [...value.types][0].replace(/_/g, " ")
      : `${value.types.size} types`;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Severity toggle pills */}
      <div className="flex items-center gap-1">
        {(["ALL", "INFO", "WARNING", "ERROR", "CRITICAL"] as SeverityFilter[]).map((s) => (
          <button
            key={s}
            onClick={() => setSeverity(s)}
            className={[
              "px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
              value.severity === s
                ? s === "ALL"
                  ? "bg-primary text-white"
                  : s === "WARNING"
                  ? "bg-warning text-white"
                  : s === "ERROR" || s === "CRITICAL"
                  ? "bg-bearish text-white"
                  : "bg-info text-white"
                : "bg-surface-raised text-text-muted hover:text-text-main hover:bg-surface-hover",
            ].join(" ")}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Event type multi-select dropdown */}
      <div className="relative">
        <button
          onClick={() => setTypesOpen((o) => !o)}
          className="px-2.5 py-1 rounded-md text-xs font-medium bg-surface-raised text-text-main hover:bg-surface-hover border border-surface-border transition-colors"
        >
          {activeTypeLabel} ▾
        </button>
        {typesOpen && (
          <div className="absolute top-full left-0 mt-1 z-50 w-60 max-h-72 overflow-y-auto bg-surface-overlay border border-surface-border rounded-lg shadow-lg p-1">
            <button
              onClick={clearTypes}
              className="w-full text-left px-2 py-1 text-xs text-primary hover:bg-surface-hover rounded"
            >
              Clear selection
            </button>
            {ALL_EVENT_TYPES.map((t) => (
              <label
                key={t}
                className="flex items-center gap-2 px-2 py-1 text-xs text-text-main hover:bg-surface-hover rounded cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={value.types.has(t)}
                  onChange={() => toggleType(t)}
                  className="accent-primary"
                />
                <span className="font-mono">{t.replace(/_/g, " ")}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {/* Date range */}
      <select
        value={value.dateRange}
        onChange={(e) => setDateRange(e.target.value as DateRangeFilter)}
        className="px-2 py-1 rounded-md text-xs bg-surface border border-surface-border text-text-main focus:outline-none focus:ring-1 focus:ring-primary"
      >
        <option value="today">Today</option>
        <option value="7d">Last 7 days</option>
        <option value="14d">Last 14 days</option>
        <option value="all">All</option>
      </select>

      <span className="text-xs text-text-muted ml-auto">
        {totalCount} event{totalCount !== 1 ? "s" : ""}
      </span>
    </div>
  );
}

/** Apply EventFiltersState to a list of SystemEvents (client-side). */
export function applyFilters<T extends { severity: string; event_type: string; ts: string }>(
  events: T[],
  f: EventFiltersState
): T[] {
  const now = Date.now();
  const cutoff: Record<DateRangeFilter, number> = {
    today: new Date().setHours(0, 0, 0, 0),
    "7d": now - 7 * 86_400_000,
    "14d": now - 14 * 86_400_000,
    all: 0,
  };
  return events.filter((e) => {
    if (f.severity !== "ALL" && e.severity !== f.severity) return false;
    if (f.types.size > 0 && !f.types.has(e.event_type)) return false;
    if (new Date(e.ts).getTime() < cutoff[f.dateRange]) return false;
    return true;
  });
}
