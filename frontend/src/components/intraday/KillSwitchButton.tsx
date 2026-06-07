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
        className="px-4 py-2 bg-red-700 hover:bg-red-600 disabled:bg-red-900 disabled:cursor-not-allowed text-white font-bold text-sm rounded border border-red-500 flex items-center gap-2 transition-colors"
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
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" role="dialog" aria-modal>
          <div className="bg-gray-900 border border-red-700 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
            <h2 className="text-lg font-bold text-red-400 mb-2">⚠ Confirm Kill Switch</h2>
            <p className="text-gray-300 text-sm mb-6">
              Are you sure? This will <strong>cancel all open orders</strong> and <strong>flatten all intraday positions</strong> at market price immediately. This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setUiState('idle')}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={execute}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white font-bold text-sm rounded transition-colors"
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
          className={`fixed bottom-4 right-4 max-w-sm px-4 py-3 rounded border text-sm z-50 shadow-lg ${
            uiState === 'error' || uiState === 'idle' && toast.includes('failed')
              ? 'bg-red-900 border-red-600 text-red-200'
              : 'bg-gray-800 border-gray-600 text-gray-200'
          }`}
        >
          {toast}
        </div>
      )}
    </div>
  )
}
