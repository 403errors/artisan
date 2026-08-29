import { describe, expect, it } from "vitest";

import { groupByGate, normalizeEvent } from "@/lib/ticket-events";

describe("normalizeEvent", () => {
  it("reads snake_case fields", () => {
    const event = normalizeEvent(
      {
        id: "e1",
        at: "2026-01-01T00:00:00Z",
        type: "tool_call",
        gate: "2",
        summary: "read_file(path=index.html)",
        tool_name: "read_file",
        tool_args: { path: "index.html" },
      },
      0,
    );
    expect(event).toMatchObject({
      id: "e1",
      type: "tool_call",
      gate: "2",
      summary: "read_file(path=index.html)",
      toolName: "read_file",
      args: { path: "index.html" },
    });
  });

  it("reads the equivalent camelCase fields", () => {
    const event = normalizeEvent(
      { id: "e2", at: "2026-01-01T00:00:00Z", type: "tool_call", toolName: "write_file", toolArgs: { path: "a.ts" } },
      0,
    );
    expect(event.toolName).toBe("write_file");
    expect(event.args).toEqual({ path: "a.ts" });
  });

  it("falls back to a humanized label when summary is missing", () => {
    const event = normalizeEvent({ type: "gate_started" }, 0);
    expect(event.summary).toBe("Gate started");
  });

  it("renders an unknown type gracefully instead of crashing", () => {
    const event = normalizeEvent({ type: "something_new_from_the_backend" }, 0);
    expect(event.type).toBe("something_new_from_the_backend");
    expect(event.summary).toBe("Something New From The Backend");
  });

  it("never throws on garbage input", () => {
    expect(() => normalizeEvent(null, 0)).not.toThrow();
    expect(() => normalizeEvent(undefined, 0)).not.toThrow();
    expect(() => normalizeEvent("not an object", 0)).not.toThrow();
    expect(() => normalizeEvent(42, 0)).not.toThrow();

    const event = normalizeEvent(null, 3);
    expect(event.type).toBe("unknown");
    expect(event.id).toContain("unknown-3");
  });

  it("collects unrecognized fields into extra", () => {
    const event = normalizeEvent({ type: "tool_call", weird_field: "value" }, 0);
    expect(event.extra).toEqual({ weird_field: "value" });
  });
});

describe("groupByGate", () => {
  it("groups consecutive events with the same gate", () => {
    const events = [
      { id: "1", at: "t1", type: "a", gate: "1" as const, summary: "a" },
      { id: "2", at: "t2", type: "b", gate: "1" as const, summary: "b" },
      { id: "3", at: "t3", type: "c", gate: "2" as const, summary: "c" },
      { id: "4", at: "t4", type: "d", gate: "1" as const, summary: "d" },
    ];
    const groups = groupByGate(events);
    expect(groups).toHaveLength(3);
    expect(groups[0]).toMatchObject({ gate: "1", events: [events[0], events[1]] });
    expect(groups[1]).toMatchObject({ gate: "2", events: [events[2]] });
    expect(groups[2]).toMatchObject({ gate: "1", events: [events[3]] });
  });

  it("returns an empty array for no events", () => {
    expect(groupByGate([])).toEqual([]);
  });
});
