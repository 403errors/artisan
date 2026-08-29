import { describe, expect, it } from "vitest";

import {
  BUCKET_ORDER,
  STALE_AFTER_MS,
  bucketOf,
  isActivelyWorking,
  isLive,
  isStalled,
} from "@/lib/ticket-status";
import type { TicketStatus } from "@/types/ticket";

describe("bucketOf", () => {
  const CASES: Array<[TicketStatus, string]> = [
    ["intake", "active"],
    ["in_progress", "active"],
    ["pr_open", "review"],
    ["manual_pickup", "review"],
    ["escalated", "urgent"],
    ["done", "resolved"],
  ];

  it.each(CASES)("maps %s to bucket %s", (status, bucket) => {
    expect(bucketOf(status)).toBe(bucket);
  });

  it("every bucket in BUCKET_ORDER is reachable", () => {
    const reached = new Set(CASES.map(([, bucket]) => bucket));
    expect(new Set(BUCKET_ORDER)).toEqual(reached);
  });
});

describe("isLive", () => {
  it("is true only for intake/in_progress", () => {
    expect(isLive("intake")).toBe(true);
    expect(isLive("in_progress")).toBe(true);
    expect(isLive("pr_open")).toBe(false);
    expect(isLive("escalated")).toBe(false);
    expect(isLive("manual_pickup")).toBe(false);
    expect(isLive("done")).toBe(false);
  });
});

describe("isActivelyWorking / isStalled", () => {
  const NOW = Date.parse("2026-01-01T00:00:00Z");

  it("treats a non-live status as neither working nor stalled", () => {
    const ticket = { status: "done" as TicketStatus, updatedAt: new Date(NOW).toISOString() };
    expect(isActivelyWorking(ticket, NOW)).toBe(false);
    expect(isStalled(ticket, NOW)).toBe(false);
  });

  it("treats a live status with a recent update as actively working", () => {
    const ticket = {
      status: "in_progress" as TicketStatus,
      updatedAt: new Date(NOW - 60_000).toISOString(),
    };
    expect(isActivelyWorking(ticket, NOW)).toBe(true);
    expect(isStalled(ticket, NOW)).toBe(false);
  });

  it("treats a live status with a stale update as stalled", () => {
    const ticket = {
      status: "in_progress" as TicketStatus,
      updatedAt: new Date(NOW - STALE_AFTER_MS - 1000).toISOString(),
    };
    expect(isActivelyWorking(ticket, NOW)).toBe(false);
    expect(isStalled(ticket, NOW)).toBe(true);
  });

  it("assumes fresh when now is null (not yet mounted)", () => {
    const ticket = {
      status: "intake" as TicketStatus,
      updatedAt: new Date(0).toISOString(),
    };
    expect(isActivelyWorking(ticket, null)).toBe(true);
    expect(isStalled(ticket, null)).toBe(false);
  });
});
