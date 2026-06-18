import { useMemo } from 'react'
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card } from '@/components/ui/Card'
import type { PayoffResult } from '../../types/builder'

interface Props {
  data: PayoffResult['pnl_curve'] | undefined
  breakevens: number[]
  spot: number
}

const formatCurrency = (val: number) => `₹${val.toFixed(2)}`

export function PayoffChart({ data, breakevens, spot }: Props) {
  const gradientOffset = useMemo(() => {
    if (!data || data.length === 0) return 0
    const dataMax = Math.max(...data.map(i => i.pnl))
    const dataMin = Math.min(...data.map(i => i.pnl))
    if (dataMax <= 0) return 0
    if (dataMin >= 0) return 1
    return dataMax / (dataMax - dataMin)
  }, [data])

  if (!data || data.length === 0) {
    return (
      <Card className="h-[300px] flex items-center justify-center text-text-muted text-sm rounded-xl">
        Add legs to see payoff chart
      </Card>
    )
  }

  return (
    <Card className="p-4 rounded-xl h-[300px] flex flex-col">
      <div className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
        Payoff Chart
      </div>
      <div className="flex-1 min-h-0 w-full relative">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
            <defs>
              <linearGradient id="splitColor" x1="0" y1="0" x2="0" y2="1">
                <stop offset={gradientOffset} stopColor="var(--color-bullish)" stopOpacity={0.4} />
                <stop offset={gradientOffset} stopColor="var(--color-bearish)" stopOpacity={0.4} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="spot"
              type="number"
              domain={['dataMin', 'dataMax']}
              tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
              tickFormatter={(v) => v.toFixed(0)}
              stroke="var(--color-surface-border)"
            />
            <YAxis
              hide
              domain={['dataMin', 'dataMax']}
            />
            <Tooltip
              formatter={(value: any) => [formatCurrency(value as number), 'P&L']}
              labelFormatter={(label) => `Spot: ${label}`}
              contentStyle={{
                backgroundColor: 'var(--color-surface)',
                borderColor: 'var(--color-surface-border)',
                borderRadius: '8px',
                color: 'var(--color-text-main)',
                fontSize: '12px'
              }}
              itemStyle={{ color: 'var(--color-text-main)' }}
            />
            <ReferenceLine y={0} stroke="var(--color-surface-border)" strokeDasharray="3 3" />
            <ReferenceLine x={spot} stroke="var(--color-text-main)" strokeDasharray="4 4" label={{ position: 'top', value: 'Spot', fill: 'var(--color-text-muted)', fontSize: 11 }} />
            {breakevens.map(be => (
              <ReferenceLine key={be} x={be} stroke="var(--color-warning)" strokeDasharray="3 3" />
            ))}
            <Area
              type="monotone"
              dataKey="pnl"
              stroke="#8884d8"
              strokeWidth={2}
              fill="url(#splitColor)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
