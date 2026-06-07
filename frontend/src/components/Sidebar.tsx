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
    <nav className="w-48 shrink-0 border-r border-gray-800 bg-gray-900 flex flex-col py-4 gap-1">
      {NAV_ITEMS.map(({ to, label }) => (
        <Link
          key={to}
          to={to}
          className="px-4 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-sm mx-2"
          activeProps={{ className: 'px-4 py-2 text-sm text-white bg-gray-700 rounded-sm mx-2' }}
          inactiveProps={{ className: 'px-4 py-2 text-sm text-gray-400 hover:text-white hover:bg-gray-800 rounded-sm mx-2' }}
        >
          {label}
        </Link>
      ))}
    </nav>
  )
}
