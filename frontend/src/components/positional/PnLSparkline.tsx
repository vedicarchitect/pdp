import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle, LineSeries } from 'lightweight-charts'
import type { DayPnL } from '../../types/positional'

interface Props {
  history: DayPnL[]
}

export function PnLSparkline({ history }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || history.length < 2) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 160,
    })

    const series = chart.addSeries(LineSeries, {
      color: '#34d399',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })

    const data = history.map((d) => ({
      time: d.date as `${number}-${number}-${number}`,
      value: d.day_pnl,
    }))

    series.setData(data)

    // Color positive vs negative with baseline
    series.applyOptions({
      color: '#34d399',
    })

    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [history])

  if (history.length < 2) {
    return (
      <div className="flex items-center justify-center h-40 bg-gray-900 rounded border border-gray-800 text-gray-600 text-sm">
        No history yet — snapshots will appear after market close
      </div>
    )
  }

  return <div ref={containerRef} className="rounded border border-gray-800 overflow-hidden" />
}
