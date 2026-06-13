import { Link } from '@tanstack/react-router'

const NAV_ITEMS = [
  { to: '/intraday', label: 'Intraday' },
  { to: '/positional', label: 'Positional' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/strategies', label: 'Strategies' },
  { to: '/backtest', label: 'Backtest' },
  { to: '/instruments', label: 'Instruments' },
] as const

export default function Sidebar() {
  return (
    <nav className="w-64 shrink-0 border-r border-surface-border bg-surface flex flex-col py-6 gap-2 shadow-lg z-10">
      <div className="px-6 pb-6">
        <h1 className="text-xl font-bold text-text-main tracking-tight">PDP <span className="text-primary font-medium">Platform</span></h1>
      </div>
      <div className="flex flex-col gap-1 px-3">
      {NAV_ITEMS.map(({ to, label }) => (
        <Link
          key={to}
          to={to}
          className="px-4 py-2.5 text-sm font-medium text-text-muted hover:text-text-main hover:bg-surface-hover rounded-lg transition-all duration-200"
          activeProps={{ className: 'px-4 py-2.5 text-sm font-medium text-white bg-primary shadow-md shadow-primary/20 rounded-lg transition-all duration-200' }}
          inactiveProps={{ className: 'px-4 py-2.5 text-sm font-medium text-text-muted hover:text-text-main hover:bg-surface-hover rounded-lg transition-all duration-200' }}
        >
          {label}
        </Link>
      ))}
      </div>
    </nav>
  )
}
