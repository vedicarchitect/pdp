import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/Tabs'
import { OrderBook } from '@/components/orders/OrderBook'
import { TradesTable } from '@/components/orders/TradesTable'
import { PositionsPanel } from '@/components/orders/PositionsPanel'
import { OrderEntry } from '@/components/orders/OrderEntry'
import { ScannerView } from '@/components/scanner/ScannerView'
import { Plus } from 'lucide-react'
import { useOrdersWS } from '@/hooks/useOrdersWS'

export const Route = createFileRoute('/trading')({
  component: TradingPage,
})

function TradingPage() {
  const [isOrderEntryOpen, setIsOrderEntryOpen] = useState(false)
  useOrdersWS()

  return (
    <div className="flex-1 space-y-4 p-4 md:p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">Trading</h2>
        <div className="flex items-center space-x-2">
          <Button onClick={() => setIsOrderEntryOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" />
            New Order
          </Button>
        </div>
      </div>

      <OrderEntry 
        open={isOrderEntryOpen} 
        onOpenChange={setIsOrderEntryOpen} 
      />

      <Tabs defaultValue="positions" className="space-y-4">
        <TabsList>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="orders">Open Orders</TabsTrigger>
          <TabsTrigger value="trades">Executed Trades</TabsTrigger>
          <TabsTrigger value="scanner">Scanner</TabsTrigger>
        </TabsList>

        <TabsContent value="positions" className="space-y-4">
          <Card className="p-6">
            <PositionsPanel />
          </Card>
        </TabsContent>

        <TabsContent value="orders" className="space-y-4">
          <Card className="p-6">
            <OrderBook />
          </Card>
        </TabsContent>

        <TabsContent value="trades" className="space-y-4">
          <Card className="p-6">
            <TradesTable />
          </Card>
        </TabsContent>

        <TabsContent value="scanner" className="space-y-4">
          <Card className="p-6">
            <ScannerView />
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
