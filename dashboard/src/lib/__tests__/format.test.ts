import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatDateTime, looksLikeCode, relativeTime, stepLabel } from "@/lib/format";

describe("formatDateTime", () => {
  it("renders a fixed en-US format regardless of runtime locale", () => {
    expect(formatDateTime("2026-08-30T14:05:06Z")).toMatch(
      /^\d{1,2}\/\d{1,2}\/\d{4}, \d{1,2}:\d{2}:\d{2}/,
    );
  });
});

describe("relativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-06T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("reports seconds-old timestamps as just now", () => {
    expect(relativeTime("2026-09-06T11:59:30Z")).toBe("just now");
  });

  it("reports minutes, hours, and days with unit suffixes", () => {
    expect(relativeTime("2026-09-06T11:45:00Z")).toBe("15m ago");
    expect(relativeTime("2026-09-06T07:00:00Z")).toBe("5h ago");
    expect(relativeTime("2026-09-03T12:00:00Z")).toBe("3d ago");
  });
});

describe("stepLabel", () => {
  it("title-cases the head word and splits underscores", () => {
    expect(stepLabel("executing (attempt 2)")).toBe("Executing (attempt 2)");
    expect(stepLabel("domain_expert")).toBe("Domain Expert");
  });
});

describe("looksLikeCode", () => {
  it("detects unified-diff content", () => {
    expect(looksLikeCode("diff --git a/x.ts b/x.ts\n+added")).toBe(true);
    expect(looksLikeCode("@@ -1,2 +1,2 @@")).toBe(true);
  });

  it("treats short plain prose as prose", () => {
    expect(looksLikeCode("Fixed the null check.")).toBe(false);
  });

  it("treats long multi-line or long-line text as code-ish", () => {
    expect(looksLikeCode("a\nb\nc\nd")).toBe(true);
    expect(looksLikeCode("x".repeat(121))).toBe(true);
  });
});
