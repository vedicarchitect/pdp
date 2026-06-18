import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { JobLauncher } from '@/components/operations/JobLauncher'
import { JobTable } from '@/components/operations/JobTable'

export const Route = createFileRoute('/operations')({
  component: OperationsPage,
})

function OperationsPage() {
  const qc = useQueryClient()
  const handleJobLaunched = (_jobId: string) => {
    qc.invalidateQueries({ queryKey: ['jobs'] })
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-text-main tracking-tight">Operations</h1>

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-4">
          Launch Job
        </h2>
        <JobLauncher onJobLaunched={handleJobLaunched} />
      </Card>

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider mb-4">
          Job History
        </h2>
        <JobTable />
      </Card>
    </div>
  )
}
