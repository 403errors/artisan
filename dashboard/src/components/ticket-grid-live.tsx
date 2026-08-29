"use client";

import { useEffect, useMemo, useState } from "react";

import { TicketFilterBar } from "@/components/ticket-filter-bar";
import { TicketGrid } from "@/components/ticket-grid";
import { BUCKET_ORDER, bucketOf, type StatusBucket } from "@/lib/ticket-status";
import type { TicketSummary } from "@/types/ticket";

function sortByUpdatedDesc(tickets: TicketSummary[]): TicketSummary[] {
  return [...tickets].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
}

function syncBucketsToUrl(buckets: StatusBucket[]) {
  const url = new URL(window.location.href);
  if (buckets.length === 0) {
    url.searchParams.delete("show");
  } else {
    url.searchParams.set("show", buckets.join(","));
  }
  window.history.replaceState(null, "", url);
}

export function TicketGridLive({
  initial,
  emptyMessage,
  streamUrl = "/api/tickets/stream",
  showFilter = true,
  initialBuckets = [],
}: {
  initial: TicketSummary[];
  emptyMessage: string;
  streamUrl?: string;
  showFilter?: boolean;
  initialBuckets?: StatusBucket[];
}) {
  const [tickets, setTickets] = useState(() => sortByUpdatedDesc(initial));
  const [selected, setSelected] = useState<StatusBucket[]>(initialBuckets);

  useEffect(() => {
    const es = new EventSource(streamUrl);
    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (Array.isArray(data)) setTickets(sortByUpdatedDesc(data));
    };
    return () => es.close();
  }, [streamUrl]);

  const counts = useMemo(() => {
    const result: Record<StatusBucket, number> = {
      active: 0,
      review: 0,
      urgent: 0,
      resolved: 0,
    };
    for (const ticket of tickets) result[bucketOf(ticket.status)] += 1;
    return result;
  }, [tickets]);

  const filtered = useMemo(() => {
    if (selected.length === 0) return tickets;
    return tickets.filter((t) => selected.includes(bucketOf(t.status)));
  }, [tickets, selected]);

  const hiddenActiveCount =
    selected.length > 0 && !selected.includes("active") ? counts.active : 0;

  function updateSelected(next: StatusBucket[]) {
    setSelected(next);
    syncBucketsToUrl(next);
  }

  const isFiltering = selected.length > 0 && selected.length < BUCKET_ORDER.length;

  return (
    <>
      {showFilter ? (
        <TicketFilterBar
          counts={counts}
          selected={selected}
          onChange={updateSelected}
          total={tickets.length}
          hiddenActiveCount={hiddenActiveCount}
          onShowActive={() => updateSelected([...selected, "active"])}
        />
      ) : null}
      <TicketGrid
        tickets={filtered}
        emptyMessage={emptyMessage}
        emptyHint={isFiltering ? "No tickets match this filter." : undefined}
      />
    </>
  );
}
