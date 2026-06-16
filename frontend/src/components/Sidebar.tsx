import { Link } from '@tanstack/react-router'
import { BarChart2 } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/intraday', label: 'Intraday', icon: null },
  { to: '/positional', label: 'Positional', icon: null },
  { to: '/portfolio', label: 'Portfolio', icon: null },
  { to: '/strategies', label: 'Strategies', icon: null },
  { to: '/analytics', label: 'Analytics', icon: BarChart2 },
  { to: '/backtest', label: 'Backtest', icon: null },
  { to: '/instruments', label: 'Instruments', icon: null },
] as const

export default function Sidebar() {
  return (
    <nav className="w-64 shrink-0 border-r border-surface-border bg-surface flex flex-col py-6 gap-2 shadow-lg z-10">
      <div className="px-6 pb-6">
        <h1 className="text-xl font-bold text-text-main tracking-tight">PDP <span className="text-primary font-medium">Platform</span></h1>
      </div>
      <div className="flex flex-col gap-1 px-3">
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <Link
          key={to}
          to={to}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-text-muted hover:text-text-main hover:bg-surface-hover rounded-lg transition-all duration-200"
          activeProps={{ className: 'flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-primary shadow-md shadow-primary/20 rounded-lg transition-all duration-200' }}
          inactiveProps={{ className: 'flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-text-muted hover:text-text-main hover:bg-surface-hover rounded-lg transition-all duration-200' }}
        >
          {Icon && <Icon size={15} />}
          {label}
        </Link>
      ))}
      </div>
    </nav>
  )
}
