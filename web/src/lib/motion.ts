// Motion tokens for code that animates outside CSS (UI/UX brief §2.4): the --duration-* tokens in
// milliseconds, read live, so reduced motion (the OS or the setting) makes every animation 0 ms.
export function motionMs(token: "fast" | "base" | "slow"): number {
  if (typeof document === "undefined") return 0;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(`--duration-${token}`).trim();
  const ms = raw.endsWith("ms") ? parseFloat(raw) : raw.endsWith("s") ? parseFloat(raw) * 1000 : NaN;
  return Number.isFinite(ms) ? ms : 0;
}
