import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { DataTable } from "@/components/ui/DataTable";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { AlertForm, type AlertData } from "./AlertForm";
import type { ColumnDef } from "@tanstack/react-table";

interface AlertItem {
  id: number;
  user_id: string;
  security_id: string;
  condition: string;
  threshold: string;
  channels: string[];
  status: string; // ARMED | TRIGGERED | RESOLVED
  created_at: string;
  updated_at: string;
}

function formatCondition(condition: string, threshold: string): string {
  const ops: Record<string, string> = {
    PRICE_GT: `Price > ${threshold}`,
    PRICE_LT: `Price < ${threshold}`,
    DELTA_GT: `Delta > ${threshold}`,
    DELTA_LT: `Delta < ${threshold}`,
    GAMMA_GT: `Gamma > ${threshold}`,
    GAMMA_LT: `Gamma < ${threshold}`,
    VEGA_GT: `Vega > ${threshold}`,
    VEGA_LT: `Vega < ${threshold}`,
    PNL_GT: `P&L > ${threshold}`,
    PNL_LT: `P&L < ${threshold}`,
  };
  return ops[condition] || `${condition} ${threshold}`;
}

function statusVariant(status: string): "success" | "warning" | "danger" | "outline" {
  if (status === "ARMED") return "success";
  if (status === "TRIGGERED") return "warning";
  if (status === "RESOLVED") return "outline";
  return "outline";
}

export function AlertsList() {
  const [editingAlert, setEditingAlert] = useState<AlertData | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);

  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data: alerts = [], isLoading } = useQuery({
    queryKey: ["alerts"],
    queryFn: async () => {
      const res = await fetch("/api/v1/alerts");
      if (!res.ok) throw new Error("Failed to fetch alerts");
      return res.json() as Promise<AlertItem[]>;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/v1/alerts/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete alert");
    },
    onSuccess: () => {
      toast({ title: "Alert Deleted", variant: "success" });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (err: Error) => {
      toast({ title: "Delete Failed", description: err.message, variant: "error" });
    },
  });

  const columns: ColumnDef<AlertItem>[] = [
    {
      accessorKey: "security_id",
      header: "Symbol",
    },
    {
      id: "condition_display",
      header: "Condition",
      cell: ({ row }) => formatCondition(row.original.condition, row.original.threshold),
    },
    {
      accessorKey: "channels",
      header: "Channels",
      cell: ({ row }) => row.original.channels.join(", "),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }) => (
        <Badge variant={statusVariant(row.original.status)}>
          {row.original.status}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setEditingAlert({
                id: row.original.id,
                security_id: row.original.security_id,
                condition: row.original.condition,
                threshold: Number(row.original.threshold),
              });
              setIsFormOpen(true);
            }}
          >
            Edit
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              if (confirm(`Delete alert for ${row.original.security_id}?`)) {
                deleteMutation.mutate(row.original.id);
              }
            }}
          >
            Delete
          </Button>
        </div>
      ),
    },
  ];

  if (isLoading) return <div className="p-4 text-center text-text-muted">Loading alerts...</div>;

  return (
    <>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-medium">Your Alerts</h3>
        <Button onClick={() => { setEditingAlert(null); setIsFormOpen(true); }}>
          New Alert
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={alerts}
        searchable
        pageSize={10}
        emptyMessage="No alerts found. Create one to get started."
      />

      <AlertForm
        open={isFormOpen}
        onOpenChange={(o) => {
          setIsFormOpen(o);
          if (!o) setEditingAlert(null);
        }}
        alertData={editingAlert}
      />
    </>
  );
}
