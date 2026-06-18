import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import { DataTable } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'

export const Route = createFileRoute('/instruments')({
  component: InstrumentsPage,
})

interface Instrument {
  security_id: string
  exchange_segment: string
  trading_symbol: string
  instrument_type: string
  underlying: string | null
  expiry: string | null
  strike: string | null
  option_type: string | null
  lot_size: number
  tick_size: string
}

const SEGMENTS = ['NSE_EQ', 'NSE_FNO', 'BSE_EQ', 'MCX_COMM', 'IDX_I'] as const
type Segment = typeof SEGMENTS[number]

function segmentVariant(seg: string): 'default' | 'info' | 'success' | 'warning' | 'danger' {
  if (seg.startsWith('NSE')) return 'info'
  if (seg.startsWith('BSE')) return 'success'
  if (seg.startsWith('MCX')) return 'warning'
  if (seg === 'IDX_I') return 'default'
  return 'default'
}

const columns: ColumnDef<Instrument>[] = [
  { accessorKey: 'trading_symbol', header: 'Symbol', cell: ({ getValue }) => (
    <span className="font-mono font-medium text-text-main">{getValue<string>()}</span>
  )},
  { accessorKey: 'exchange_segment', header: 'Segment', cell: ({ getValue }) => {
    const seg = getValue<string>()
    return <Badge variant={segmentVariant(seg)} size="sm">{seg}</Badge>
  }},
  { accessorKey: 'instrument_type', header: 'Type' },
  { accessorKey: 'underlying', header: 'Underlying', cell: ({ getValue }) => (
    <span className="text-text-muted">{getValue<string | null>() ?? '—'}</span>
  )},
  { accessorKey: 'expiry', header: 'Expiry', cell: ({ getValue }) => (
    <span className="font-mono text-text-muted">{getValue<string | null>() ?? '—'}</span>
  )},
  { accessorKey: 'strike', header: 'Strike', cell: ({ getValue }) => (
    <span className="font-mono">{getValue<string | null>() ? parseFloat(getValue<string>()).toFixed(0) : '—'}</span>
  )},
  { accessorKey: 'option_type', header: 'OT', cell: ({ getValue }) => {
    const ot = getValue<string | null>()
    if (!ot) return <span className="text-text-muted">—</span>
    return <span className={ot === 'CE' ? 'text-bullish font-medium' : 'text-bearish font-medium'}>{ot}</span>
  }},
  { accessorKey: 'lot_size', header: 'Lot' },
]

function InstrumentsPage() {
  const [segment, setSegment] = useState<Segment | ''>('')
  const params = new URLSearchParams({ limit: '100' })
  if (segment) params.set('segment', segment)

  const { data, isLoading } = useQuery<Instrument[]>({
    queryKey: ['instruments', segment],
    queryFn: () => fetch(`/api/v1/instruments?${params}`).then((r) => r.json()),
    staleTime: 60_000,
  })

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-text-main tracking-tight">Instruments</h1>

      {/* Segment filters */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setSegment('')}
          className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${segment === '' ? 'bg-primary text-white border-primary' : 'border-surface-border text-text-muted hover:text-text-main hover:border-text-subtle'}`}
        >
          All
        </button>
        {SEGMENTS.map((seg) => (
          <button
            key={seg}
            onClick={() => setSegment(seg)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${segment === seg ? 'bg-primary text-white border-primary' : 'border-surface-border text-text-muted hover:text-text-main hover:border-text-subtle'}`}
          >
            {seg}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Instrument Browser</CardTitle>
            {data && <span className="text-xs text-text-muted">{data.length} results</span>}
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-64 rounded-lg" />
          ) : (
            <DataTable
              data={data ?? []}
              columns={columns}
              searchable
              pageSize={25}
              emptyMessage="No instruments found"
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
