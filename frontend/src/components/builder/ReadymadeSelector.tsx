import { useQuery } from '@tanstack/react-query'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import type { ReadymadeStrategy } from '../../types/builder'

interface Props {
  underlying: string
  onSelect: (strategy: ReadymadeStrategy) => void
}

export function ReadymadeSelector({ underlying, onSelect }: Props) {
  const { data, isLoading } = useQuery<{ strategies: ReadymadeStrategy[] }>({
    queryKey: ['readymades', underlying],
    queryFn: async () => {
      const res = await fetch(`/api/v1/options/${underlying}/readymades`)
      if (!res.ok) throw new Error('Failed to fetch readymades')
      return res.json()
    },
  })

  if (isLoading) {
    return <Card className="p-4 rounded-xl text-text-muted text-sm text-center">Loading templates...</Card>
  }

  if (!data?.strategies) return null

  return (
    <Card className="p-4 rounded-xl">
      <div className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
        Readymade Templates
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {data.strategies.map((strategy) => (
          <Button
            key={strategy.name}
            variant="secondary"
            size="sm"
            onClick={() => onSelect(strategy)}
            className="w-full justify-start text-xs font-medium"
          >
            {strategy.name}
          </Button>
        ))}
      </div>
    </Card>
  )
}
