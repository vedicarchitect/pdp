import type { FeedStatus } from '../../types/intraday'

interface Props {
  marketStatus: FeedStatus
  ordersStatus: FeedStatus
  portfolioStatus: FeedStatus
}

function statusDot(status: FeedStatus): string {
  switch (status) {
    case 'connected': return 'bg-green-500'
    case 'connecting': return 'bg-yellow-500 animate-pulse'
    case 'disconnected': return 'bg-red-500'
  }
}

function label(status: FeedStatus): string {
  switch (status) {
    case 'connected': return 'Connected'
    case 'connecting': return 'Connecting…'
    case 'disconnected': return 'Disconnected'
  }
}

export function ConnectionBadge({ marketStatus, ordersStatus, portfolioStatus }: Props) {
  const allConnected =
    marketStatus === 'connected' &&
    ordersStatus === 'connected' &&
    portfolioStatus === 'connected'

  if (allConnected) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-green-400">
        <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
        Live
      </div>
    )
  }

  return (
    <div className="flex items-center gap-3 text-xs">
      {[
        { label: 'Market', status: marketStatus },
        { label: 'Orders', status: ordersStatus },
        { label: 'Portfolio', status: portfolioStatus },
      ].map(({ label: name, status }) => (
        <div key={name} className="flex items-center gap-1">
          <span className={`w-2 h-2 rounded-full inline-block ${statusDot(status)}`} />
          <span className={status === 'disconnected' ? 'text-red-400 font-medium' : 'text-gray-400'}>
            {name}: {label(status)}
          </span>
        </div>
      ))}
      {(marketStatus === 'disconnected' || ordersStatus === 'disconnected' || portfolioStatus === 'disconnected') && (
        <span className="px-2 py-0.5 bg-red-900 border border-red-700 rounded text-red-300 font-medium">
          Disconnected
        </span>
      )}
    </div>
  )
}
