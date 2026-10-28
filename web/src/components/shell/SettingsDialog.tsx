// Settings (UI brief §5.11, App Flow §13). Cut 1 keeps four settings: mode, accent, chat bar and
// after upload; cleaning depth (PRD CLEAN-15) is a fifth. Changes apply at once and save to the profile; the mode and accent preview live.
// `?settings=1` opens the dialog; `&field=after_upload` scrolls to that field and marks it (the
// "Change" links on screens the setting opened by itself, App Flow §4).
import { useEffect, useRef, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useMe, useSaveSettings } from "@/api/queries";
import type { Depth, Settings } from "@/api/types";
import { LAYERS } from "@/components/dataset/depth";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/segmented";
import { cn } from "@/lib/utils";

const ACCENTS: { value: Settings["accent"]; label: string; light: string; dark: string }[] = [
  { value: "verdigris", label: "Verdigris", light: "#13756E", dark: "#5CC2B7" },
  { value: "arcane", label: "Arcane", light: "#6B4BD6", dark: "#AB95F6" },
  { value: "ember", label: "Ember", light: "#B8471D", dark: "#FF9A72" },
  { value: "aether", label: "Aether", light: "#2F62C9", dark: "#84A9F4" },
  { value: "brass", label: "Brass", light: "#93650F", dark: "#E0B25C" },
];

export function useSettingsOpen() {
  const [params, setParams] = useSearchParams();
  const open = params.get("settings") === "1";
  const setOpen = (next: boolean) => {
    const p = new URLSearchParams(params);
    if (next) p.set("settings", "1");
    else {
      p.delete("settings");
      p.delete("field");
    }
    setParams(p, { replace: true });
  };
  const openAt = (field: string) => {
    const p = new URLSearchParams(params);
    p.set("settings", "1");
    p.set("field", field);
    setParams(p, { replace: true });
  };
  return [open, setOpen, openAt] as const;
}

export function SettingsDialog() {
  const [open, setOpen] = useSettingsOpen();
  const [params] = useSearchParams();
  const field = params.get("field");
  const { data: me } = useMe();
  const save = useSaveSettings();
  const s = me?.settings;
  const set = (patch: Partial<Settings>) => save.mutate(patch);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[600px]" aria-describedby={undefined}>
        <div className="px-7 pb-1 pt-6">
          <DialogTitle className="type-display">Settings</DialogTitle>
        </div>
        {s && (
          <div className="flex min-h-0 flex-1 flex-col divide-y divide-border overflow-y-auto px-7 py-2">
            <Field label="Appearance" help="System follows your computer.">
              <Segmented label="Mode" value={s.theme} onChange={(theme) => set({ theme })}
                options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "System" }]} />
            </Field>
            <Field label="Accent" help="Marks focus and what you've selected.">
              <Segmented label="Accent" value={s.accent} onChange={(accent) => set({ accent })}
                options={ACCENTS.map((a) => ({
                  value: a.value,
                  label: (
                    <>
                      <span aria-hidden className="size-2.5 rounded-full dark:hidden" style={{ background: a.light }} />
                      <span aria-hidden className="hidden size-2.5 rounded-full dark:inline-block" style={{ background: a.dark }} />
                      {a.label}
                    </>
                  ),
                }))} />
            </Field>
            <Field label="Chat bar" help="Auto-hide shows it when you point at it.">
              <Segmented label="Chat bar" value={s.chatbar} onChange={(chatbar) => set({ chatbar })}
                options={[{ value: "pinned", label: "Pinned" }, { value: "autohide", label: "Auto-hide" }, { value: "hidden", label: "Hidden" }]} />
            </Field>
            <Field label="After upload" help="Nothing is cleaned until you start a plan."
              focus={field === "after_upload"}>
              <Segmented label="After upload" value={s.after_upload} onChange={(after_upload) => set({ after_upload })}
                options={[{ value: "ask", label: "Ask me" }, { value: "always", label: "Open the cleaning plan" },
                          { value: "never", label: "I'll clean it myself" }]} />
            </Field>
            <Field label="Cleaning depth" help="Deeper layers check wider parts of the data."
              focus={field === "clean_depth"}>
              <Segmented label="Cleaning depth" value={String(s.clean_depth)}
                onChange={(v) => set({ clean_depth: Number(v) as Depth })}
                options={LAYERS.map((l, n) => ({ value: String(n + 1), label: l.name }))} />
            </Field>
          </div>
        )}
        <div className="flex items-center gap-3 border-t border-border px-7 py-4">
          <span className="mr-auto text-[13px] text-muted-foreground">Changes save as you go</span>
          <DialogClose asChild>
            <Button variant="primary">Done</Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, help, focus = false, children }: { label: string; help: string; focus?: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focus) ref.current?.scrollIntoView({ block: "center" });
  }, [focus]);
  return (
    <div ref={ref} className={cn("flex flex-col gap-2.5 py-4", focus && "-mx-3 rounded-2xl bg-accent-soft px-3")}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[14px] font-semibold tracking-[-0.01em]">{label}</span>
        <span className="text-right text-[12.5px] text-muted-foreground">{help}</span>
      </div>
      {children}
    </div>
  );
}
