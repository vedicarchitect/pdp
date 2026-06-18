import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/DataTable";
import type { ColumnDef } from "@tanstack/react-table";

interface Trade {
  id: number;
  order_id: number;
  security_id: string;
  exchange_segment: string;
  side: string;
  qty: number;
  fill_price: string;
  slippage_bps: string;
  charges: string;
  filled_at: string;
}

export function TradesTable() {
  const { data: trades = [], isLoading } = useQuery({
    queryKey: ["trades"],
    queryFn: async () => {
      const res = await fetch("/api/v1/trades");
      if (!res.ok) throw new Error("Failed to fetch trades");
      return res.json() as Promise<Trade[]>;
    },
  });

  const columns: ColumnDef<Trade>[] = [
    {
      accessorKey: "filled_at",
      header: "Time",
      cell: ({ row }) => new Date(row.original.filled_at).toLocaleTimeString(),
    },
    {
      accessorKey: "security_id",
      header: "Symbol",
    },
    {
      accessorKey: "side",
      header: "Side",
      cell: ({ row }) => (
        <span className={row.original.side === "BUY" ? "text-bullish font-bold" : "text-bearish font-bold"}>
          {row.original.side}
        </span>
      ),
    },
    {
      accessorKey: "qty",
      header: "Qty",
    },
    {
      accessorKey: "fill_price",
      header: "Fill Price",
      cell: ({ row }) => `₹ ${Number(row.original.fill_price).toFixed(2)}`,
    },
    {
      accessorKey: "charges",
      header: "Charges",
      cell: ({ row }) => `₹ ${Number(row.original.charges).toFixed(2)}`,
    },
  ];

  if (isLoading) return <div className="p-4 text-center text-text-muted">Loading trades...</div>;

  return (
    <DataTable
      columns={columns}
      data={trades}
      searchable
      pageSize={10}
      emptyMessage="No executed trades."
    />
  );
}
