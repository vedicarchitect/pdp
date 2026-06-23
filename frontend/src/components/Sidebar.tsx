import { useState, useEffect } from 'react'
import { Link } from '@tanstack/react-router'
import {
  LayoutDashboard,
  Activity,
  Briefcase,
  PieChart,
  BarChart2,
  Hammer,
  Database,
  Search,
  History,
  AlertTriangle,
  Settings,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  ArrowUpDown
} from 'lucide-react'
import { Tooltip } from './ui/Tooltip'
import { cn } from '@/lib/utils'
import ModeBanner from './ModeBanner'
import { useUnreadEvents } from '@/hooks/useEventsWS'

type NavItem = {
  to: string;
  label: string;
  icon: React.ElementType;
  shortcut?: string;
}

type NavGroup = {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: 'TRADING',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, shortcut: '⌘1' },
      { to: '/intraday', label: 'Intraday', icon: Activity, shortcut: '⌘2' },
      { to: '/positional', label: 'Positional', icon: Briefcase, shortcut: '⌘3' },
      { to: '/trading', label: 'Trading', icon: ArrowUpDown, shortcut: '⌘4' },
      { to: '/strategies', label: 'Strategies', icon: PieChart, shortcut: '⌘5' },
    ]
  },
  {
    title: 'OPTIONS',
    items: [
      { to: '/analytics', label: 'Analytics', icon: BarChart2, shortcut: '⌘5' },
      { to: '/builder', label: 'Builder', icon: Hammer, shortcut: '⌘6' },
    ]
  },
  {
    title: 'DATA',
    items: [
      { to: '/portfolio', label: 'Portfolio', icon: Database, shortcut: '⌘7' },
      { to: '/instruments', label: 'Instruments', icon: Search, shortcut: '⌘8' },
      { to: '/backtest', label: 'Backtest', icon: History, shortcut: '⌘9' },
    ]
  },
  {
    title: 'SYSTEM',
    items: [
      { to: '/events', label: 'Events', icon: Activity },
      { to: '/alerts', label: 'Alerts', icon: AlertTriangle },
      { to: '/operations', label: 'Operations', icon: Settings },
    ]
  }
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('sidebar_collapsed') === 'true'
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const unreadEvents = useUnreadEvents()

  useEffect(() => {
    localStorage.setItem('sidebar_collapsed', collapsed.toString())
  }, [collapsed])

  const toggleCollapse = () => setCollapsed((prev) => !prev)
  const toggleMobile = () => setMobileOpen((prev) => !prev)
  const closeMobile = () => setMobileOpen(false)

  return (
    <>
      {/* Mobile Hamburger Button */}
      <button 
        onClick={toggleMobile}
        aria-label="Open menu"
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-surface rounded-md border border-surface-border shadow-sm text-text-main"
      >
        <Menu size={20} />
      </button>

      {/* Mobile Overlay */}
      {mobileOpen && (
        <div 
          className="md:hidden fixed inset-0 bg-black/60 z-40 backdrop-blur-sm"
          onClick={closeMobile}
        />
      )}

      {/* Sidebar Container */}
      <nav 
        className={cn(
          "fixed md:static inset-y-0 left-0 z-50 flex flex-col bg-surface border-r border-surface-border shadow-lg transition-all duration-300 ease-in-out transform",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
          collapsed ? "md:w-[68px]" : "md:w-64 w-64"
        )}
      >
        {/* Header */}
        <div className={cn("flex items-center h-16 shrink-0 border-b border-surface-border px-4", collapsed ? "justify-center" : "justify-between")}>
          {!collapsed && (
            <h1 className="text-xl font-bold text-text-main tracking-tight">
              PDP <span className="text-primary font-medium">Platform</span>
            </h1>
          )}
          {collapsed && (
            <div className="w-8 h-8 rounded bg-primary/20 flex items-center justify-center text-primary font-bold">
              P
            </div>
          )}
          
          <button 
            onClick={toggleCollapse}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden md:flex p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-text-main transition-colors"
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
          
          <button 
            onClick={closeMobile}
            aria-label="Close menu"
            className="md:hidden p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-text-main"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation Content */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden py-4 scrollbar-thin">
          <div className="flex flex-col gap-6">
            {NAV_GROUPS.map((group, groupIdx) => (
              <div key={groupIdx} className="flex flex-col px-3">
                {!collapsed && (
                  <div className="px-3 mb-2 text-[11px] font-semibold tracking-wider text-text-muted uppercase">
                    {group.title}
                  </div>
                )}
                {collapsed && (
                  <div className="mx-auto mb-2 w-4 h-[1px] bg-surface-border" />
                )}
                <div className="flex flex-col gap-1">
                  {group.items.map((item) => (
                    <Tooltip 
                      key={item.to} 
                      content={
                        <div className="flex items-center gap-2">
                          {item.label}
                          {item.shortcut && <span className="text-text-muted text-[10px] bg-surface px-1 rounded border border-surface-border">{item.shortcut}</span>}
                        </div>
                      } 
                      placement="right" 
                      className={cn(collapsed ? "block" : "hidden")}
                    >
                      <Link
                        to={item.to}
                        onClick={closeMobile}
                        className={cn(
                          "flex items-center relative group text-sm font-medium transition-all duration-200 rounded-lg",
                          collapsed ? "justify-center h-10 w-10 mx-auto" : "gap-3 px-3 py-2.5 w-full"
                        )}
                        activeProps={{ 
                          className: 'text-white bg-primary shadow-md shadow-primary/20' 
                        }}
                        inactiveProps={{ 
                          className: 'text-text-muted hover:text-text-main hover:bg-surface-hover' 
                        }}
                      >
                        <item.icon size={18} className={cn(collapsed && "shrink-0")} />
                        {collapsed && item.to === '/events' && unreadEvents > 0 && (
                          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-bearish text-white text-[9px] font-bold flex items-center justify-center leading-none">
                            {unreadEvents > 99 ? '99+' : unreadEvents}
                          </span>
                        )}
                        {!collapsed && (
                          <>
                            <span className="flex-1 truncate">{item.label}</span>
                            {item.to === '/events' && unreadEvents > 0 ? (
                              <span className="min-w-[20px] h-5 px-1.5 rounded-full bg-bearish text-white text-[10px] font-bold flex items-center justify-center leading-none">
                                {unreadEvents > 99 ? '99+' : unreadEvents}
                              </span>
                            ) : item.shortcut ? (
                              <span className="text-[10px] font-mono text-text-subtle px-1.5 py-0.5 rounded-md border border-surface-border bg-surface-raised group-hover:border-text-subtle/30 transition-colors">
                                {item.shortcut}
                              </span>
                            ) : null}
                          </>
                        )}
                      </Link>
                    </Tooltip>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-surface-border p-4 bg-surface-raised/30">
          <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-start")}>
            <ModeBanner collapsed={collapsed} />
          </div>
        </div>
      </nav>
    </>
  )
}
