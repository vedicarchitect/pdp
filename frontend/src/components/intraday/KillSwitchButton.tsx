import { useRef, useState } from 'react'

interface KillResult {
  status: string
  cancelled_orders: { id: string; security_id: string; strategy_id?: string }[]
  flattened_positions: { security_id: string; qty_flattened: number }[]
  errors: string[]
}

type UIState = 'idle' | 'confirming' | 'calling' | 'success' | 'error'

const MAX_RETRIES = 3
const BASE_DELAY_MS = 1_000

async function callKillSwitch(attempt = 0): Promise<KillResult> {
  try {
    const res = await fetch('/api/v1/risk/kill', { method: 'POST' })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json() as Promise<KillResult>
  } catch (err) {
    if (attempt < MAX_RETRIES - 1) {
      await new Promise((r) => setTimeout(r, BASE_DELAY_MS * 2 ** attempt))
      return callKillSwitch(attempt + 1)
    }
    throw err
  }
}

export function KillSwitchButton() {
  const [uiState, setUiState] = useState<UIState>('idle')
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function showToast(msg: string) {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 5_000)
  }

  async function execute() {
    setUiState('calling')
    try {
      const result = await callKillSwitch()
      setUiState('success')
      showToast(`Kill-switch executed: cancelled ${result.cancelled_orders.length} orders, flattened ${result.flattened_positions.length} positions`)
      setTimeout(() => setUiState('idle'), 3_000)
    } catch {
      setUiState('error')
      showToast('Kill-switch failed after 3 retries. Please retry manually or call your broker.')
      setTimeout(() => setUiState('idle'), 5_000)
    }
  }

  const isBusy = uiState === 'calling'

  return (
    <div className="relative">
      {/* Main kill-switch button */}
      <button
        onClick={() => setUiState('confirming')}
        disabled={isBusy}
        className="px-4 py-2 bg-bearish/90 hover:bg-bearish disabled:bg-bearish/30 disabled:cursor-not-allowed text-white font-bold text-sm rounded-lg border border-bearish/50 shadow-md shadow-bearish/20 flex items-center gap-2 transition-all duration-200"
        aria-label="Kill switch — cancel all orders and flatten all positions"
      >
        {isBusy ? (
          <>
            <span className="animate-spin">⏳</span> Executing...
          </>
        ) : (
          <>
            <span>☠</span> Kill Switch
          </>
        )}
      </button>

      {/* Confirmation modal */}
      {uiState === 'confirming' && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 transition-opacity" role="dialog" aria-modal>
          <div className="glass-panel border-bearish/50 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl shadow-bearish/10 transform scale-100 transition-transform">
            <h2 className="text-lg font-bold text-bearish mb-2">⚠ Confirm Kill Switch</h2>
            <p className="text-text-muted text-sm mb-6 leading-relaxed">
              Are you sure? This will <strong className="text-text-main">cancel all open orders</strong> and <strong className="text-text-main">flatten all intraday positions</strong> at market price immediately. This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setUiState('idle')}
                className="px-4 py-2 bg-surface hover:bg-surface-hover text-text-main text-sm font-medium rounded-lg border border-surface-border transition-all duration-200"
              >
                Cancel
              </button>
              <button
                onClick={execute}
                className="px-4 py-2 bg-bearish hover:bg-bearish/90 text-white font-bold text-sm rounded-lg shadow-md shadow-bearish/20 transition-all duration-200"
              >
                Yes, Execute Kill Switch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 max-w-sm px-5 py-3.5 rounded-lg border text-sm font-medium z-50 shadow-xl transition-all duration-300 translate-y-0 ${
            uiState === 'error' || uiState === 'idle' && toast.includes('failed')
              ? 'glass-panel bg-bearish/10 border-bearish/40 text-bearish'
              : 'glass-panel bg-surface border-surface-border text-text-main'
          }`}
        >
          {toast}
        </div>
      )}
    </div>
  )
}
