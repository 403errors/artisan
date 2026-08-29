import { useEffect, useState } from "react";

import { normalizeEvent } from "@/lib/ticket-events";
import type { TicketEvent } from "@/types/ticket-event";

function sortByAt(events: TicketEvent[]): TicketEvent[] {
  return [...events].sort((a, b) => a.at.localeCompare(b.at));
}

function mergeEvent(prev: TicketEvent[], next: TicketEvent): TicketEvent[] {
  const existingIndex = prev.findIndex((e) => e.id === next.id);
  if (existingIndex === -1) return sortByAt([...prev, next]);
  const copy = [...prev];
  copy[existingIndex] = next;
  return copy;
}

// The backend event-log route may not exist yet (Track 2 of the dashboard
// overhaul ships independently) — this hook is the single seam that talks to
// it, so once the real route lands, only this file needs to change. It tries
// SSE first, falls back to a one-shot fetch, and reports `unavailable` rather
// than throwing if neither works.
export function useTicketEvents(ticketId: string): { events: TicketEvent[]; unavailable: boolean } {
  const [events, setEvents] = useState<TicketEvent[]>([]);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let gotMessage = false;

    function applyFrame(data: unknown) {
      if (cancelled) return;
      if (Array.isArray(data)) {
        setEvents(sortByAt(data.map((raw, i) => normalizeEvent(raw, i))));
      } else if (data && typeof data === "object") {
        setEvents((prev) => mergeEvent(prev, normalizeEvent(data, prev.length)));
      }
    }

    async function fallbackFetch() {
      try {
        const res = await fetch(`/api/tickets/${ticketId}/events`);
        if (!res.ok) {
          if (!cancelled) setUnavailable(true);
          return;
        }
        applyFrame(await res.json());
      } catch {
        if (!cancelled) setUnavailable(true);
      }
    }

    try {
      es = new EventSource(`/api/tickets/${ticketId}/events/stream`);
      es.onmessage = (event) => {
        gotMessage = true;
        try {
          applyFrame(JSON.parse(event.data));
        } catch {
          // malformed frame — ignore rather than crash the feed
        }
      };
      es.onerror = () => {
        if (!gotMessage) {
          es?.close();
          void fallbackFetch();
        }
      };
    } catch {
      void fallbackFetch();
    }

    return () => {
      cancelled = true;
      es?.close();
    };
  }, [ticketId]);

  return { events, unavailable };
}
