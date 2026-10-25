// The offline banner (Implementation Plan D8.3, UI/UX brief §5.15): when the browser loses the network,
// or Sherlock stops answering, a strip says so and that nothing is lost; it goes away by itself once
// `/healthz` answers again (checked every 5 s while it shows).
import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

export function OfflineBanner() {
  const [offline, setOffline] = useState(typeof navigator !== "undefined" && navigator.onLine === false);
  useEffect(() => {
    const down = () => setOffline(true);
    const up = () => setOffline(false);
    window.addEventListener("offline", down);
    window.addEventListener("online", up);
    window.addEventListener("sherlock:offline", down); // an API call that couldn't reach the server
    return () => {
      window.removeEventListener("offline", down);
      window.removeEventListener("online", up);
      window.removeEventListener("sherlock:offline", down);
    };
  }, []);
  useEffect(() => {
    if (!offline) return;
    const t = setInterval(() => {
      fetch("/healthz", { cache: "no-store" }).then((r) => r.ok && setOffline(false)).catch(() => undefined);
    }, 5000);
    return () => clearInterval(t);
  }, [offline]);
  if (!offline) return null;
  return (
    <div role="status" className="flex shrink-0 items-center justify-center gap-2 border-b border-warning bg-[color-mix(in_srgb,var(--warning)_12%,var(--background))] px-4 py-1.5 text-[13px]">
      <WifiOff className="size-3.5 text-warning" aria-hidden />
      Can't reach Sherlock. Your data is safe, and unsaved CSV edits stay in this browser; this clears when the connection is back.
    </div>
  );
}
