import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Badge } from "@/components/ui/Badge";
import { InstrumentPicker } from "./InstrumentPicker";
import { useToast } from "@/components/ui/Toast";
import { useTradeMode, extractTradeModeFromResponse } from "@/hooks/useTradeMode";

export interface OrderPrefill {
  security_id?: string;
  exchange_segment?: string;
  side?: "BUY" | "SELL";
  qty?: number;
  order_type?: "MARKET" | "LIMIT";
  price?: number;
  product?: string;
}

interface OrderEntryProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  prefill?: OrderPrefill;
}

export function OrderEntry({ open, onOpenChange, prefill }: OrderEntryProps) {
  const [securityId, setSecurityId] = useState(prefill?.security_id || "");
  const [exchangeSegment, setExchangeSegment] = useState(prefill?.exchange_segment || "NSE_FO");
  const [side, setSide] = useState<"BUY" | "SELL">(prefill?.side || "BUY");
  const [qty, setQty] = useState<number | string>(prefill?.qty || "");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">(prefill?.order_type || "MARKET");
  const [price, setPrice] = useState<number | string>(prefill?.price || "");
  const [product, setProduct] = useState(prefill?.product || "INTRADAY");

  const { toast } = useToast();
  const queryClient = useQueryClient();
  const tradeMode = useTradeMode();
  const isLive = tradeMode === "live";

  useEffect(() => {
    if (open && prefill) {
      if (prefill.security_id) setSecurityId(prefill.security_id);
      if (prefill.exchange_segment) setExchangeSegment(prefill.exchange_segment);
      if (prefill.side) setSide(prefill.side);
      if (prefill.qty) setQty(prefill.qty);
      if (prefill.order_type) setOrderType(prefill.order_type);
      if (prefill.price) setPrice(prefill.price);
      if (prefill.product) setProduct(prefill.product);
    }
  }, [open, prefill]);

  const mutation = useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/v1/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          security_id: securityId,
          exchange_segment: exchangeSegment,
          side,
          qty: Number(qty),
          order_type: orderType,
          price: orderType === "LIMIT" ? Number(price) : undefined,
          product,
        })
      });
      extractTradeModeFromResponse(res);
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to place order");
      }
      return res.json();
    },
    onSuccess: () => {
      toast({ title: "Order Placed", description: `${side} ${securityId} submitted`, variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["positions"] });
      onOpenChange(false);
    },
    onError: (err: Error) => {
      toast({ title: "Order Failed", description: err.message || "An error occurred", variant: "error" });
    },
  });

  const estimatedCost = orderType === "LIMIT" && Number(price) > 0 && Number(qty) > 0
    ? (Number(price) * Number(qty)).toFixed(2)
    : "---";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex justify-between items-center">
            <span>New Order</span>
            {isLive ? (
              <Badge variant="danger" className="text-[10px] animate-pulse">LIVE — Real Money</Badge>
            ) : (
              <Badge variant="success">PAPER TRADING</Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {isLive ? "⚠️ Live trading enabled — real money orders." : "Paper mode — orders are simulated."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Instrument</label>
            <InstrumentPicker
              className="col-span-3"
              value={securityId}
              onChange={setSecurityId}
              onSelect={(inst) => setExchangeSegment(inst.segment || "NSE_FO")}
            />
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Side</label>
            <div className="col-span-3 flex rounded-md overflow-hidden border border-surface-border">
              <button
                type="button"
                className={`flex-1 py-1 text-sm font-bold transition-colors ${side === "BUY" ? "bg-bullish text-white" : "bg-transparent text-text hover:bg-surface-hover"}`}
                onClick={() => setSide("BUY")}
              >
                BUY
              </button>
              <button
                type="button"
                className={`flex-1 py-1 text-sm font-bold transition-colors ${side === "SELL" ? "bg-bearish text-white" : "bg-transparent text-text hover:bg-surface-hover"}`}
                onClick={() => setSide("SELL")}
              >
                SELL
              </button>
            </div>
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Type</label>
            <Select
              className="col-span-3"
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as "MARKET" | "LIMIT")}
            >
              <option value="MARKET">Market</option>
              <option value="LIMIT">Limit</option>
            </Select>
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Product</label>
            <Select
              className="col-span-3"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
            >
              <option value="INTRADAY">Intraday (MIS)</option>
              <option value="NRML">Normal (NRML)</option>
              <option value="DELIVERY">Delivery (CNC)</option>
            </Select>
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Quantity</label>
            <Input
              type="number"
              min="1"
              className="col-span-3"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              placeholder="e.g. 15"
            />
          </div>

          {orderType === "LIMIT" && (
            <div className="grid grid-cols-4 items-center gap-4">
              <label className="text-sm font-medium text-right">Price</label>
              <Input
                type="number"
                step="0.05"
                min="0"
                className="col-span-3"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="Limit Price"
              />
            </div>
          )}

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Est. Value</label>
            <div className="col-span-3 font-mono text-sm text-text-muted">
              ₹ {estimatedCost}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !securityId || !qty || (orderType === "LIMIT" && !price)}
            className={side === "BUY" ? "bg-bullish hover:bg-bullish/90" : "bg-bearish hover:bg-bearish/90"}
          >
            {mutation.isPending ? "Submitting..." : `Submit ${side}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
