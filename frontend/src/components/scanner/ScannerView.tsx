import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/DataTable";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { OrderEntry } from "@/components/orders/OrderEntry";
import type { ColumnDef } from "@tanstack/react-table";

interface ScannerRow {
  strike: string;
  type: string;
  oi_buildup: string;
  iv_rank: number | null;
  security_id: string;
}

export function ScannerView({ underlying = "NIFTY" }: { underlying?: string }) {
  const [selectedSecurity, setSelectedSecurity] = useState<{ id: string, side: "BUY" | "SELL" } | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["scanner", underlying],
    queryFn: async () => {
      // Graceful degradation handled by checking response status
      const [oiRes, ivRes] = await Promise.all([
        fetch(`/api/v1/options/${underlying}/oi-buildup`),
        fetch(`/api/v1/options/${underlying}/iv-history`)
      ]);

      if (oiRes.status === 404 || ivRes.status === 404) {
        throw new Error("Analytics upgrade required");
      }
      
      if (!oiRes.ok || !ivRes.ok) {
        throw new Error("Failed to fetch scanner data");
      }

      const oiData = await oiRes.json();
      const ivData = await ivRes.json();

      // Mock merge logic - assuming backend returns list of objects with matching strikes
      // In reality, this depends on the exact shape from Proposal #3
      const rows: ScannerRow[] = [];
      
      if (Array.isArray(oiData)) {
        for (const item of oiData) {
          const ivItem = Array.isArray(ivData) ? ivData.find((i: any) => i.strike === item.strike && i.type === item.type) : null;
          rows.push({
            strike: item.strike,
            type: item.type,
            oi_buildup: item.classification || "UNKNOWN",
            iv_rank: ivItem ? ivItem.iv_rank : null,
            security_id: item.security_id || `${underlying}_${item.strike}_${item.type}` // mock security_id
          });
        }
      }

      return rows;
    },
    retry: false
  });

  if (isLoading) return <div className="p-4 text-center text-text-muted">Loading scanner...</div>;

  if (isError) {
    if (error instanceof Error && error.message === "Analytics upgrade required") {
      return (
        <div className="p-8 text-center bg-surface-hover/30 rounded-md border border-surface-border">
          <h3 className="text-lg font-medium text-text-main mb-2">Analytics upgrade required</h3>
          <p className="text-sm text-text-muted">
            Install OI/IV Analytics proposal to enable the Scanner.
          </p>
        </div>
      );
    }
    return <div className="p-4 text-center text-bearish">Failed to load scanner: {(error as Error).message}</div>;
  }

  const columns: ColumnDef<ScannerRow>[] = [
    {
      accessorKey: "strike",
      header: "Strike",
    },
    {
      accessorKey: "type",
      header: "Type",
    },
    {
      accessorKey: "oi_buildup",
      header: "OI Buildup",
      cell: ({ row }) => {
        const buildup = row.original.oi_buildup;
        let variant: "default" | "success" | "danger" | "warning" | "outline" = "outline";
        if (buildup.includes("LONG BUILDUP") || buildup.includes("SHORT COVERING")) variant = "success";
        else if (buildup.includes("SHORT BUILDUP") || buildup.includes("LONG UNWINDING")) variant = "danger";
        return <Badge variant={variant}>{buildup}</Badge>;
      },
    },
    {
      accessorKey: "iv_rank",
      header: "IV Rank",
      cell: ({ row }) => row.original.iv_rank !== null ? `${row.original.iv_rank}%` : "-",
    },
    {
      id: "actions",
      header: "Action",
      cell: ({ row }) => (
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelectedSecurity({ id: row.original.security_id, side: "BUY" })}
          >
            Buy
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSelectedSecurity({ id: row.original.security_id, side: "SELL" })}
          >
            Sell
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <DataTable
        columns={columns}
        data={data || []}
        searchable
        pageSize={10}
        emptyMessage="No scanner data available."
      />

      {selectedSecurity && (
        <OrderEntry
          open={!!selectedSecurity}
          onOpenChange={(open) => !open && setSelectedSecurity(null)}
          prefill={{
            security_id: selectedSecurity.id,
            side: selectedSecurity.side,
            order_type: "LIMIT", // Usually options are traded via LIMIT
          }}
        />
      )}
    </>
  );
}
