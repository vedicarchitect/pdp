import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { unreadEventsStore, type SystemEvent } from "@/hooks/useEventsWS";
import { EventCard } from "./EventCard";
import { EventFilters, defaultFilters, applyFilters } from "./EventFilters";

const PAGE_SIZE = 50;

export function EventFeed() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState(defaultFilters());
  const [page, setPage] = useState(0);

  // Clear unread badge when the events page is open
  useEffect(() => {
    unreadEventsStore.clear();
  }, []);

  const { data: allEvents, isLoading } = useQuery({
    queryKey: ["events"],
    queryFn: async () => {
      const res = await fetch("/api/v1/events?limit=500");
      if (!res.ok) throw new Error("Failed to fetch events");
      const data = await res.json();
      return data.events as SystemEvent[];
    },
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });

  // Reset page when filters change
  useEffect(() => setPage(0), [filters]);

  const filtered = applyFilters(allEvents ?? [], filters);
  const paginated = filtered.slice(0, (page + 1) * PAGE_SIZE);
  const hasMore = paginated.length < filtered.length;

  const loadMore = () => {
    // Also fetch more from the server using offset
    const currentLimit = (page + 2) * PAGE_SIZE;
    fetch(`/api/v1/events?limit=${currentLimit}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.events) {
          queryClient.setQueryData<SystemEvent[]>(["events"], d.events);
        }
      })
      .catch(() => {});
    setPage((p) => p + 1);
  };

  return (
    <div className="flex flex-col gap-3">
      <EventFilters value={filters} onChange={setFilters} totalCount={filtered.length} />

      {isLoading ? (
        <div className="p-8 text-center text-text-muted text-sm">Loading event stream…</div>
      ) : filtered.length === 0 ? (
        <div className="p-8 text-center text-text-muted text-sm">No events match the current filters.</div>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            {paginated.map((e) => (
              <EventCard key={e.id} event={e} />
            ))}
          </div>

          {hasMore && (
            <button
              onClick={loadMore}
              className="self-center px-4 py-1.5 text-xs rounded-md bg-surface-raised hover:bg-surface-hover text-text-muted border border-surface-border transition-colors"
            >
              Load more ({filtered.length - paginated.length} remaining)
            </button>
          )}
        </>
      )}
    </div>
  );
}
