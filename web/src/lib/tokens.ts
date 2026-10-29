// Design tokens as concrete colors for canvas drawing (the CSV grid): a canvas can't read
// `var(--accent)` or `color-mix()`, so each token is resolved through a probe element and a 1 × 1
// canvas to `rgba()`.
export function resolveToken(name: string): string {
  if (typeof document === "undefined") return "rgba(0,0,0,1)";
  const probe = document.createElement("span");
  probe.style.color = `var(${name})`;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const computed = getComputedStyle(probe).color;
  probe.remove();
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d");
  if (!ctx) return computed;
  ctx.fillStyle = computed;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgba(${r},${g},${b},${(a / 255).toFixed(3)})`;
}

export function resolveTokens<K extends string>(names: Record<K, string>): Record<K, string> {
  const out = {} as Record<K, string>;
  for (const [k, v] of Object.entries(names) as [K, string][]) out[k] = resolveToken(v);
  return out;
}
