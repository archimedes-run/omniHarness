import { useEffect, useState } from "react";

/** The clock, re-read every `ms`: ages ("6 min ago") and countdowns move on
 * their own, without a refetch. */
export function useNow(ms = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
