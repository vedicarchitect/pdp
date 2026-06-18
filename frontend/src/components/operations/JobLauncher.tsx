import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'

const TASK_DEFS = [
  {
    id: 'housekeeping:backfill-spot',
    label: 'Backfill Spot',
    destructive: false,
    params: [
      { key: 'from_date', label: 'From date', placeholder: 'YYYY-MM-DD', type: 'text' },
      { key: 'to_date', label: 'To date', placeholder: 'YYYY-MM-DD', type: 'text' },
      { key: 'only_missing', label: 'Only missing', type: 'checkbox' },
      { key: 'dry_run', label: 'Dry run (preview)', type: 'checkbox' },
    ],
  },
  {
    id: 'housekeeping:backfill-options',
    label: 'Backfill Options',
    destructive: false,
    params: [
      { key: 'from_date', label: 'From date', placeholder: 'YYYY-MM-DD', type: 'text' },
      { key: 'to_date', label: 'To date', placeholder: 'YYYY-MM-DD', type: 'text' },
      { key: 'only_missing', label: 'Only missing', type: 'checkbox' },
      { key: 'dry_run', label: 'Dry run (preview)', type: 'checkbox' },
    ],
  },
  {
    id: 'housekeeping:validate-warehouse',
    label: 'Validate Warehouse',
    destructive: false,
    params: [],
  },
  {
    id: 'housekeeping:snapshot-instruments',
    label: 'Snapshot Instruments',
    destructive: false,
    params: [],
  },
  {
    id: 'housekeeping:reset-paper',
    label: 'Reset Paper Trading',
    destructive: true,
    params: [],
  },
  {
    id: 'ml_train',
    label: 'Train ML Model',
    destructive: false,
    params: [
      { key: 'security_id', label: 'Security ID', placeholder: '13', type: 'text' },
      { key: 'timeframe', label: 'Timeframe', placeholder: '15m', type: 'text' },
      { key: 'days', label: 'Training days', placeholder: '90', type: 'number' },
    ],
  },
] as const

type TaskDef = (typeof TASK_DEFS)[number]

async function submitJob(taskId: string, params: Record<string, unknown>): Promise<{ job_id: string }> {
  const url =
    taskId === 'ml_train'
      ? '/api/v1/ml/train'
      : `/api/v1/housekeeping/${taskId.replace('housekeeping:', '')}`

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? res.statusText)
  }
  return res.json()
}

type Props = {
  onJobLaunched: (jobId: string) => void
}

export function JobLauncher({ onJobLaunched }: Props) {
  const [selectedId, setSelectedId] = useState<string>(TASK_DEFS[0].id)
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({})
  const [confirmOpen, setConfirmOpen] = useState(false)

  const selected = TASK_DEFS.find((t) => t.id === selectedId) as TaskDef

  const mutation = useMutation({
    mutationFn: ({ id, params }: { id: string; params: Record<string, unknown> }) =>
      submitJob(id, params),
    onSuccess: (data) => {
      onJobLaunched(data.job_id)
      setParamValues({})
    },
  })

  const buildParams = () => {
    const out: Record<string, unknown> = {}
    for (const p of selected.params) {
      const val = paramValues[p.key]
      if (p.type === 'checkbox') {
        out[p.key] = Boolean(val)
      } else if (p.type === 'number') {
        if (val !== '' && val !== undefined) out[p.key] = Number(val)
      } else {
        if (val) out[p.key] = val
      }
    }
    return out
  }

  const handleLaunch = () => {
    if (selected.destructive) {
      setConfirmOpen(true)
    } else {
      mutation.mutate({ id: selected.id, params: buildParams() })
    }
  }

  const handleConfirmedLaunch = () => {
    setConfirmOpen(false)
    mutation.mutate({ id: selected.id, params: { ...buildParams(), confirm: true } })
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <Select
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value)
              setParamValues({})
            }}
            className="flex-1"
          >
            {TASK_DEFS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </Select>
          {selected.destructive && (
            <Badge variant="danger" size="sm">
              Destructive
            </Badge>
          )}
        </div>

        {'params' in selected && selected.params.length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {selected.params.map((p) => (
              <label key={p.key} className="flex flex-col gap-1 text-xs text-text-muted">
                {p.label}
                {p.type === 'checkbox' ? (
                  <div className="flex items-center gap-2 h-9">
                    <input
                      type="checkbox"
                      className="accent-primary w-4 h-4"
                      checked={Boolean(paramValues[p.key])}
                      onChange={(e) =>
                        setParamValues((v) => ({ ...v, [p.key]: e.target.checked }))
                      }
                    />
                    <span className="text-text-main">Enabled</span>
                  </div>
                ) : (
                  <Input
                    type={p.type}
                    placeholder={'placeholder' in p ? p.placeholder : ''}
                    value={(paramValues[p.key] as string) ?? ''}
                    onChange={(e) =>
                      setParamValues((v) => ({ ...v, [p.key]: e.target.value }))
                    }
                  />
                )}
              </label>
            ))}
          </div>
        )}

        {mutation.isError && (
          <p className="text-xs text-bearish">{(mutation.error as Error).message}</p>
        )}

        <Button
          variant={selected.destructive ? 'danger' : 'primary'}
          onClick={handleLaunch}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Launching…' : 'Launch'}
        </Button>
      </div>

      {/* Confirmation dialog for destructive operations (task 10) */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Destructive Operation</DialogTitle>
            <DialogDescription>
              This will delete <strong>all paper orders, trades, and positions</strong>. This
              cannot be undone. Are you sure?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={handleConfirmedLaunch}>
              Yes, Reset Paper
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
