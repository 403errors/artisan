import { useEffect, useState } from "react";

// Returns null until mounted, then the current time, ticking every
// `intervalMs`. Callers should treat `null` as "assume fresh" so server and
// first client render agree (relative-time/staleness checks must not read
// Date.now() during render, or React logs a hydration mismatch).
export function useNow(intervalMs = 30_000): number | null {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
