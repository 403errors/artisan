import { useEffect, useRef } from "react";

// Shared EventSource lifecycle: open on mount/url change, parse each frame as JSON, close on
// unmount. Malformed frames are ignored rather than crashing the feed. Callbacks are read
// through refs so inline handlers don't resubscribe on every render — only `url` does.
export function useEventSource(
  url: string,
  onMessage: (data: unknown) => void,
  onError?: (es: EventSource | null) => void,
) {
  const messageRef = useRef(onMessage);
  messageRef.current = onMessage;
  const errorRef = useRef(onError);
  errorRef.current = onError;

  useEffect(() => {
    let es: EventSource;
    try {
      es = new EventSource(url);
    } catch {
      errorRef.current?.(null);
      return;
    }
    es.onmessage = (event) => {
      try {
        messageRef.current(JSON.parse(event.data));
      } catch {
        // malformed frame — ignore rather than crash the feed
      }
    };
    es.onerror = () => errorRef.current?.(es);
    return () => es.close();
  }, [url]);
}
