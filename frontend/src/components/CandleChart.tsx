import { useEffect, useRef } from 'react'
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts'

interface CandleChartProps {
  title: string
}

export default function CandleChart({ title }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f1117' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      width: containerRef.current.clientWidth,
      height: 320,
    })

    chart.addSeries(CandlestickSeries)

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  return (
    <div className="rounded border border-gray-800 overflow-hidden">
      <div className="px-3 py-2 text-sm font-medium text-gray-400 border-b border-gray-800">
        {title}
      </div>
      <div ref={containerRef} className="w-full" />
    </div>
  )
}
