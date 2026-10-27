// Applies the user's mode, accent and motion settings to <html> (UI brief §9).
import { useEffect } from "react";
import { useMe } from "@/api/queries";

export function ThemeSync() {
  const { data: me } = useMe();
  const s = me?.settings;
  useEffect(() => {
    if (!s) return;
    const root = document.documentElement;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = s.theme === "dark" || (s.theme === "system" && !!media?.matches);
      root.classList.toggle("dark", dark);
    };
    apply();
    root.dataset.accent = s.accent;
    if (s.reduce_motion === "system") delete root.dataset.reduceMotion;
    else root.dataset.reduceMotion = s.reduce_motion;
    media?.addEventListener?.("change", apply);
    return () => media?.removeEventListener?.("change", apply);
  }, [s]);
  return null;
}
