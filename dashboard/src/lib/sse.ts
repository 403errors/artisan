// Generic Firestore-onSnapshot -> Server-Sent-Events bridge. Cleanup on client disconnect is the
// whole point here: without unsubscribing on `signal`'s abort event, every dashboard tab ever
// opened would leak one live Firestore listener server-side forever.
export function sseResponse(
  subscribe: (send: (data: unknown) => void) => () => void,
  signal: AbortSignal,
): Response {
  const encoder = new TextEncoder();
  let unsubscribe: (() => void) | undefined;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (data: unknown) => {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
      };
      unsubscribe = subscribe(send);
      signal.addEventListener("abort", () => {
        unsubscribe?.();
        try {
          controller.close();
        } catch {
          // already closed
        }
      });
    },
    cancel() {
      unsubscribe?.();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
