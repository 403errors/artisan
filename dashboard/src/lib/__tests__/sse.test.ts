import { describe, expect, it } from "vitest";

import { sseResponse } from "@/lib/sse";

async function readFrame(response: Response): Promise<string> {
  const reader = response.body!.getReader();
  const { value } = await reader.read();
  return new TextDecoder().decode(value);
}

describe("sseResponse", () => {
  it("returns an SSE response with the right headers", () => {
    const res = sseResponse(() => () => {}, new AbortController().signal);
    expect(res.headers.get("Content-Type")).toBe("text/event-stream");
    expect(res.headers.get("Cache-Control")).toBe("no-cache, no-transform");
  });

  it("writes each sent payload as a JSON data frame", async () => {
    const controller = new AbortController();
    const res = sseResponse(
      (send) => {
        send({ hello: "world" });
        return () => {};
      },
      controller.signal,
    );
    expect(await readFrame(res)).toBe('data: {"hello":"world"}\n\n');
    controller.abort();
  });

  it("unsubscribes and closes the stream when the signal aborts", async () => {
    const controller = new AbortController();
    let unsubscribed = false;
    const res = sseResponse(
      () => () => {
        unsubscribed = true;
      },
      controller.signal,
    );

    controller.abort();
    // Give the abort listener a microtask turn to run.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(unsubscribed).toBe(true);
    const reader = res.body!.getReader();
    expect((await reader.read()).done).toBe(true);
  });
});
