import { useTradeMode } from '../hooks/useTradeMode'

export default function ModeBanner() {
  const mode = useTradeMode()

  if (mode === 'live') {
    return (
      <div className="w-full bg-red-700 text-white text-center text-xs py-1 font-medium tracking-wide">
        LIVE MODE — real money at risk
      </div>
    )
  }

  return (
    <div className="w-full bg-yellow-500 text-black text-center text-xs py-1 font-medium tracking-wide">
      PAPER MODE — trades are simulated
    </div>
  )
}
