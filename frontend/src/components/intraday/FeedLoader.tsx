import type { FeedStatus } from '../../types/intraday'

interface Props {
  marketStatus: FeedStatus
  ordersStatus: FeedStatus
  portfolioStatus: FeedStatus
  children: React.ReactNode
}

export function FeedLoader({ marketStatus, ordersStatus, portfolioStatus, children }: Props) {
  const anyConnecting =
    marketStatus === 'connecting' ||
    ordersStatus === 'connecting' ||
    portfolioStatus === 'connecting'

  const allConnected =
    marketStatus === 'connected' &&
    ordersStatus === 'connected' &&
    portfolioStatus === 'connected'

  if (!allConnected && anyConnecting) {
    return (
      <div className="flex items-center justify-center gap-3 py-16 text-gray-500">
        <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <span>Connecting to live feeds…</span>
      </div>
    )
  }

  return <>{children}</>
}
