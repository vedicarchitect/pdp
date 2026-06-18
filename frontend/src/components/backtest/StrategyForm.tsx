import { useState } from 'react'
import { Plus, Trash2, Play } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { NumberField } from '@/components/ui/NumberField'
import { Select } from '@/components/ui/Select'
import { Switch } from '@/components/ui/Switch'


interface LegDef {
  type: 'CE' | 'PE'
  side: 'BUY' | 'SELL'
  lots: number
  strike_selection: {
    method: 'atm_offset' | 'by_premium' | 'by_delta'
    offset: number
    target_premium?: number
  }
}

interface FormState {
  name: string
  underlying: string
  from_date: string
  to_date: string
  expiry_selection: 'weekly' | 'monthly' | 'nearest'
  entry_time: string
  exit_time: string
  legs: LegDef[]
  lot_size: number
  commissions: boolean
  combined_sl_enabled: boolean
  combined_sl_value: number
  combined_target_enabled: boolean
  combined_target_value: number
  trailing_sl_enabled: boolean
  trail_after: number
  trail_step: number
  re_entry_enabled: boolean
  re_entry_max: number
}

function defaultLeg(type: 'CE' | 'PE'): LegDef {
  return {
    type,
    side: 'SELL',
    lots: 1,
    strike_selection: { method: 'atm_offset', offset: 0 },
  }
}

interface Props {
  onSubmit: (payload: object) => void
  isLoading: boolean
}

export function StrategyForm({ onSubmit, isLoading }: Props) {
  const today = new Date().toISOString().slice(0, 10)
  const threeMonthsAgo = new Date(Date.now() - 90 * 86400_000).toISOString().slice(0, 10)

  const [form, setForm] = useState<FormState>({
    name: 'Short Straddle 9:20',
    underlying: 'NIFTY',
    from_date: threeMonthsAgo,
    to_date: today,
    expiry_selection: 'weekly',
    entry_time: '09:20',
    exit_time: '15:10',
    legs: [defaultLeg('CE'), defaultLeg('PE')],
    lot_size: 75,
    commissions: true,
    combined_sl_enabled: true,
    combined_sl_value: 50,
    combined_target_enabled: true,
    combined_target_value: 30,
    trailing_sl_enabled: true,
    trail_after: 20,
    trail_step: 5,
    re_entry_enabled: false,
    re_entry_max: 2,
  })

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const setLeg = (i: number, patch: Partial<LegDef>) =>
    setForm((f) => {
      const legs = [...f.legs]
      legs[i] = { ...legs[i], ...patch }
      return { ...f, legs }
    })

  const addLeg = () =>
    setForm((f) => ({
      ...f,
      legs: [...f.legs, defaultLeg(f.legs.length % 2 === 0 ? 'CE' : 'PE')],
    }))

  const removeLeg = (i: number) =>
    setForm((f) => ({ ...f, legs: f.legs.filter((_, j) => j !== i) }))

  const buildPayload = () => ({
    type: 'options-strategy',
    name: form.name,
    underlying: form.underlying,
    date_range: { from: form.from_date, to: form.to_date },
    expiry_selection: form.expiry_selection,
    entry: {
      time_ist: form.entry_time,
      legs: form.legs.map((l) => ({
        type: l.type,
        side: l.side,
        lots: l.lots,
        strike_selection: l.strike_selection,
      })),
    },
    exit: { time_ist: form.exit_time },
    risk: {
      combined_sl: form.combined_sl_enabled ? { type: 'points', value: form.combined_sl_value } : null,
      combined_target: form.combined_target_enabled ? { type: 'points', value: form.combined_target_value } : null,
      per_leg_sl: null,
      trailing_sl: {
        enabled: form.trailing_sl_enabled,
        trail_after: form.trail_after,
        trail_step: form.trail_step,
      },
      re_entry: {
        enabled: form.re_entry_enabled,
        max_count: form.re_entry_max,
      },
    },
    lot_size: form.lot_size,
    commissions: form.commissions,
  })

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="text-sm">Strategy Config</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {/* Name + Underlying */}
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-text-muted mb-1 block">Name</label>
            <Input value={form.name} onChange={(e) => set('name', e.target.value)} className="text-sm" />
          </div>
          <div className="w-28">
            <label className="text-xs text-text-muted mb-1 block">Underlying</label>
            <Select value={form.underlying} onChange={(e) => set('underlying', e.target.value)}>
              <option value="NIFTY">NIFTY</option>
              <option value="BANKNIFTY">BANKNIFTY</option>
              <option value="SENSEX">SENSEX</option>
            </Select>
          </div>
        </div>

        {/* Date range */}
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-text-muted mb-1 block">From</label>
            <Input type="date" value={form.from_date} onChange={(e) => set('from_date', e.target.value)} className="text-sm" />
          </div>
          <div className="flex-1">
            <label className="text-xs text-text-muted mb-1 block">To</label>
            <Input type="date" value={form.to_date} onChange={(e) => set('to_date', e.target.value)} className="text-sm" />
          </div>
        </div>

        {/* Expiry + Entry/Exit times */}
        <div className="flex gap-2">
          <div className="w-28">
            <label className="text-xs text-text-muted mb-1 block">Expiry</label>
            <Select value={form.expiry_selection} onChange={(e) => set('expiry_selection', e.target.value as 'weekly' | 'monthly' | 'nearest')}>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="nearest">Nearest</option>
            </Select>
          </div>
          <div className="flex-1">
            <label className="text-xs text-text-muted mb-1 block">Entry (IST)</label>
            <Input type="time" value={form.entry_time} onChange={(e) => set('entry_time', e.target.value)} className="text-sm" />
          </div>
          <div className="flex-1">
            <label className="text-xs text-text-muted mb-1 block">Exit (IST)</label>
            <Input type="time" value={form.exit_time} onChange={(e) => set('exit_time', e.target.value)} className="text-sm" />
          </div>
        </div>

        {/* Legs */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-medium text-text-muted uppercase tracking-wide">Legs</label>
            <Button variant="ghost" size="sm" onClick={addLeg} className="h-6 px-2 text-xs gap-1">
              <Plus size={12} /> Add Leg
            </Button>
          </div>
          <div className="flex flex-col gap-2">
            {form.legs.map((leg, i) => (
              <div key={i} className="flex gap-2 items-center p-2 rounded border border-surface-border bg-surface-raised/30">
                <Select
                  value={leg.type}
                  onChange={(e) => setLeg(i, { type: e.target.value as 'CE' | 'PE' })}
                  className="w-16 text-xs"
                >
                  <option value="CE">CE</option>
                  <option value="PE">PE</option>
                </Select>
                <Select
                  value={leg.side}
                  onChange={(e) => setLeg(i, { side: e.target.value as 'BUY' | 'SELL' })}
                  className="w-16 text-xs"
                >
                  <option value="SELL">SELL</option>
                  <option value="BUY">BUY</option>
                </Select>
                <NumberField
                  value={leg.lots}
                  min={1}
                  onChange={(e) => setLeg(i, { lots: parseInt(e.target.value) || 1 })}
                  className="w-14 text-xs"
                  placeholder="Lots"
                />
                <Select
                  value={leg.strike_selection.method}
                  onChange={(e) => setLeg(i, {
                    strike_selection: {
                      ...leg.strike_selection,
                      method: e.target.value as 'atm_offset' | 'by_premium' | 'by_delta',
                    },
                  })}
                  className="flex-1 text-xs"
                >
                  <option value="atm_offset">ATM offset</option>
                  <option value="by_premium">By premium</option>
                  <option value="by_delta">By delta</option>
                </Select>
                {leg.strike_selection.method === 'atm_offset' && (
                  <NumberField
                    value={leg.strike_selection.offset}
                    onChange={(e) => setLeg(i, {
                      strike_selection: { ...leg.strike_selection, offset: parseInt(e.target.value) || 0 },
                    })}
                    className="w-16 text-xs"
                    placeholder="±N"
                  />
                )}
                {leg.strike_selection.method === 'by_premium' && (
                  <NumberField
                    value={leg.strike_selection.target_premium || ''}
                    onChange={(e) => setLeg(i, {
                      strike_selection: { ...leg.strike_selection, target_premium: parseFloat(e.target.value) || 0 },
                    })}
                    className="w-16 text-xs"
                    placeholder="₹"
                  />
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeLeg(i)}
                  className="h-7 w-7 p-0 text-text-muted hover:text-bearish"
                  disabled={form.legs.length <= 1}
                >
                  <Trash2 size={12} />
                </Button>
              </div>
            ))}
          </div>
        </div>

        {/* Risk */}
        <div className="flex flex-col gap-3">
          <label className="text-xs font-medium text-text-muted uppercase tracking-wide">Risk</label>

          {/* Combined SL */}
          <div className="flex items-center gap-2">
            <Switch
              checked={form.combined_sl_enabled}
              onChange={(e) => set('combined_sl_enabled', e.target.checked)}
            />
            <span className="text-xs text-text-main w-24">Combined SL</span>
            {form.combined_sl_enabled && (
              <div className="flex items-center gap-1">
                <NumberField
                  value={form.combined_sl_value}
                  min={1}
                  onChange={(e) => set('combined_sl_value', parseFloat(e.target.value) || 0)}
                  className="w-20 text-xs"
                />
                <span className="text-xs text-text-muted">pts</span>
              </div>
            )}
          </div>

          {/* Combined Target */}
          <div className="flex items-center gap-2">
            <Switch
              checked={form.combined_target_enabled}
              onChange={(e) => set('combined_target_enabled', e.target.checked)}
            />
            <span className="text-xs text-text-main w-24">Target</span>
            {form.combined_target_enabled && (
              <div className="flex items-center gap-1">
                <NumberField
                  value={form.combined_target_value}
                  min={1}
                  onChange={(e) => set('combined_target_value', parseFloat(e.target.value) || 0)}
                  className="w-20 text-xs"
                />
                <span className="text-xs text-text-muted">pts</span>
              </div>
            )}
          </div>

          {/* Trailing SL */}
          <div className="flex items-center gap-2 flex-wrap">
            <Switch
              checked={form.trailing_sl_enabled}
              onChange={(e) => set('trailing_sl_enabled', e.target.checked)}
            />
            <span className="text-xs text-text-main w-24">Trailing SL</span>
            {form.trailing_sl_enabled && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">after</span>
                <NumberField
                  value={form.trail_after}
                  min={1}
                  onChange={(e) => set('trail_after', parseFloat(e.target.value) || 0)}
                  className="w-16 text-xs"
                />
                <span className="text-xs text-text-muted">step</span>
                <NumberField
                  value={form.trail_step}
                  min={1}
                  onChange={(e) => set('trail_step', parseFloat(e.target.value) || 0)}
                  className="w-16 text-xs"
                />
                <span className="text-xs text-text-muted">pts</span>
              </div>
            )}
          </div>

          {/* Re-entry */}
          <div className="flex items-center gap-2">
            <Switch
              checked={form.re_entry_enabled}
              onChange={(e) => set('re_entry_enabled', e.target.checked)}
            />
            <span className="text-xs text-text-main w-24">Re-entry</span>
            {form.re_entry_enabled && (
              <div className="flex items-center gap-1">
                <span className="text-xs text-text-muted">max</span>
                <NumberField
                  value={form.re_entry_max}
                  min={1}
                  max={5}
                  onChange={(e) => set('re_entry_max', parseInt(e.target.value) || 1)}
                  className="w-16 text-xs"
                />
                <span className="text-xs text-text-muted">×</span>
              </div>
            )}
          </div>
        </div>

        {/* Lot size + commissions */}
        <div className="flex gap-2 items-center">
          <div className="w-28">
            <label className="text-xs text-text-muted mb-1 block">Lot size</label>
            <NumberField
              value={form.lot_size}
              min={1}
              onChange={(e) => set('lot_size', parseInt(e.target.value) || 1)}
              className="text-sm"
            />
          </div>
          <div className="flex items-center gap-2 mt-5">
            <Switch checked={form.commissions} onChange={(e) => set('commissions', e.target.checked)} />
            <span className="text-xs text-text-muted">Commissions</span>
          </div>
        </div>

        {/* Submit */}
        <Button
          onClick={() => onSubmit(buildPayload())}
          disabled={isLoading || form.legs.length === 0}
          className="w-full gap-2"
        >
          <Play size={14} />
          {isLoading ? 'Running…' : 'Run Backtest'}
        </Button>
      </CardContent>
    </Card>
  )
}
