import { useState } from 'react'
import { ArrowLeft, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import type { BacktestRun } from '@/hooks/useStrangleBacktests'
import { useDayTrades, useDayStatus } from '@/hooks/useStrangleBacktests'
import { Card } from '@/components/ui/Card'

interface Props { run: BacktestRun; date: string; onBack: () => void }

export function DayDrillDown({ run, date, onBack }: Props) {
  const { data, isLoading, isError } = useDayTrades(run.run_id, date)
  const { data: statusData } = useDayStatus(run.run_id, date)
  const fills = data?.fills ?? []
  const statusLog = statusData?.status_log ?? []
  const [showTrace, setShowTrace] = useState(false)

  return (
    <div className="flex flex-col gap-4" data-testid="day-drilldown">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-1.5 rounded hover:bg-surface-border text-text-muted">
          <ArrowLeft size={16} />
        </button>
        <div>
          <p className="text-sm font-medium text-text-main">Day Drill-down — {date}</p>
          <p className="text-xs text-text-muted">{run.run_id}</p>
        </div>
      </div>

      {/* Every-bar status trace */}
      {statusLog.length > 0 && (
        <Card>
          <button
            onClick={() => setShowTrace((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs text-text-muted hover:text-text-main"
          >
            <span>Every-bar Status Trace ({statusLog.length} bars)</span>
            {showTrace ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          {showTrace && (
            <pre className="px-4 pb-3 text-[10px] font-mono text-text-muted leading-relaxed overflow-x-auto max-h-72 whitespace-pre">
              {statusLog.map((line, i) => {
                const isEvent = /open|close|exit|stop|flip|hedge|halted/i.test(line)
                return (
                  <span key={i} className={isEvent ? 'text-primary' : ''}>
                    {line}{'\n'}
                  </span>
                )
              })}
            </pre>
          )}
        </Card>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-8 text-text-muted">
          <Loader2 size={16} className="animate-spin mr-2" />
          <span className="text-sm">Loading fills…</span>
        </div>
      )}
      {isError && <p className="text-sm text-bearish">No trade data for this day.</p>}

      {fills.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-4 py-2 border-b border-surface-border text-xs text-text-muted font-medium">
            Fills ({fills.length})
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-card/50">
                <tr className="text-xs text-text-muted">
                  {['Time', 'Side', 'Type', 'Strike', 'Qty', 'Price', 'NIFTY', 'Leg P&L', 'Day P&L', 'Comm', 'Note'].map((h) => (
                    <th key={h} className="px-3 py-1.5 text-left font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border/30">
                {fills.map((f, i) => (
                  <tr key={i} className="hover:bg-surface-card/30">
                    <td className="px-3 py-1.5 font-mono text-xs">{f.time}</td>
                    <td className={`px-3 py-1.5 text-xs font-medium ${f.side === 'SELL' ? 'text-bearish' : 'text-bullish'}`}>{f.side}</td>
                    <td className="px-3 py-1.5 text-xs">{f.opt_type}</td>
                    <td className="px-3 py-1.5 tabular-nums text-xs">{f.strike?.toFixed(0) ?? '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums text-center text-xs">{f.qty}</td>
                    <td className="px-3 py-1.5 tabular-nums text-xs">₹{f.price?.toFixed(2) ?? '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums text-xs text-text-muted">{f.nifty?.toFixed(0) ?? '—'}</td>
                    <td className={`px-3 py-1.5 tabular-nums text-xs ${f.leg_pnl != null ? ((f.leg_pnl >= 0) ? 'text-bullish' : 'text-bearish') : ''}`}>
                      {f.leg_pnl != null ? `₹${f.leg_pnl.toFixed(0)}` : '—'}
                    </td>
                    <td className={`px-3 py-1.5 tabular-nums text-xs ${(f.day_pnl ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                      {f.day_pnl != null ? `₹${f.day_pnl.toFixed(0)}` : '—'}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-xs text-text-muted">{f.commission != null ? `₹${f.commission.toFixed(0)}` : '—'}</td>
                    <td className="px-3 py-1.5 text-xs text-text-muted max-w-[200px] truncate" title={f.note}>{f.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {!isLoading && !isError && fills.length === 0 && (
        <p className="text-sm text-text-muted">No trade detail stored for this day.</p>
      )}
    </div>
  )
}
