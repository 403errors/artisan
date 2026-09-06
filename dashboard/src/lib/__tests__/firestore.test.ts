import { afterEach, describe, expect, it, vi } from "vitest";

const constructorSpy = vi.fn();

vi.mock("@google-cloud/firestore", () => ({
  Firestore: class {
    constructor(options: unknown) {
      constructorSpy(options);
    }
  },
}));

describe("getFirestore", () => {
  afterEach(() => {
    vi.resetModules();
    constructorSpy.mockClear();
  });

  it("constructs the client with the configured GCP project", async () => {
    const { getFirestore } = await import("@/lib/firestore");
    getFirestore();
    expect(constructorSpy).toHaveBeenCalledWith({ projectId: "artisan-multiagent-ai" });
  });

  it("is a singleton — one client per process", async () => {
    const { getFirestore } = await import("@/lib/firestore");
    const first = getFirestore();
    const second = getFirestore();
    expect(second).toBe(first);
    expect(constructorSpy).toHaveBeenCalledTimes(1);
  });
});
