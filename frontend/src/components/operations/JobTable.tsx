import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { DataTable } from '@/components/ui/DataTable'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/Dialog'
import { JobProgress } from './JobProgress'
import { useJobWS } from '@/hooks/useJobWS'
import { X, FileText } from 'lucide-react'

type Job = {
  id: string
  type: string
  status: string
  progress: number
  progress_message: string | null
  error: string | null
  logs: string | null
  result: unknown
  created_at: string
  started_at: string | null
  completed_at: string | null
}

async function fetchJobs(): Promise<Job[]> {
  const res = await fetch('/api/v1/jobs?limit=100')
  if (!res.ok) throw new Error('Failed to fetch jobs')
  const data = await res.json()
  return data.jobs
}

async function cancelJob(id: string): Promise<void> {
  const res = await fetch(`/api/v1/jobs/${id}/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error('Cancel failed')
}

function statusVariant(status: string): 'success' | 'danger' | 'warning' | 'info' | 'outline' {
  switch (status) {
    case 'COMPLETED': return 'success'
    case 'FAILED': return 'danger'
    case 'CANCELLED': return 'outline'
    case 'RUNNING': return 'info'
    default: return 'warning'
  }
}

function duration(job: Job): string {
  const start = job.started_at ? new Date(job.started_at).getTime() : null
  const end = job.completed_at ? new Date(job.completed_at).getTime() : null
  if (!start) return '—'
  const ms = (end ?? Date.now()) - start
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  return `${Math.round(ms / 60_000)}m`
}

function LiveProgress({ job }: { job: Job }) {
  const ws = useJobWS(job.status === 'RUNNING' ? job.id : null)
  const progress = job.status === 'RUNNING' ? ws.progress || job.progress : job.progress
  const message = job.status === 'RUNNING' ? ws.message || job.progress_message || '' : job.progress_message || ''
  if (job.status === 'PENDING') return <span className="text-xs text-text-muted">Pending…</span>
  if (job.status === 'COMPLETED') return <span className="text-xs text-bullish">Done</span>
  if (job.status === 'CANCELLED') return <span className="text-xs text-text-muted">Cancelled</span>
  if (job.status === 'FAILED') return <span className="text-xs text-bearish truncate max-w-[140px]">{job.error ?? 'Failed'}</span>
  return <JobProgress progress={progress} message={message} className="w-36" />
}

export function JobTable() {
  const qc = useQueryClient()
  const [logsJob, setLogsJob] = useState<Job | null>(null)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: fetchJobs,
    refetchInterval: 3000,
  })

  // Refetch when a new job is launched
  const cancel = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })

  const columns: ColumnDef<Job>[] = [
    {
      accessorKey: 'type',
      header: 'Type',
      cell: ({ row }) => (
        <span className="font-mono text-xs text-text-muted">{row.original.type}</span>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => (
        <Badge variant={statusVariant(row.original.status)} size="sm">
          {row.original.status}
        </Badge>
      ),
    },
    {
      id: 'progress',
      header: 'Progress',
      cell: ({ row }) => <LiveProgress job={row.original} />,
    },
    {
      id: 'duration',
      header: 'Duration',
      cell: ({ row }) => (
        <span className="text-xs text-text-muted font-mono">{duration(row.original)}</span>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => {
        const job = row.original
        return (
          <div className="flex items-center gap-1 justify-end">
            {(job.logs || job.error) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setLogsJob(job)}
                title="View logs"
                aria-label="View logs"
              >
                <FileText size={14} />
              </Button>
            )}
            {job.status === 'RUNNING' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => cancel.mutate(job.id)}
                title="Cancel job"
                aria-label="Cancel job"
                className="text-bearish hover:text-bearish"
              >
                <X size={14} />
              </Button>
            )}
          </div>
        )
      },
    },
  ]

  if (isLoading) {
    return <p className="text-sm text-text-muted py-4">Loading jobs…</p>
  }

  return (
    <>
      <DataTable
        columns={columns}
        data={jobs}
        emptyMessage="No jobs yet. Launch one above."
      />

      <Dialog open={!!logsJob} onOpenChange={(open) => !open && setLogsJob(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Job Logs — {logsJob?.type}</DialogTitle>
            <DialogDescription>{logsJob?.id}</DialogDescription>
          </DialogHeader>
          {logsJob?.error && (
            <pre className="text-xs text-bearish bg-surface-raised rounded p-3 overflow-auto max-h-32 whitespace-pre-wrap">
              {logsJob.error}
            </pre>
          )}
          {logsJob?.logs && (
            <pre className="text-xs text-text-muted bg-surface-raised rounded p-3 overflow-auto max-h-64 whitespace-pre-wrap">
              {logsJob.logs}
            </pre>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
