import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { NumberField } from '@/components/ui/NumberField'
import { Select } from '@/components/ui/Select'
import { Trash2, Plus, ShoppingCart } from 'lucide-react'
import type { PayoffLeg } from '../../types/builder'

interface Props {
  legs: PayoffLeg[]
  onChange: (legs: PayoffLeg[]) => void
  onTrade?: (leg: PayoffLeg) => void
}

export function LegTable({ legs, onChange, onTrade }: Props) {
  const updateLeg = (index: number, updates: Partial<PayoffLeg>) => {
    const newLegs = [...legs]
    newLegs[index] = { ...newLegs[index], ...updates }
    onChange(newLegs)
  }

  const removeLeg = (index: number) => {
    const newLegs = legs.filter((_, i) => i !== index)
    onChange(newLegs)
  }

  const addLeg = () => {
    onChange([
      ...legs,
      {
        id: crypto.randomUUID(),
        strike: 0,
        expiry: '',
        option_type: 'CE',
        side: 'BUY',
        lots: 1,
        premium: 0,
        iv: 0.2,
      },
    ])
  }

  return (
    <Card className="rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-surface text-xs text-text-muted uppercase tracking-wider font-semibold border-b border-surface-border">
            <tr>
              <th className="px-4 py-3">Strike</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Side</th>
              <th className="px-4 py-3">Lots</th>
              <th className="px-4 py-3">Premium</th>
              <th className="px-4 py-3 w-10"></th>
              {onTrade && <th className="px-4 py-3 w-10"></th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border">
            {legs.length === 0 ? (
              <tr>
                <td colSpan={onTrade ? 7 : 6} className="px-4 py-8 text-center text-text-muted">
                  No legs added. Select a template or add a leg from the chain.
                </td>
              </tr>
            ) : (
              legs.map((leg, i) => (
                <tr key={leg.id} className="hover:bg-surface/50 transition-colors">
                  <td className="px-4 py-2">
                    <NumberField
                      value={leg.strike}
                      onChange={(e: any) => updateLeg(i, { strike: Number(e.target.value) })}
                      className="w-24"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <Select
                      value={leg.option_type}
                      onChange={(e) => updateLeg(i, { option_type: e.target.value as 'CE' | 'PE' })}
                      className="w-20"
                    >
                      <option value="CE">CE</option>
                      <option value="PE">PE</option>
                    </Select>
                  </td>
                  <td className="px-4 py-2">
                    <Select
                      value={leg.side}
                      onChange={(e) => updateLeg(i, { side: e.target.value as 'BUY' | 'SELL' })}
                      className="w-24"
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </Select>
                  </td>
                  <td className="px-4 py-2">
                    <NumberField
                      value={leg.lots}
                      onChange={(e: any) => updateLeg(i, { lots: Number(e.target.value) })}
                      className="w-20"
                      min={1}
                    />
                  </td>
                  <td className="px-4 py-2">
                    <NumberField
                      value={leg.premium}
                      onChange={(e: any) => updateLeg(i, { premium: Number(e.target.value) })}
                      className="w-24"
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button variant="ghost" size="sm" className="px-2" onClick={() => removeLeg(i)} title="Remove Leg">
                      <Trash2 className="w-4 h-4 text-text-muted hover:text-danger" />
                    </Button>
                  </td>
                  {onTrade && (
                    <td className="px-4 py-2 text-right">
                      <Button variant="ghost" size="sm" className="px-2" onClick={() => onTrade(leg)} title="Trade this leg">
                        <ShoppingCart className="w-4 h-4 text-primary hover:text-bullish" />
                      </Button>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="p-3 border-t border-surface-border bg-surface/30">
        <Button variant="secondary" size="sm" onClick={addLeg}>
          <Plus className="w-4 h-4 mr-2" />
          Add Custom Leg
        </Button>
      </div>
    </Card>
  )
}
