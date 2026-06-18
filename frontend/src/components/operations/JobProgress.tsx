import { cn } from '@/lib/utils'

type Props = {
  progress: number
  message?: string
  className?: string
}

export function JobProgress({ progress, message, className }: Props) {
  const pct = Math.max(0, Math.min(100, progress))
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-center justify-between text-xs text-text-muted">
        {message && <span className="truncate max-w-[200px]">{message}</span>}
        <span className="ml-auto font-mono shrink-0">{pct}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-surface-raised overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
