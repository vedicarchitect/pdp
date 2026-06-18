import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/DataTable";
import { Button } from "@/components/ui/Button";
import { OrderEntry } from "./OrderEntry";
import type { ColumnDef } from "@tanstack/react-table";

interface Position {
  id: number;
  security_id: string;
  exchange_segment: string;
  product: string;
  net_qty: number;
  avg_price: string;
  realized_pnl: string;
  unrealized_pnl: string;
  updated_at: string;
}

export function PositionsPanel() {
  const [closePosSecurity, setClosePosSecurity] = useState<{ id: string, side: "BUY" | "SELL", qty: number } | null>(null);

  const { data: positions = [], isLoading } = useQuery({
    queryKey: ["positions"],
    queryFn: async () => {
      const res = await fetch("/api/v1/positions");
      if (!res.ok) throw new Error("Failed to fetch positions");
      return res.json() as Promise<Position[]>;
    },
  });

  const columns: ColumnDef<Position>[] = [
    {
      accessorKey: "security_id",
      header: "Symbol",
    },
    {
      accessorKey: "net_qty",
      header: "Net Qty",
      cell: ({ row }) => (
        <span className={row.original.net_qty > 0 ? "text-bullish font-bold" : row.original.net_qty < 0 ? "text-bearish font-bold" : "text-text-muted"}>
          {row.original.net_qty}
        </span>
      ),
    },
    {
      accessorKey: "avg_price",
      header: "Avg Price",
      cell: ({ row }) => `₹ ${Number(row.original.avg_price).toFixed(2)}`,
    },
    {
      accessorKey: "unrealized_pnl",
      header: "MTM P&L",
      cell: ({ row }) => {
        const pnl = Number(row.original.unrealized_pnl);
        return (
          <span className={pnl > 0 ? "text-bullish font-bold" : pnl < 0 ? "text-bearish font-bold" : "text-text-muted"}>
            ₹ {pnl.toFixed(2)}
          </span>
        );
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        if (row.original.net_qty !== 0) {
          const side = row.original.net_qty > 0 ? "SELL" : "BUY";
          const qty = Math.abs(row.original.net_qty);
          return (
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                setClosePosSecurity({ id: row.original.security_id, side, qty });
              }}
            >
              Close
            </Button>
          );
        }
        return null;
      },
    },
  ];

  if (isLoading) return <div className="p-4 text-center text-text-muted">Loading positions...</div>;

  return (
    <>
      <DataTable
        columns={columns}
        data={positions}
        searchable
        pageSize={10}
        emptyMessage="No open positions."
      />
      
      {closePosSecurity && (
        <OrderEntry
          open={!!closePosSecurity}
          onOpenChange={(open) => !open && setClosePosSecurity(null)}
          prefill={{
            security_id: closePosSecurity.id,
            side: closePosSecurity.side,
            qty: closePosSecurity.qty,
            order_type: "MARKET",
          }}
        />
      )}
    </>
  );
}
