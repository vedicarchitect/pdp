import { useTradeMode } from '../hooks/useTradeMode'

export default function ModeBanner() {
  const mode = useTradeMode()

  if (mode === 'live') {
    return (
      <div className="w-full bg-bearish text-white text-center text-xs py-1.5 font-bold tracking-widest uppercase shadow-md shadow-bearish/20 z-50 sticky top-0 border-b border-bearish/50">
        Live Mode — Real money at risk
      </div>
    )
  }

  return (
    <div className="w-full bg-warning/90 backdrop-blur-sm text-background text-center text-xs py-1.5 font-bold tracking-widest uppercase shadow-md shadow-warning/20 z-50 sticky top-0 border-b border-warning/50">
      Paper Mode — Trades are simulated
    </div>
  )
}
