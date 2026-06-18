import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { useDebounce } from "@/hooks/useDebounce";

export interface Instrument {
  security_id: string;
  name: string;
  exchange: string;
  segment: string;
  instrument_type: string;
  underlying: string | null;
  expiry: string | null;
  strike: number | null;
  option_type: string | null;
}

interface InstrumentPickerProps {
  value: string;
  onChange: (securityId: string) => void;
  onSelect?: (instrument: Instrument) => void;
  /** Human-readable label to display when value is pre-filled (e.g. from prefill prop) */
  displayValue?: string;
  placeholder?: string;
  className?: string;
}

export function InstrumentPicker({ value, onChange, onSelect, displayValue, placeholder = "Search instrument...", className }: InstrumentPickerProps) {
  const [search, setSearch] = useState(displayValue || "");
  const debouncedSearch = useDebounce(search, 300);
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Sync when external prefill changes
  useEffect(() => {
    if (value) {
      setSearch(displayValue || value);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, displayValue]);

  const { data: instruments, isFetching } = useQuery({
    queryKey: ["instruments", "search", debouncedSearch],
    queryFn: async () => {
      if (!debouncedSearch) return [];
      const res = await fetch(`/api/v1/instruments?search=${encodeURIComponent(debouncedSearch)}`);
      if (!res.ok) throw new Error("Failed to fetch");
      return (await res.json()) as Instrument[];
    },
    enabled: debouncedSearch.length >= 2,
  });

  // Close dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className={`relative ${className || ""}`} ref={containerRef}>
      <Input
        type="text"
        placeholder={placeholder}
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setIsOpen(true);
        }}
        onFocus={() => setIsOpen(true)}
      />
      {isOpen && debouncedSearch.length >= 2 && (
        <div className="absolute z-10 w-full mt-1 bg-surface border border-surface-border rounded-md shadow-lg max-h-60 overflow-auto">
          {isFetching ? (
            <div className="p-2 text-sm text-text-muted">Searching...</div>
          ) : instruments && instruments.length > 0 ? (
            <ul className="py-1">
              {instruments.map((inst) => (
                <li
                  key={inst.security_id}
                  className="px-3 py-2 hover:bg-surface-hover cursor-pointer text-sm flex items-center justify-between"
                  onClick={() => {
                    setSearch(inst.name || inst.security_id);
                    onChange(inst.security_id);
                    onSelect?.(inst);
                    setIsOpen(false);
                  }}
                >
                  <span className="font-medium text-text">{inst.name}</span>
                  <div className="flex gap-2 items-center">
                    <span className="text-xs text-text-muted">{inst.security_id}</span>
                    <Badge variant="outline">{inst.exchange}</Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-2 text-sm text-text-muted">No instruments found.</div>
          )}
        </div>
      )}
    </div>
  );
}
