// Loose by design: the backend event-log shape (Track 2 of the dashboard
// overhaul) isn't wired up yet, and even once it is, this type must not break
// if a field is renamed or an unrecognized `type` value appears — normalizeEvent
// (lib/ticket-events.ts) never throws on unexpected input.
export interface TicketEvent {
  id: string;
  at: string; // ISO
  type: string;
  gate: "1" | "2" | "3" | null;
  summary: string;
  detail?: string;
  toolName?: string;
  args?: unknown;
  result?: unknown;
  status?: "ok" | "error" | "pending";
  extra?: Record<string, unknown>;
}
