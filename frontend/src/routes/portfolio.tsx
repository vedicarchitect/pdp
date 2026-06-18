import { createFileRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import { DataTable } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import { AlertTriangle } from 'lucide-react'

export const Route = createFileRoute('/portfolio')({
  component: PortfolioPage,
})

interface PortfolioSummary {
  total_unrealized_pnl: number
  total_realized_pnl: number
  day_pnl: number
  open_positions: number
  mode: string
}

interface Position {
  security_id: string
  exchange_segment: string
  product: string
  net_qty: number
  avg_price: string
  realized_pnl: string
  unrealized_pnl: string
  updated_at: string | null
}

interface PositionsResponse {
  positions: Position[]
  count: number
}

const positionColumns: ColumnDef<Position>[] = [
  { accessorKey: 'security_id', header: 'Security', cell: ({ getValue }) => (
    <span className="font-mono text-text-main">{getValue<string>()}</span>
  )},
  { accessorKey: 'exchange_segment', header: 'Segment', cell: ({ getValue }) => (
    <Badge variant="default" size="sm">{getValue<string>()}</Badge>
  )},
  { accessorKey: 'product', header: 'Product' },
  { accessorKey: 'net_qty', header: 'Qty', cell: ({ getValue }) => {
    const qty = getValue<number>()
    return <span className={qty > 0 ? 'text-bullish' : qty < 0 ? 'text-bearish' : 'text-text-muted'}>{qty}</span>
  }},
  { accessorKey: 'avg_price', header: 'Avg Price', cell: ({ getValue }) => (
    <span className="font-mono">{parseFloat(getValue<string>()).toFixed(2)}</span>
  )},
  { accessorKey: 'realized_pnl', header: 'Realized P&L', cell: ({ getValue }) => {
    const val = parseFloat(getValue<string>())
    return <span className={`font-mono ${val > 0 ? 'text-bullish' : val < 0 ? 'text-bearish' : 'text-text-muted'}`}>₹{val.toFixed(2)}</span>
  }},
  { accessorKey: 'unrealized_pnl', header: 'Unrealized P&L', cell: ({ getValue }) => {
    const val = parseFloat(getValue<string>())
    return <span className={`font-mono ${val > 0 ? 'text-bullish' : val < 0 ? 'text-bearish' : 'text-text-muted'}`}>₹{val.toFixed(2)}</span>
  }},
]

function StatCard({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-xl font-mono font-semibold ${positive === undefined ? 'text-text-main' : positive ? 'text-bullish' : 'text-bearish'}`}>
        {value}
      </div>
    </Card>
  )
}

function inr(n: number) {
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card className="p-6 border-bearish/40 bg-bearish/5">
      <div className="flex items-center gap-3 text-bearish mb-3">
        <AlertTriangle size={18} />
        <span className="font-medium text-sm">Failed to load portfolio data</span>
      </div>
      <p className="text-xs text-text-muted mb-4">{message}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>Retry</Button>
    </Card>
  )
}

function PortfolioPage() {
  const {
    data: summary,
    isLoading: summaryLoading,
    isError: summaryError,
    error: summaryErr,
    refetch: refetchSummary,
  } = useQuery<PortfolioSummary>({
    queryKey: ['portfolio-summary'],
    queryFn: () => fetchJson('/api/v1/portfolio/summary'),
    refetchInterval: 10_000,
  })

  const {
    data: posData,
    isLoading: posLoading,
    isError: posError,
    error: posErr,
    refetch: refetchPos,
  } = useQuery<PositionsResponse>({
    queryKey: ['portfolio-positions'],
    queryFn: () => fetchJson('/api/v1/portfolio/positions'),
    refetchInterval: 10_000,
  })

  const positions = posData?.positions ?? []
  const openPositions = positions.filter((p) => p.net_qty !== 0)
  const closedPositions = positions.filter((p) => p.net_qty === 0)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-text-main tracking-tight">Portfolio</h1>
        {summary && (
          <Badge variant={summary.mode === 'live' ? 'danger' : 'warning'} className="uppercase">
            {summary.mode}
          </Badge>
        )}
      </div>

      {/* Summary stats */}
      {summaryError ? (
        <ErrorCard message={(summaryErr as Error)?.message ?? 'Unknown error'} onRetry={() => refetchSummary()} />
      ) : summaryLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : summary ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard label="Day P&L" value={inr(summary.day_pnl)} positive={summary.day_pnl >= 0} />
          <StatCard label="Unrealized P&L" value={inr(summary.total_unrealized_pnl)} positive={summary.total_unrealized_pnl >= 0} />
          <StatCard label="Realized P&L" value={inr(summary.total_realized_pnl)} positive={summary.total_realized_pnl >= 0} />
          <StatCard label="Open Positions" value={String(summary.open_positions)} />
        </div>
      ) : null}

      {/* Open positions */}
      {posError ? (
        <ErrorCard message={(posErr as Error)?.message ?? 'Unknown error'} onRetry={() => refetchPos()} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Open Positions</CardTitle>
          </CardHeader>
          <CardContent>
            {posLoading ? (
              <Skeleton className="h-48 rounded-lg" />
            ) : (
              <DataTable
                data={openPositions}
                columns={positionColumns}
                emptyMessage="No open positions"
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Closed / flat positions */}
      {closedPositions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Flat Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <DataTable
              data={closedPositions}
              columns={positionColumns}
              pageSize={10}
              emptyMessage="No flat positions"
            />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
