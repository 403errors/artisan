import { afterEach, describe, expect, it, vi } from "vitest";

import { availableActions, postTicketAction } from "@/lib/ticket-actions";
import { STALE_AFTER_MS } from "@/lib/ticket-status";
import type { TicketStatus } from "@/types/ticket";

const NOW = Date.parse("2026-01-01T00:00:00Z");
const RECENT = new Date(NOW - 60_000).toISOString();
const STALE = new Date(NOW - STALE_AFTER_MS - 1000).toISOString();

function kinds(status: TicketStatus, updatedAt: string) {
  return availableActions({ status, updatedAt }, NOW)
    .map((a) => `${a.kind}:${a.enabled ? "enabled" : "disabled"}`)
    .sort();
}

describe("availableActions", () => {
  it("offers nothing for a done ticket", () => {
    expect(availableActions({ status: "done", updatedAt: RECENT }, NOW)).toEqual([]);
  });

  it("offers escalate and a disabled mark-done while actively working", () => {
    expect(kinds("in_progress", RECENT)).toEqual(["escalate:enabled", "mark-done:disabled"]);
    expect(kinds("intake", RECENT)).toEqual(["escalate:enabled", "mark-done:disabled"]);
  });

  it("also offers retry once a live ticket has gone stale", () => {
    expect(kinds("in_progress", STALE)).toEqual([
      "escalate:enabled",
      "mark-done:disabled",
      "retry:enabled",
    ]);
  });

  it("offers escalate and mark-done for pr_open, no retry", () => {
    expect(kinds("pr_open", RECENT)).toEqual(["escalate:enabled", "mark-done:enabled"]);
  });

  it("uses pr_open-specific wording for escalate and mark-done, distinct from other statuses", () => {
    const prOpenActions = availableActions({ status: "pr_open", updatedAt: RECENT }, NOW);
    const escalate = prOpenActions.find((a) => a.kind === "escalate");
    const markDone = prOpenActions.find((a) => a.kind === "mark-done");
    expect(escalate?.label).toBe("Flag for manual review");
    expect(escalate?.confirm?.title).toBe("Flag this PR for manual review?");
    expect(markDone?.label).toBe("Close ticket");

    const inProgressActions = availableActions({ status: "in_progress", updatedAt: RECENT }, NOW);
    expect(inProgressActions.find((a) => a.kind === "escalate")?.label).toBeUndefined();
  });

  it("offers retry and mark-done for escalated/manual_pickup, no escalate", () => {
    expect(kinds("escalated", RECENT)).toEqual(["mark-done:enabled", "retry:enabled"]);
    expect(kinds("manual_pickup", RECENT)).toEqual(["mark-done:enabled", "retry:enabled"]);
  });
});

describe("postTicketAction", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends an Idempotency-Key header and the given body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await postTicketAction("t1", "escalate", { reason: "test" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tickets/t1/actions/escalate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ reason: "test" }),
      }),
    );
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers["Idempotency-Key"]).toBeTruthy();
  });

  it.each([
    [401, "Your session expired — sign in again."],
    [404, "Ticket not found."],
    [409, "This ticket already changed state. Refresh and try again."],
  ])("maps HTTP %i to a readable message", async (status, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({}) }),
    );
    const result = await postTicketAction("t1", "retry");
    expect(result).toEqual({ ok: false, message });
  });

  it("falls back to a generic message for an unmapped status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }),
    );
    const result = await postTicketAction("t1", "retry");
    expect(result).toEqual({ ok: false, message: "Request failed (500)." });
  });

  it("uses the server error message when present", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: "boom" }) }),
    );
    const result = await postTicketAction("t1", "retry");
    expect(result).toEqual({ ok: false, message: "boom" });
  });

  it("reports a network failure without throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const result = await postTicketAction("t1", "retry");
    expect(result).toEqual({ ok: false, message: "Couldn't reach the server." });
  });
});
