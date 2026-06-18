import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { InstrumentPicker } from "@/components/orders/InstrumentPicker";
import { useToast } from "@/components/ui/Toast";

export interface AlertData {
  id?: number;
  security_id: string;
  condition: string;
  threshold: number;
}

interface AlertFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  alertData?: AlertData | null;
}

const CONDITION_OPTIONS = [
  { value: "PRICE_GT", label: "Price above (>)" },
  { value: "PRICE_LT", label: "Price below (<)" },
  { value: "DELTA_GT", label: "Delta above (>)" },
  { value: "DELTA_LT", label: "Delta below (<)" },
  { value: "GAMMA_GT", label: "Gamma above (>)" },
  { value: "GAMMA_LT", label: "Gamma below (<)" },
  { value: "VEGA_GT", label: "Vega above (>)" },
  { value: "VEGA_LT", label: "Vega below (<)" },
  { value: "PNL_GT", label: "P&L above (>)" },
  { value: "PNL_LT", label: "P&L below (<)" },
];

export function AlertForm({ open, onOpenChange, alertData }: AlertFormProps) {
  const [securityId, setSecurityId] = useState("");
  const [condition, setCondition] = useState("PRICE_GT");
  const [threshold, setThreshold] = useState<number | string>("");

  const { toast } = useToast();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (open) {
      if (alertData) {
        setSecurityId(alertData.security_id || "");
        setCondition(alertData.condition || "PRICE_GT");
        setThreshold(alertData.threshold ?? "");
      } else {
        setSecurityId("");
        setCondition("PRICE_GT");
        setThreshold("");
      }
    }
  }, [open, alertData]);

  const isEditing = !!alertData?.id;

  const mutation = useMutation({
    mutationFn: async () => {
      if (isEditing) {
        const res = await fetch(`/api/v1/alerts/${alertData!.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ threshold: Number(threshold) })
        });
        if (!res.ok) throw new Error("Failed to update alert");
        return res.json();
      } else {
        const res = await fetch("/api/v1/alerts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            security_id: securityId,
            condition,
            threshold: Number(threshold),
          })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "Failed to create alert");
        }
        return res.json();
      }
    },
    onSuccess: () => {
      toast({
        title: isEditing ? "Alert Updated" : "Alert Created",
        variant: "success"
      });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      onOpenChange(false);
    },
    onError: (err: Error) => {
      toast({ title: "Operation Failed", description: err.message || "An error occurred", variant: "error" });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Alert" : "Create Alert"}</DialogTitle>
          <DialogDescription>
            {isEditing ? "Update the threshold value." : "Set a condition to be notified when triggered."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Instrument</label>
            <InstrumentPicker
              className="col-span-3"
              value={securityId}
              onChange={setSecurityId}
            />
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Condition</label>
            <Select
              className="col-span-3"
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              disabled={isEditing}
            >
              {CONDITION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-4 items-center gap-4">
            <label className="text-sm font-medium text-right">Threshold</label>
            <Input
              type="number"
              step="any"
              className="col-span-3"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder="Trigger value"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !securityId || threshold === ""}
          >
            {mutation.isPending ? "Saving..." : isEditing ? "Update Alert" : "Create Alert"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
