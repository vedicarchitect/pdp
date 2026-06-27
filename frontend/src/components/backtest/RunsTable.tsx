import { useState } from 'react'
import { ArrowUpDown, ChevronDown, ChevronUp, Eye, GitCompare } from 'lucide-react'
import type { BacktestRun, ListRunsParams } from '@/hooks/useStrangleBacktests'
import { useRunsList } from '@/hooks/useStrangleBacktests'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'

const _fmt = (v: number | null | undefined, digits = 0) =>
  v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: digits })

const _fmtPF = (v: number | null | undefined) =>
  v == null ? '—' : v === Infinity ? '∞' : v.toFixed(2)

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return null
  return (
    <Badge variant={verdict === 'PASS' ? 'success' : 'warning'} size="sm">
      {verdict}
    </Badge>
  )
}

function KindBadge({ kind }: { kind: string }) {
  const v = kind === 'walkforward' ? 'info' : kind === 'sweep' ? 'warning' : 'outline'
  return <Badge variant={v as any} size="sm">{kind}</Badge>
}

function PromoBadge({ state }: { state: string }) {
  if (state !== 'promoted') return null
  return <Badge variant="success" size="sm">promoted</Badge>
}

interface Props {
  onSelect: (run: BacktestRun) => void
  compareIds: string[]
  onToggleCompare: (id: string) => void
}

const SORT_OPTIONS = [
  { value: 'created_at', label: 'Date' },
  { value: 'pf', label: 'Profit Factor' },
  { value: 'net', label: 'Net P&L' },
  { value: 'sharpe', label: 'Sharpe' },
  { value: 'max_dd', label: 'Max DD' },
]

export function RunsTable({ onSelect, compareIds, onToggleCompare }: Props) {
  const [sortBy, setSortBy] = useState<string>('created_at')
  const [sortDir, setSortDir] = useState<-1 | 1>(-1)
  const [kindFilter, setKindFilter] = useState('')
  const [verdictFilter, setVerdictFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 20

  const params: ListRunsParams = {
    sort_by: sortBy, sort_dir: sortDir, limit, offset,
    kind: kindFilter || undefined,
    verdict: verdictFilter || undefined,
  }
  const { data, isLoading, isError } = useRunsList(params)

  function toggleSort(field: string) {
    if (field === sortBy) setSortDir((d) => (d === -1 ? 1 : -1))
    else { setSortBy(field); setSortDir(-1) }
    setOffset(0)
  }

  const SortIcon = ({ field }: { field: string }) => {
    if (field !== sortBy) return <ArrowUpDown size={12} className="text-text-muted" />
    return sortDir === -1 ? <ChevronDown size={12} /> : <ChevronUp size={12} />
  }

  const thCls = 'px-3 py-2 text-left text-xs text-text-muted font-medium whitespace-nowrap'
  const tdCls = 'px-3 py-2 text-sm whitespace-nowrap'

  if (isLoading) return (
    <Card><div className="py-8 text-center text-text-muted text-sm">Loading runs…</div></Card>
  )
  if (isError) return (
    <Card><div className="py-8 text-center text-bearish text-sm">Failed to load runs</div></Card>
  )

  const runs = data?.runs ?? []
  const total = data?.total ?? 0

  return (
    <div className="flex flex-col gap-3">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap items-center">
        <select
          value={kindFilter}
          onChange={(e) => { setKindFilter(e.target.value); setOffset(0) }}
          className="bg-surface-card border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none"
        >
          <option value="">All kinds</option>
          <option value="single">single</option>
          <option value="sweep">sweep</option>
          <option value="walkforward">walkforward</option>
        </select>
        <select
          value={verdictFilter}
          onChange={(e) => { setVerdictFilter(e.target.value); setOffset(0) }}
          className="bg-surface-card border border-surface-border rounded px-2 py-1 text-sm text-text-main focus:outline-none"
        >
          <option value="">All verdicts</option>
          <option value="PASS">PASS</option>
          <option value="REVIEW">REVIEW</option>
        </select>
        <div className="flex items-center gap-2 ml-auto text-xs text-text-muted">
          Sort:
          <select
            value={sortBy}
            onChange={(e) => toggleSort(e.target.value)}
            className="bg-surface-card border border-surface-border rounded px-2 py-1 text-text-main focus:outline-none"
          >
            {SORT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button onClick={() => setSortDir((d) => (d === -1 ? 1 : -1))} className="text-text-muted hover:text-text-main">
            {sortDir === -1 ? '↓' : '↑'}
          </button>
        </div>
      </div>

      {/* Table */}
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-text-main">
            <thead className="border-b border-surface-border bg-surface-card/50">
              <tr>
                <th className={thCls}>Run ID</th>
                <th className={thCls}>Kind</th>
                <th className={`${thCls} cursor-pointer`} onClick={() => toggleSort('pf')}>
                  <span className="inline-flex items-center gap-1">PF <SortIcon field="pf" /></span>
                </th>
                <th className={`${thCls} cursor-pointer`} onClick={() => toggleSort('net')}>
                  <span className="inline-flex items-center gap-1">Net <SortIcon field="net" /></span>
                </th>
                <th className={`${thCls} cursor-pointer`} onClick={() => toggleSort('sharpe')}>
                  <span className="inline-flex items-center gap-1">Sharpe <SortIcon field="sharpe" /></span>
                </th>
                <th className={`${thCls} cursor-pointer`} onClick={() => toggleSort('max_dd')}>
                  <span className="inline-flex items-center gap-1">MaxDD <SortIcon field="max_dd" /></span>
                </th>
                <th className={thCls}>Win%</th>
                <th className={thCls}>Verdict</th>
                <th className={thCls}>Promo</th>
                <th className={thCls}>Window</th>
                <th className={thCls}></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border/40">
              {runs.length === 0 && (
                <tr><td colSpan={11} className="py-8 text-center text-text-muted text-sm">No runs found</td></tr>
              )}
              {runs.map((run) => {
                const m = run.metrics
                const inCompare = compareIds.includes(run.run_id)
                return (
                  <tr key={run.run_id} className="hover:bg-surface-card/30 transition-colors">
                    <td className={tdCls}>
                      <button
                        onClick={() => onSelect(run)}
                        className="font-mono text-xs text-primary hover:underline max-w-[180px] truncate block"
                        title={run.run_id}
                      >
                        {run.run_id}
                      </button>
                    </td>
                    <td className={tdCls}><KindBadge kind={run.kind} /></td>
                    <td className={`${tdCls} tabular-nums`}>{_fmtPF(m.profit_factor)}</td>
                    <td className={`${tdCls} tabular-nums ${(m.net ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                      ₹{_fmt(m.net)}
                    </td>
                    <td className={`${tdCls} tabular-nums`}>{m.sharpe != null ? m.sharpe.toFixed(2) : '—'}</td>
                    <td className={`${tdCls} tabular-nums text-bearish`}>₹{_fmt(m.max_dd)}</td>
                    <td className={`${tdCls} tabular-nums`}>{m.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'}</td>
                    <td className={tdCls}><VerdictBadge verdict={run.verdict} /></td>
                    <td className={tdCls}><PromoBadge state={run.promotion_state} /></td>
                    <td className={`${tdCls} text-text-muted text-xs`}>
                      {run.window?.from?.slice(0, 10)} → {run.window?.to?.slice(0, 10)}
                    </td>
                    <td className={tdCls}>
                      <div className="flex gap-1">
                        <button
                          onClick={() => onSelect(run)}
                          className="p-1 rounded hover:bg-surface-border text-text-muted hover:text-text-main"
                          title="View detail"
                        >
                          <Eye size={14} />
                        </button>
                        <button
                          onClick={() => onToggleCompare(run.run_id)}
                          className={`p-1 rounded hover:bg-surface-border ${inCompare ? 'text-primary' : 'text-text-muted hover:text-text-main'}`}
                          title={inCompare ? 'Remove from compare' : 'Add to compare'}
                        >
                          <GitCompare size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-text-muted">
        <span>{total} total run{total !== 1 ? 's' : ''}</span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="px-2 py-1 border border-surface-border rounded disabled:opacity-40 hover:bg-surface-card"
          >
            ← Prev
          </button>
          <span className="px-2 py-1">{Math.floor(offset / limit) + 1} / {Math.ceil(total / limit) || 1}</span>
          <button
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
            className="px-2 py-1 border border-surface-border rounded disabled:opacity-40 hover:bg-surface-card"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  )
}
