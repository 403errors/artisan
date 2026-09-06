import { useEffect, useRef, useState } from "react";

import { useEventSource } from "@/hooks/use-event-source";
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
  const gotMessage = useRef(false);

  // Reset per ticket — a prior ticket's delivered frame must not suppress this one's fallback.
  // (Declared before useEventSource so it runs first; effects run in declaration order.)
  useEffect(() => {
    gotMessage.current = false;
  }, [ticketId]);

  function applyFrame(data: unknown) {
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
        setUnavailable(true);
        return;
      }
      applyFrame(await res.json());
    } catch {
      setUnavailable(true);
    }
  }

  useEventSource(
    `/api/tickets/${ticketId}/events/stream`,
    (data) => {
      gotMessage.current = true;
      applyFrame(data);
    },
    (es) => {
      // Only fall back when the stream never delivered — a mid-stream error is
      // EventSource's own retry concern, not a missing-route signal.
      if (!gotMessage.current) {
        es?.close();
        void fallbackFetch();
      }
    },
  );

  return { events, unavailable };
}
