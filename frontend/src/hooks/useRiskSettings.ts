import { useQuery } from '@tanstack/react-query'
import type { RiskSettings } from '../types/intraday'

const DEFAULTS: RiskSettings = {
  RISK_DAILY_LOSS_CAP_INR: 50_000,
  RISK_PER_STRATEGY_LOSS_CAP_INR: 20_000,
  RISK_SOFT_CAP_PCT: 80,
}

async function fetchRiskSettings(): Promise<RiskSettings> {
  const res = await fetch('/api/v1/settings/risk')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<RiskSettings>
}

export function useRiskSettings(): { settings: RiskSettings; isDefault: boolean; isLoading: boolean } {
  const { data, isError, isLoading } = useQuery({
    queryKey: ['settings', 'risk'],
    queryFn: fetchRiskSettings,
    retry: 2,
    staleTime: 60_000,
  })

  return {
    settings: data ?? DEFAULTS,
    isDefault: isError || !data,
    isLoading,
  }
}
