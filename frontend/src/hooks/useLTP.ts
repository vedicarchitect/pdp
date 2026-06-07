import { useState, useEffect } from 'react'
import { useMarketWS } from './useMarketWS'

const WS_DISABLED = import.meta.env.VITE_WS_DISABLED === 'true'

export function useLTP(securityId: string): number | undefined {
  const [ids] = useState(() => [securityId])
  const tick = useMarketWS(WS_DISABLED ? [] : ids)
  const [ltp, setLtp] = useState<number | undefined>(undefined)

  useEffect(() => {
    if (tick && tick.security_id === securityId) {
      setLtp(tick.ltp)
    }
  }, [tick, securityId])

  return ltp
}
