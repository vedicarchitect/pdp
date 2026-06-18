import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts'
import { chartTheme } from '@/lib/chartTheme'

interface EquityPoint {
  date: string
  cumulative_pnl: number
  drawdown?: number
}

interface Props {
  data: EquityPoint[]
}

function formatINR(v: number) {
  const abs = Math.abs(v)
  if (abs >= 100000) return `${v >= 0 ? '' : '-'}₹${(abs / 100000).toFixed(1)}L`
  if (abs >= 1000) return `${v >= 0 ? '' : '-'}₹${(abs / 1000).toFixed(1)}K`
  return `₹${v.toFixed(0)}`
}

export function EquityCurve({ data }: Props) {
  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={240}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid.color} />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
          tickFormatter={(v) => v.slice(5)}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
          tickFormatter={formatINR}
          width={56}
        />
        <Tooltip
          contentStyle={{
            background: chartTheme.tooltip.bg,
            border: `1px solid ${chartTheme.tooltip.border}`,
            borderRadius: 6,
            color: chartTheme.tooltip.text,
            fontSize: 12,
          }}
          formatter={(v, name) => {
            if (name === 'drawdown') return [formatINR(Number(v)), 'Drawdown']
            return [formatINR(Number(v)), 'Cumulative P&L']
          }}
          labelStyle={{ color: 'var(--color-text-muted)', fontSize: 11 }}
        />
        <ReferenceLine y={0} stroke={chartTheme.axis.color} strokeDasharray="4 2" />
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke={chartTheme.colors.loss}
          fill={chartTheme.colors.loss}
          fillOpacity={0.15}
          dot={false}
          strokeWidth={1}
        />
        <Line
          type="monotone"
          dataKey="cumulative_pnl"
          stroke={
            data[data.length - 1]?.cumulative_pnl >= 0
              ? chartTheme.colors.profit
              : chartTheme.colors.loss
          }
          dot={false}
          strokeWidth={2}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
