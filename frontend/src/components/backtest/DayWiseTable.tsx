import type { ColumnDef } from '@tanstack/react-table'
import { DataTable } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'

interface DayRow {
  date: string
  pnl: number
  trades: number
  re_entries: number
  weekday: string
  exit_reason?: string
}

const EXIT_REASON_MAP: Record<string, { label: string; variant: 'info' | 'warning' | 'danger' | 'success' }> = {
  time_exit: { label: 'Time', variant: 'info' },
  combined_sl: { label: 'SL', variant: 'danger' },
  per_leg_sl: { label: 'Leg SL', variant: 'danger' },
  trailing_sl: { label: 'Trail', variant: 'warning' },
  combined_target: { label: 'Target', variant: 'success' },
}

function ExitReasonBadge({ reason }: { reason: string }) {
  const cfg = EXIT_REASON_MAP[reason]
  if (!cfg) return <span className="text-xs text-text-muted">—</span>
  return <Badge variant={cfg.variant} size="sm">{cfg.label}</Badge>
}

const columns: ColumnDef<DayRow>[] = [
  {
    accessorKey: 'date',
    header: 'Date',
    cell: ({ getValue }) => (
      <span className="font-mono text-xs text-text-muted">{String(getValue())}</span>
    ),
  },
  {
    accessorKey: 'weekday',
    header: 'Day',
    cell: ({ getValue }) => (
      <span className="text-xs text-text-muted">{String(getValue()).slice(0, 3)}</span>
    ),
  },
  {
    accessorKey: 'pnl',
    header: 'P&L',
    cell: ({ getValue }) => {
      const v = getValue() as number
      return (
        <span className={cn('font-mono text-sm font-medium', v >= 0 ? 'text-bullish' : 'text-bearish')}>
          {v >= 0 ? '+' : ''}₹{v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </span>
      )
    },
  },
  {
    accessorKey: 'trades',
    header: 'Trades',
    cell: ({ getValue }) => <span className="text-xs text-text-main">{String(getValue())}</span>,
  },
  {
    accessorKey: 're_entries',
    header: 'Re-entries',
    cell: ({ getValue }) => {
      const v = getValue() as number
      return v > 0 ? (
        <Badge variant="warning" size="sm">{v}</Badge>
      ) : (
        <span className="text-xs text-text-muted">—</span>
      )
    },
  },
  {
    accessorKey: 'exit_reason',
    header: 'Exit',
    cell: ({ getValue }) => <ExitReasonBadge reason={String(getValue())} />,
  },
]

interface Props {
  data: DayRow[]
}

export function DayWiseTable({ data }: Props) {
  return (
    <DataTable
      columns={columns}
      data={data}
      pageSize={15}
      emptyMessage="No trading days in results"
    />
  )
}
