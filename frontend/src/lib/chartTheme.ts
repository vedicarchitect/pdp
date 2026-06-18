import type { ResponsiveContainerProps } from "recharts"
import type { ChartOptions, DeepPartial, SolidColor } from "lightweight-charts"

export const chartTheme = {
  colors: {
    profit: "var(--color-chart-profit)",
    loss: "var(--color-chart-loss)",
    neutral: "var(--color-chart-neutral)",
    accent: "var(--color-chart-accent)",
    series: [
      "var(--color-chart-series-1)",
      "var(--color-chart-series-2)",
      "var(--color-chart-series-3)",
      "var(--color-chart-series-4)",
      "var(--color-chart-series-5)"
    ],
  },
  axis: {
    color: "#3f3f46",
    fontSize: 11
  },
  tooltip: {
    bg: "#27272a",
    border: "#3f3f46",
    text: "#fafafa"
  },
  grid: {
    color: "rgba(39, 39, 42, 0.2)"
  }
}

export function rechartsDefaults(): Partial<ResponsiveContainerProps> {
  return {
    width: "100%",
    height: "100%",
  }
}

export function lwcDefaults(): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: 'solid', color: 'transparent' } as SolidColor,
      textColor: 'var(--color-text-muted)',
    },
    grid: {
      vertLines: { color: chartTheme.grid.color },
      horzLines: { color: chartTheme.grid.color },
    },
    crosshair: {
      mode: 1, // Normal mode
    },
    rightPriceScale: {
      borderColor: chartTheme.axis.color,
    },
    timeScale: {
      borderColor: chartTheme.axis.color,
      timeVisible: true,
    },
  }
}
