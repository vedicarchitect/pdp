import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/DataTable";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import type { ColumnDef } from "@tanstack/react-table";

interface Order {
  id: number;
  client_order_id: string | null;
  broker: string;
  mode: string;
  security_id: string;
  exchange_segment: string;
  side: string;
  qty: number;
  order_type: string;
  price: string | null;
  trigger_price: string | null;
  product: string;
  status: string;
  placed_at: string | null;
  filled_at: string | null;
  cancelled_at: string | null;
  reject_reason: string | null;
}

export function OrderBook() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["orders"],
    queryFn: async () => {
      const res = await fetch("/api/v1/orders");
      if (!res.ok) throw new Error("Failed to fetch orders");
      return res.json() as Promise<Order[]>;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: async (orderId: number) => {
      const res = await fetch(`/api/v1/orders/${orderId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to cancel order");
      return res.json();
    },
    onSuccess: () => {
      toast({ title: "Order Cancelled", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
    onError: (err: any) => {
      toast({ title: "Cancel Failed", description: err.message, variant: "error" });
    },
  });

  const columns: ColumnDef<Order>[] = [
    {
      accessorKey: "placed_at",
      header: "Time",
      cell: ({ row }) => row.original.placed_at ? new Date(row.original.placed_at).toLocaleTimeString() : "-",
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
      accessorKey: "order_type",
      header: "Type",
    },
    {
      accessorKey: "price",
      header: "Price",
      cell: ({ row }) => row.original.price || "MKT",
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }) => {
        const s = row.original.status;
        let variant: "default" | "success" | "danger" | "warning" | "outline" = "outline";
        if (s === "FILLED") variant = "success";
        else if (s === "REJECTED" || s === "CANCELLED") variant = "danger";
        else if (s === "OPEN" || s === "PENDING") variant = "warning";
        return <Badge variant={variant}>{s}</Badge>;
      },
    },
    {
      id: "actions",
      cell: ({ row }) => {
        if (row.original.status === "OPEN" || row.original.status === "PENDING") {
          return (
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                cancelMutation.mutate(row.original.id);
              }}
              disabled={cancelMutation.isPending}
            >
              Cancel
            </Button>
          );
        }
        return null;
      },
    },
  ];

  if (isLoading) return <div className="p-4 text-center text-text-muted">Loading orders...</div>;

  return (
    <DataTable
      columns={columns}
      data={orders}
      searchable
      pageSize={10}
      emptyMessage="No orders found."
    />
  );
}
